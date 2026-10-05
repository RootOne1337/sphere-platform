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


async def test_first_pong_promotes_connecting_presence_to_online(world, presence_cache):
    device_id = str(world.dev_a.id)
    await presence_cache.set_status(device_id, DeviceLiveStatus(
        device_id=device_id, status="connecting", ws_session_id="session-1",
    ))
    heartbeat = HeartbeatManager(
        AsyncMock(), device_id, presence_cache, session_id="session-1",
    )

    await heartbeat.handle_pong({"type": "pong", "ts": time.time()})

    online = await presence_cache.get_status(device_id)
    assert online is not None
    assert online.status == "online"
    assert online.last_heartbeat is not None


async def test_redis_outage_does_not_kill_heartbeat_and_next_pong_recovers(world, presence_cache):
    device_id = str(world.dev_a.id)
    heartbeat = HeartbeatManager(AsyncMock(), device_id, presence_cache)
    previous = heartbeat._last_agent_response
    with patch.object(presence_cache.redis, "pipeline", side_effect=ConnectionError("isolated Redis outage")):
        assert await heartbeat.handle_pong({"type": "pong", "ts": time.time()}) is False
    assert heartbeat._last_agent_response >= previous
    await heartbeat.handle_pong({"type": "pong", "ts": time.time()})
    assert (await presence_cache.get_status(device_id)).status == "online"


@pytest.mark.parametrize("kind", ["pong", "telemetry"])
async def test_old_observation_cannot_overwrite_replacement_in_real_redis(world, presence_cache, kind):
    from backend.api.ws.android.router import handle_telemetry

    device_id = str(world.dev_a.id)
    await presence_cache.set_status(device_id, DeviceLiveStatus(
        device_id=device_id, status="online", ws_session_id="old", battery=75,
    ))
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=False)
    replacement = DeviceStatusCache(redis)
    original_pipeline = presence_cache.redis.pipeline
    replaced = False

    class ReplaceBeforeExecute:
        def __init__(self, pipe):
            self.pipe = pipe

        async def __aenter__(self):
            await self.pipe.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.pipe.__aexit__(*args)

        def __getattr__(self, name):
            attribute = getattr(self.pipe, name)
            if name != "execute":
                return attribute

            async def execute():
                nonlocal replaced
                if not replaced:
                    replaced = True
                    await replacement.set_status(device_id, DeviceLiveStatus(
                        device_id=device_id, status="connecting", ws_session_id="replacement",
                    ))
                return await attribute()

            return execute

    try:
        with patch.object(presence_cache.redis, "pipeline", side_effect=lambda **kwargs: ReplaceBeforeExecute(original_pipeline(**kwargs))):
            if kind == "pong":
                heartbeat = HeartbeatManager(AsyncMock(), device_id, presence_cache, session_id="old")
                assert await heartbeat.handle_pong({"vpn_active": True, "battery": 1}) is False
            else:
                await handle_telemetry(device_id, {"vpn_active": True, "battery": 1}, presence_cache, session_id="old")
        current = await presence_cache.get_status(device_id)
        assert replaced and current.ws_session_id == "replacement"
        assert current.status == "connecting" and current.battery is None
        assert current.vpn_active is None
    finally:
        await redis.aclose()


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
