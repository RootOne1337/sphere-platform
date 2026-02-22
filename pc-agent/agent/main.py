"""
Точка входа PC Agent.
Запуск: python -m agent.main
"""
from __future__ import annotations

import asyncio
import signal
import sys

from loguru import logger

from .adb_bridge import AdbBridgeManager
from .client import AgentWebSocketClient
from .dispatcher import CommandDispatcher
from .ldplayer import LDPlayerManager
from .telemetry import TelemetryReporter
from .topology import TopologyReporter


async def adb_sync_loop(adb_bridge: AdbBridgeManager) -> None:
    """Каждые 15 секунд синхронизировать ADB-соединения."""
    while True:
        try:
            await asyncio.sleep(15)
            await adb_bridge.sync_connections()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"ADB sync ошибка: {exc!r}")


async def main() -> None:
    logger.info("Sphere Platform PC Agent starting…")

    ldplayer_mgr = LDPlayerManager()
    adb_bridge = AdbBridgeManager(ldplayer_mgr)

    # dispatcher создаётся без ws_client — ссылка подставляется ниже
    dispatcher = CommandDispatcher(ldplayer_mgr, adb_bridge)

    ws_client = AgentWebSocketClient(on_message=dispatcher.dispatch)
    # Обратная ссылка — dispatcher отправляет ответы через ws_client
    dispatcher.ws_client = ws_client

    telemetry = TelemetryReporter(ws_client, ldplayer_mgr)
    topology = TopologyReporter(ws_client, ldplayer_mgr)

    stop_event = asyncio.Event()

    # asyncio.add_signal_handler работает ТОЛЬКО на Unix/macOS.
    # На Windows SIGTERM не поддерживается в asyncio — используем signal.signal().
    if sys.platform == "win32":
        def _win_stop_handler(signum: int, frame: object) -> None:
            logger.info(f"Signal {signum} получен, завершаем работу")
            asyncio.get_event_loop().call_soon_threadsafe(stop_event.set)

        signal.signal(signal.SIGINT, _win_stop_handler)
        try:
            signal.signal(signal.SIGBREAK, _win_stop_handler)  # Ctrl+Break
        except AttributeError:
            pass
    else:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

    # Отправить топологию сразу после первого подключения
    async def on_connected_once() -> None:
        await asyncio.sleep(1.0)  # небольшая пауза — WS auth проходит чуть позже
        await topology.report_on_connect()

    tasks = [
        asyncio.create_task(ws_client.run(), name="ws_client"),
        asyncio.create_task(telemetry.run(), name="telemetry"),
        asyncio.create_task(adb_sync_loop(adb_bridge), name="adb_sync"),
        asyncio.create_task(on_connected_once(), name="topology_init"),
    ]

    await stop_event.wait()
    logger.info("Shutdown сигнал получен, завершаем задачи…")

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await ws_client.stop()
    logger.info("PC Agent остановлен")


if __name__ == "__main__":
    asyncio.run(main())
