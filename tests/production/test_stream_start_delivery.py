"""Idle command subscriptions and an unavailable initial capture command."""

import asyncio
import importlib
import json
import os
import uuid
from unittest.mock import AsyncMock, patch

from redis.asyncio import Redis

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.pubsub_router import PubSubPublisher, PubSubRouter
from backend.websocket.stream_bridge import VideoStreamBridge
from tests.production.test_stream_video_routing import Viewer


async def test_idle_command_subscription_keeps_redis_connection_and_delivers_start(world):
    name = "isolated-idle-command-" + uuid.uuid4().hex
    redis = Redis.from_url(
        os.environ["REDIS_URL"], decode_responses=True, client_name=name,
        socket_timeout=5.0, socket_connect_timeout=5.0,
        retry_on_timeout=True, health_check_interval=30,
    )
    manager = AsyncMock()
    router = PubSubRouter(redis, manager)
    device, org = str(world.dev_a.id), str(world.org_a.id)
    await router.start()
    await router.subscribe_device(device, org)

    async def connections():
        return {row['id'] for row in await world.redis.client_list()
                if row['name'] == name and int(row['sub']) == 2}

    try:
        async with asyncio.timeout(3):
            while not (initial := await connections()):
                await asyncio.sleep(0.01)
        await asyncio.sleep(6.3)  # Longer than the production request socket timeout.
        assert await connections() == initial, "Idle listener dropped/replaced its subscriptions"
        command = {"type": "start_stream", "quality": "720p", "bitrate": 2_000_000}
        assert await world.redis.publish(f"sphere:agent:cmd:{device}", json.dumps(command)) == 1
        async with asyncio.timeout(2):
            while manager.send_to_device.await_count == 0:
                await asyncio.sleep(0.01)
        manager.send_to_device.assert_awaited_once_with(device, command)
    finally:
        await router.stop()
        await redis.aclose()


async def test_missing_initial_command_subscription_closes_viewer_for_recovery(world):
    module = importlib.import_module("backend.api.ws.stream.router")
    token = world.auth(world.users["org_admin"])["Authorization"].split()[1]
    viewer = Viewer(token)
    bridge = VideoStreamBridge(ConnectionManager(), publisher=PubSubPublisher(world.redis))
    device = str(world.dev_a.id)
    # No owner subscription: PUBLISH really returns zero, not a mock exception.
    with patch.object(module, "AsyncSessionLocal", world.sessions), \
         patch.object(module, "get_stream_bridge", return_value=bridge):
        task = asyncio.create_task(module.stream_viewer_ws(viewer, device))
        try:
            async with asyncio.timeout(2):
                while viewer.closed is None:
                    await asyncio.sleep(0.01)
            assert viewer.closed == (1013, "stream_transport_unavailable")
            await asyncio.wait_for(task, 2)
            assert not bridge.is_streaming(device)
            assert device not in bridge._viewers
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.close()
