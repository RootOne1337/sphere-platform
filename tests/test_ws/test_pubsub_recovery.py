"""Listeners must retry a failed restoration, including a partially restored set."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.ws.events.router import EventsManager, FrontendConnection
from backend.websocket.pubsub_router import PubSubRouter


class FaultySubscription:
    def __init__(self, *, initial=False, fail_after=None, close_failure=False):
        self.initial = initial
        self.fail_after = fail_after
        self.close_failure = close_failure
        self.channels = set()
        self.closed = False

    @property
    def subscribed(self):
        return bool(self.channels)

    async def subscribe(self, channel):
        if not self.initial and self.fail_after is not None and len(self.channels) >= self.fail_after:
            raise ConnectionError("Redis still unavailable during resubscribe")
        self.channels.add(channel)

    async def aclose(self):
        if self.close_failure:
            self.close_failure = False
            raise ConnectionError("Connection close interrupted")
        self.closed = True

    async def listen(self):
        if self.initial:
            raise ConnectionError("Existing Redis connection lost")
        if self.fail_after is None:
            for channel in sorted(self.channels):
                yield {"type": "message", "channel": channel, "data": json.dumps({
                    "event_type": "device.online", "org_id": channel.removeprefix("sphere:org:events:"),
                    "device_id": "dev-1",
                })}
        # A partially restored subscription remains live but never receives the
        # missing channels. The listener must finish recovery before listening.
        await asyncio.Future()


@pytest.mark.parametrize("kind", ["commands", "browser_events"])
@pytest.mark.parametrize("failure", ["first_channel", "partial_channels", "close", "repeated_outage"])
async def test_existing_clients_receive_again_after_resubscribe_failure(monkeypatch, kind, failure):
    initial = FaultySubscription(initial=True, close_failure=failure == "close")
    failed = [] if failure == "close" else [FaultySubscription(
        fail_after=1 if failure == "partial_channels" else 0,
    ) for _ in range(8 if failure == "repeated_outage" else 1)]
    restored = FaultySubscription()
    available = iter([initial, *failed, restored])
    redis = SimpleNamespace(pubsub=lambda: next(available))
    delays = []
    original_sleep = asyncio.sleep

    async def accelerated_sleep(delay):
        delays.append(delay)
        await original_sleep(0.001)

    monkeypatch.setattr(asyncio, "sleep", accelerated_sleep)
    connection_manager = AsyncMock()
    sockets = [AsyncMock(), AsyncMock()]
    if kind == "commands":
        listener = PubSubRouter(redis, connection_manager)
        await listener.start()
        await listener.subscribe_device("dev-1", "org-1")
        expected_channels = {"sphere:agent:cmd:dev-1", "sphere:org:events:org-1"}
    else:
        listener = EventsManager()
        await listener.start(redis)
        for index, socket in enumerate(sockets):
            org = "org-" + str(index + 1)
            await listener.add_client(org, FrontendConnection(socket, org, set()))
        expected_channels = {"sphere:org:events:org-1", "sphere:org:events:org-2"}

    async def wait_for_delivery():
        while True:
            if kind == "commands":
                delivered = (connection_manager.send_to_device.await_count == 1
                    and connection_manager.broadcast_to_org.await_count == 1)
            else:
                delivered = all(socket.send_json.await_count == 1 for socket in sockets)
            if delivered:
                return
            await original_sleep(0.001)

    try:
        await asyncio.wait_for(wait_for_delivery(), timeout=0.4)
        assert restored.channels == expected_channels
        assert initial.closed and all(sub.closed for sub in failed)
        assert delays[0] == 1.0 and max(delays) <= 30.0
        if failure == "repeated_outage":
            assert delays[:7] == [1, 2, 4, 8, 16, 30, 30]
        if kind == "commands":
            assert connection_manager.send_to_device.await_args.args[0] == "dev-1"
            assert connection_manager.broadcast_to_org.await_args.args[0] == "org-1"
        else:
            for index, socket in enumerate(sockets):
                assert socket.send_json.await_args.args[0]["org_id"] == "org-" + str(index + 1)
    finally:
        await listener.stop()
