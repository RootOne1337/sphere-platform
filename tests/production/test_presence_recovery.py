"""Live APK heartbeats must recover disposable Redis presence without reconnect."""

import os
import time
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.heartbeat import HeartbeatManager


@pytest_asyncio.fixture
async def presence_cache(world):
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=False)
    try:
        yield DeviceStatusCache(redis)
    finally:
        await redis.aclose()


async def test_next_pong_recreates_evicted_presence_without_reconnecting(world, presence_cache):
    device_id = str(world.dev_a.id)
    cache = presence_cache
    await cache.set_status(device_id, DeviceLiveStatus(device_id=device_id, status="online"))
    await cache.redis.delete(cache._key(device_id))  # This fixture's key only; no database flush.
    heartbeat = HeartbeatManager(AsyncMock(), device_id, cache)
    await heartbeat.handle_pong({"type": "pong", "ts": time.time(), "battery": 81})
    recovered = await cache.get_status(device_id)
    assert recovered is not None
    assert recovered.status == "online"
    assert recovered.battery == 81
    assert recovered.last_heartbeat is not None
    assert 0 < await cache.redis.ttl(cache._key(device_id)) <= cache.TTL_ONLINE


async def test_redis_outage_does_not_kill_heartbeat_and_next_pong_recovers(world, presence_cache):
    device_id = str(world.dev_a.id)
    heartbeat = HeartbeatManager(AsyncMock(), device_id, presence_cache)
    previous = heartbeat._last_pong
    with patch.object(presence_cache.redis, "get", AsyncMock(side_effect=ConnectionError("isolated Redis outage"))):
        await heartbeat.handle_pong({"type": "pong", "ts": time.time()})
    assert heartbeat._last_pong >= previous
    await heartbeat.handle_pong({"type": "pong", "ts": time.time()})
    assert (await presence_cache.get_status(device_id)).status == "online"


@pytest.mark.parametrize("timestamp", [None, "malformed", {}, 10**400])
async def test_bad_latency_timestamp_cannot_prevent_valid_liveness_update(world, presence_cache, timestamp):
    device_id = str(world.dev_a.id)
    heartbeat = HeartbeatManager(AsyncMock(), device_id, presence_cache)
    await heartbeat.handle_pong({"type": "pong", "ts": timestamp, "battery": 80})
    assert (await presence_cache.get_status(device_id)).battery == 80


async def test_replacement_session_is_preserved_and_invalid_telemetry_is_not_cached(world, presence_cache):
    device_id = str(world.dev_a.id)
    await presence_cache.set_status(device_id, DeviceLiveStatus(
        device_id=device_id, status="busy", ws_session_id="new-session", battery=75,
    ))
    old = HeartbeatManager(AsyncMock(), device_id, presence_cache, session_id="old-session")
    await old.handle_pong({"battery": 50})
    assert (await presence_cache.get_status(device_id)).battery == 75
    current = HeartbeatManager(AsyncMock(), device_id, presence_cache, session_id="new-session")
    await current.handle_pong({"battery": 500})
    cached = await presence_cache.get_status(device_id)
    assert cached.battery == 75
    assert cached.status == "busy"
    assert cached.ws_session_id == "new-session"
    await presence_cache.redis.delete(presence_cache._key(device_id))
    await current.handle_pong({"battery": 65})
    assert (await presence_cache.get_status(device_id)).ws_session_id == "new-session"
