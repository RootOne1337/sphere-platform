"""Streaming REST controls must reach the owning worker through real Redis."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.pubsub_router import PubSubPublisher, PubSubRouter


@pytest.mark.parametrize("endpoint,expected", [
    ("start", {"type": "start_stream", "quality": "720p", "bitrate": 2_000_000}),
    ("stop", {"type": "stop_stream"}),
    ("keyframe", {"type": "request_keyframe"}),
])
async def test_stream_control_reaches_another_worker(world, endpoint, expected):
    device = str(world.dev_a.id)
    api_manager = ConnectionManager()
    owner_manager = ConnectionManager()
    seen = []
    received = asyncio.Event()

    async def deliver(command):
        seen.append(command)
        received.set()

    await owner_manager.connect(AsyncMock(send_json=deliver), device, "android", str(world.org_a.id))
    router = PubSubRouter(world.redis, owner_manager)
    await router.start()
    await router.subscribe_device(device, str(world.org_a.id))
    # Wait for the actual Redis subscription acknowledgement, not an arbitrary sleep.
    async with asyncio.timeout(3):
        while not dict(await world.redis.pubsub_numsub(f"sphere:agent:cmd:{device}"))[f"sphere:agent:cmd:{device}"]:
            await asyncio.sleep(0.01)
    try:
        with patch("backend.api.v1.streaming.router.get_connection_manager", return_value=api_manager, create=True), \
             patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=PubSubPublisher(world.redis)):
            response = await world.client.post(f"/api/v1/streaming/{device}/{endpoint}",
                headers=world.auth(world.users["org_admin"]))
        assert response.status_code == 200, response.text
        await asyncio.wait_for(received.wait(), 3)
        assert seen == [expected]
        assert response.json()["device_id"] == device
    finally:
        await router.stop()


@pytest.mark.parametrize("endpoint", ["start", "stop", "keyframe"])
async def test_unavailable_device_is_503_without_offline_queue(world, endpoint):
    publisher = PubSubPublisher(world.redis)
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher), \
         patch.object(publisher, "_send_command_inner", AsyncMock()) as queued:
        response = await world.client.post(f"/api/v1/streaming/{world.dev_a.id}/{endpoint}",
            headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 503
    queued.assert_not_awaited()


@pytest.mark.parametrize("endpoint", ["start", "stop", "keyframe"])
@pytest.mark.parametrize("outage", ["missing", "redis"])
async def test_transport_outage_is_reported_without_claiming_offline(world, endpoint, outage):
    publisher = None if outage == "missing" else AsyncMock()
    if publisher is not None:
        publisher.send_command_live.side_effect = RedisConnectionError("isolated transport reset")
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        response = await world.client.post(f"/api/v1/streaming/{world.dev_a.id}/{endpoint}",
            headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 503
    assert "transport" in response.json()["detail"].lower()


@pytest.mark.parametrize("endpoint", ["start", "stop", "keyframe"])
@pytest.mark.parametrize("case,status", [("foreign", 404), ("viewer", 403)])
async def test_authorize_before_cross_worker_publication(world, endpoint, case, status):
    publisher = AsyncMock()
    device = world.dev_b if case == "foreign" else world.dev_a
    user = world.users["org_admin"] if case == "foreign" else world.users["viewer"]
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        response = await world.client.post(f"/api/v1/streaming/{device.id}/{endpoint}", headers=world.auth(user))
    assert response.status_code == status
    publisher.send_command_live.assert_not_awaited()
