"""Actual client lifecycle with deterministic, in-process WebSocket boundaries."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class Socket:
    def __init__(self, *, auth_error=None, send_error=None, auth_gate=None):
        self.auth_error = auth_error
        self.send_error = send_error
        self.auth_gate = auth_gate
        self.auth_started = asyncio.Event()
        self.receiving = asyncio.Event()
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.active_sends = 0
        self.max_sends = 0

    async def send(self, raw):
        data = json.loads(raw)
        if data["type"] == "auth":
            self.auth_started.set()
            if self.auth_gate:
                await self.auth_gate.wait()
            if self.auth_error:
                raise self.auth_error
        elif self.send_error:
            raise self.send_error
        self.active_sends += 1
        self.max_sends = max(self.max_sends, self.active_sends)
        try:
            await asyncio.sleep(0)
            self.sent.append(data)
        finally:
            self.active_sends -= 1

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.receiving.set()
        item = await self.incoming.get()
        if item is None:
            raise StopAsyncIteration
        if isinstance(item, Exception):
            raise item
        return json.dumps(item)

    async def close(self):
        self.closed = True
        self.incoming.put_nowait(None)


@pytest.fixture
def client(monkeypatch):
    import agent.client as module

    monkeypatch.setattr(module, "config", SimpleNamespace(
        server_url="ws://audit.invalid", workstation_id="isolated-pc",
        agent_token="isolated-key", reconnect_initial_delay=0.001,
        reconnect_max_delay=0.002, reconnect_backoff_factor=2,
    ))
    return module.AgentWebSocketClient(AsyncMock())


def connections(monkeypatch, sockets):
    """No listener, DNS lookup or network connection is created."""
    import agent.client as module

    remaining = iter(sockets)

    class Connection:
        async def __aenter__(self):
            self.socket = next(remaining)
            return self.socket

        async def __aexit__(self, *args):
            await self.socket.close()

    monkeypatch.setattr(module.websockets, "connect", lambda *args, **kwargs: Connection())


async def cleanup(client, task):
    await client.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_send_failure_reconnects_even_when_receiver_is_still_open(client, monkeypatch):
    first = Socket(send_error=OSError("isolated send failure"))
    second = Socket()
    connections(monkeypatch, [first, second])
    run = asyncio.create_task(client.run())
    try:
        await asyncio.wait_for(first.receiving.wait(), 1)
        await client.send({"type": "command_result", "command_id": "first"})
        await asyncio.wait_for(second.receiving.wait(), 1)
        assert first.closed and client._connected
        await client.send({"type": "command_result", "command_id": "after-reconnect"})
        async with asyncio.timeout(1):
            while len(second.sent) < 2:
                await asyncio.sleep(0)
        assert second.sent[-1]["command_id"] == "after-reconnect"
    finally:
        await cleanup(client, run)


async def test_auth_write_failure_cleans_state_and_next_session_recovers(client, monkeypatch):
    failed = Socket(auth_error=OSError("isolated auth failure"))
    recovered = Socket()
    connections(monkeypatch, [failed, recovered])
    with pytest.raises(OSError, match="isolated auth failure"):
        await client._connect_once()
    assert failed.closed and not client._connected and client._ws is None
    session = asyncio.create_task(client._connect_once())
    try:
        await asyncio.wait_for(recovered.receiving.wait(), 1)
        assert client._connected
    finally:
        await cleanup(client, session)


async def test_cancellation_during_auth_cleans_state(client, monkeypatch):
    socket = Socket(auth_gate=asyncio.Event())
    connections(monkeypatch, [socket])
    session = asyncio.create_task(client._connect_once())
    await asyncio.wait_for(socket.auth_started.wait(), 1)
    await cleanup(client, session)
    assert socket.closed and not client._connected and client._ws is None


async def test_stop_interrupts_open_circuit_without_reconnecting(client, monkeypatch):
    client._circuit_open_until = asyncio.get_running_loop().time() + 300
    connect = AsyncMock()
    monkeypatch.setattr(client, "_connect_once", connect)
    run = asyncio.create_task(client.run())
    try:
        await asyncio.sleep(0)
        await client.stop()
        await asyncio.wait_for(asyncio.shield(run), 1)
        connect.assert_not_awaited()
    finally:
        await cleanup(client, run)


async def test_repeated_failed_connects_do_not_leave_stop_waiters(client, monkeypatch):
    attempts = 0
    waiters = []
    client._CIRCUIT_THRESHOLD = 100

    async def fail():
        nonlocal attempts
        attempts += 1
        if attempts == 21:
            for task in asyncio.all_tasks():
                frame = getattr(task.get_coro(), "cr_frame", None)
                if frame and frame.f_locals.get("self") is client._stop_event:
                    waiters.append(task)
            client._stop_event.set()
        raise OSError("isolated reconnect failure")

    monkeypatch.setattr(client, "_connect_once", fail)
    await asyncio.wait_for(client.run(), 2)
    assert attempts == 21
    assert waiters == [], "Each expired reconnect delay leaked a shielded Event.wait task"


async def test_clean_close_uses_delay_before_next_connection(client, monkeypatch):
    import agent.client as module

    monkeypatch.setattr(module.config, "reconnect_initial_delay", 30)
    first, second = Socket(), Socket()
    first.incoming.put_nowait(None)
    connections(monkeypatch, [first, second])
    run = asyncio.create_task(client.run())
    try:
        await asyncio.wait_for(first.receiving.wait(), 1)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(second.auth_started.wait(), 0.1)
        await client.stop()
        await asyncio.wait_for(asyncio.shield(run), 1)
    finally:
        await cleanup(client, run)


@pytest.mark.parametrize("abrupt", [False, True])
async def test_receive_end_cleans_transport_tasks(client, monkeypatch, abrupt):
    socket = Socket()
    connections(monkeypatch, [socket])
    before = asyncio.all_tasks()
    session = asyncio.create_task(client._connect_once())
    await asyncio.wait_for(socket.receiving.wait(), 1)
    socket.incoming.put_nowait(OSError("isolated receive failure") if abrupt else None)
    if abrupt:
        with pytest.raises(OSError, match="isolated receive failure"):
            await asyncio.wait_for(session, 1)
    else:
        await asyncio.wait_for(session, 1)
    assert socket.closed and not client._connected and client._ws is None
    assert asyncio.all_tasks() - before == set()


async def test_concurrent_producers_keep_auth_first_and_serialize_sends(client, monkeypatch):
    socket = Socket()
    connections(monkeypatch, [socket])
    session = asyncio.create_task(client._connect_once())
    try:
        await asyncio.wait_for(socket.receiving.wait(), 1)
        await asyncio.gather(*(client.send({"type": "command_result", "command_id": i}) for i in range(20)))
        async with asyncio.timeout(1):
            while len(socket.sent) < 21:
                await asyncio.sleep(0)
        assert socket.sent[0]["type"] == "auth"
        assert [item["command_id"] for item in socket.sent[1:]] == list(range(20))
        assert socket.max_sends == 1
    finally:
        await cleanup(client, session)
    assert not client._connected and client._ws is None
