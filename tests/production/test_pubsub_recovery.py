"""Restore subscriptions after a failed retry, then deliver through actual Redis."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from backend.api.ws.events.router import EventsManager, FrontendConnection
from backend.websocket.pubsub_router import PubSubRouter


@pytest.mark.parametrize("kind", ["commands", "browser_events"])
async def test_real_redis_delivery_resumes_for_existing_client(world, monkeypatch, kind):
    fault = asyncio.Event()
    attempts = []

    class Subscription:
        def __init__(self, index):
            self.index = index
            self.delegate = world.redis.pubsub()

        @property
        def subscribed(self):
            return self.delegate.subscribed

        async def subscribe(self, channel):
            if self.index == 1:
                raise ConnectionError("Isolated replacement subscription failure")
            await self.delegate.subscribe(channel)

        async def aclose(self):
            await self.delegate.aclose()

        async def listen(self):
            if self.index == 0:
                await fault.wait()
                raise ConnectionError("Isolated established connection failure")
            async for message in self.delegate.listen():
                yield message

    class RedisConnections:
        def pubsub(self):
            result = Subscription(len(attempts))
            attempts.append(result)
            return result

    original_sleep = asyncio.sleep

    async def accelerated_sleep(delay):
        await original_sleep(min(delay, 0.01))

    monkeypatch.setattr(asyncio, "sleep", accelerated_sleep)
    device_id, org_id = str(world.dev_a.id), str(world.org_a.id)
    socket = AsyncMock()
    if kind == "commands":
        manager = AsyncMock()
        listener = PubSubRouter(RedisConnections(), manager)
        await listener.start()
        await listener.subscribe_device(device_id, org_id)
        channel = f"sphere:agent:cmd:{device_id}"
        delivered = manager.send_to_device
    else:
        listener = EventsManager()
        await listener.start(RedisConnections())
        await listener.add_client(org_id, FrontendConnection(socket, org_id, set()))
        channel = f"sphere:org:events:{org_id}"
        delivered = socket.send_json

    async def confirm_subscription():
        while True:
            count = await world.redis.pubsub_numsub(channel)
            if len(attempts) >= 3 and count[0][1] == 1:
                return
            await original_sleep(0.005)

    async def confirm_delivery():
        while delivered.await_count == 0:
            await original_sleep(0.005)

    try:
        fault.set()
        await asyncio.wait_for(confirm_subscription(), 3)
        payload = {"event_type": "device.online", "org_id": org_id, "device_id": device_id}
        assert await world.redis.publish(channel, json.dumps(payload)) == 1
        await asyncio.wait_for(confirm_delivery(), 3)
        assert delivered.await_count == 1
        if kind == "commands":
            assert delivered.await_args.args == (device_id, payload)
        else:
            assert delivered.await_args.args[0]["org_id"] == org_id
            assert delivered.await_args.args[0]["device_id"] == device_id
    finally:
        await listener.stop()
