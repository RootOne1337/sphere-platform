"""Run the PC Agent entry point with an in-process delayed transport and no ADB."""

import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "pc-agent"))

from agent import main as entrypoint
from agent.client import AgentWebSocketClient


async def test_delayed_start():
    report_started = asyncio.Event()
    transport_connected = asyncio.Event()
    messages = []

    class DelayedClient(AgentWebSocketClient):
        async def run(self):
            await report_started.wait()
            self._connected = True
            transport_connected.set()
            await asyncio.Event().wait()

        async def send(self, message):
            messages.append({"type": message["type"], "connected": self._connected})
            await super().send(message)
            if message["type"] == "workstation_register":
                report_started.set()

    async def park(*_):
        await asyncio.Event().wait()

    instance = None

    def client_factory(**kwargs):
        nonlocal instance
        instance = DelayedClient(**kwargs)
        return instance

    with patch.multiple(entrypoint, LDPlayerManager=object,
                        AdbBridgeManager=lambda _: object(),
                        AgentWebSocketClient=client_factory,
                        TelemetryReporter=lambda *_: SimpleNamespace(run=park),
                        adb_sync_loop=park,
                        signal=SimpleNamespace(SIGINT=2, SIGTERM=15, signal=lambda *_: None),
                        sys=SimpleNamespace(platform="win32")), patch.object(
        entrypoint.TopologyReporter, "_build_registration",
        AsyncMock(return_value=SimpleNamespace(instances=[], hostname="fixture",
                                               ip_address="127.0.0.1", model_dump=lambda: {})),
    ):
        # Inspect the real queue after the first successful connection.
        agent = asyncio.create_task(entrypoint.main())
        try:
            await asyncio.wait_for(transport_connected.wait(), timeout=3)
            await asyncio.sleep(0)
            return {"connection_established": instance._connected,
                    "registration_calls": messages, "queued_after_connect": instance._send_queue.qsize()}
        finally:
            agent.cancel()
            await asyncio.gather(agent, return_exceptions=True)
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    entrypoint.logger.remove()
    print(json.dumps(asyncio.run(test_delayed_start()), indent=2))
