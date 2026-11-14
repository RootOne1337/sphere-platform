"""VPN observations must not borrow heartbeat freshness or replacement ownership."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import msgpack
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

import backend.schemas.device_status as status_module
import backend.services.device_status_cache as cache_module
import backend.websocket.heartbeat as heartbeat_module
from backend.api.ws.android.router import handle_telemetry
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.heartbeat import HeartbeatManager

NOW = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


@pytest_asyncio.fixture
async def cache(monkeypatch):
    monkeypatch.setattr(status_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(cache_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(heartbeat_module, "datetime", FrozenDatetime)
    redis = FakeRedis(decode_responses=False)
    yield DeviceStatusCache(redis)
    await redis.aclose()


async def seed(cache, **overrides):
    payload = DeviceLiveStatus(
        device_id="vpn-device", status="online", ws_session_id="current",
        last_heartbeat=NOW, battery=70, vpn_active=True,
    ).model_dump(mode="json") | {
        "vpn_observed_at": NOW.isoformat(),
        "vpn_observed_session_id": "current",
    } | overrides
    await cache.redis.set("device:status:vpn-device", msgpack.packb(payload, use_bin_type=True), ex=120)


@pytest.mark.parametrize("age,expected,state", [
    (0, True, "fresh"), (119, True, "fresh"),
    (120, None, "stale"), (600, None, "stale"), (-1, None, "unknown"),
])
async def test_single_and_bulk_reads_use_independent_vpn_age(cache, age, expected, state):
    observed = (NOW - timedelta(seconds=age)).isoformat()
    await seed(cache, vpn_observed_at=observed)
    one = await cache.get_status("vpn-device")
    bulk = (await cache.bulk_get_status(["vpn-device"]))["vpn-device"]
    for result in [one, bulk]:
        assert result.vpn_active is expected
        assert getattr(result, "vpn_observation_state", None) == state
        assert getattr(result, "vpn_observed_at", None).isoformat() == observed
    stored = msgpack.unpackb(await cache.redis.get("device:status:vpn-device"), raw=False)
    assert stored["vpn_active"] is True, "A read must not replace historical cache evidence."


@pytest.mark.parametrize("overrides", [
    {"vpn_observed_at": None},
    {"vpn_observed_session_id": None},
    {"vpn_observed_session_id": "replaced"},
    {"ws_session_id": None},
    {"status": "offline"},
    {"status": "connecting"},
    {"last_heartbeat": None},
    {"last_heartbeat": (NOW - timedelta(seconds=120)).isoformat()},
    {"last_heartbeat": (NOW + timedelta(seconds=1)).isoformat()},
    {"vpn_observed_at": NOW.replace(tzinfo=None).isoformat()},
])
async def test_legacy_unowned_or_disconnected_flag_is_unknown(cache, overrides):
    await seed(cache, **overrides)
    result = await cache.get_status("vpn-device")
    assert result.vpn_active is None
    assert getattr(result, "vpn_observation_state", None) == "unknown"


async def test_a_fresh_false_report_is_not_unknown(cache):
    await seed(cache, vpn_active=False)
    result = await cache.get_status("vpn-device")
    assert result.vpn_active is False
    assert getattr(result, "vpn_observation_state", None) == "fresh"


async def test_heartbeat_without_vpn_does_not_renew_its_observation(cache):
    old = NOW - timedelta(seconds=121)
    await seed(cache, vpn_observed_at=old.isoformat())
    heartbeat = HeartbeatManager(AsyncMock(), "vpn-device", cache, session_id="current")
    await heartbeat.handle_pong({"type": "pong", "battery": 81})
    result = await cache.get_status("vpn-device")
    assert result.status == "online" and result.last_heartbeat == NOW
    assert result.battery == 81 and result.vpn_active is None
    assert getattr(result, "vpn_observed_at", None) == old
    assert getattr(result, "vpn_observation_state", None) == "stale"


@pytest.mark.parametrize("flag", [True, False])
async def test_current_pong_records_vpn_time_and_owner(cache, flag):
    await seed(cache, vpn_observed_at=None, vpn_observed_session_id=None)
    heartbeat = HeartbeatManager(AsyncMock(), "vpn-device", cache, session_id="current")
    await heartbeat.handle_pong({"type": "pong", "vpn_active": flag, "vpn_observed_at": "2099-01-01"})
    result = await cache.get_status("vpn-device")
    assert result.vpn_active is flag
    assert getattr(result, "vpn_observed_at", None) == NOW
    assert getattr(result, "vpn_observed_session_id", None) == "current"


@pytest.mark.parametrize("flag", ["true", 1, [], {}])
async def test_malformed_vpn_report_does_not_mint_freshness(cache, flag):
    old = NOW - timedelta(seconds=121)
    await seed(cache, vpn_observed_at=old.isoformat())
    heartbeat = HeartbeatManager(AsyncMock(), "vpn-device", cache, session_id="current")
    await heartbeat.handle_pong({"type": "pong", "vpn_active": flag})
    result = await cache.get_status("vpn-device")
    assert result.vpn_active is None
    assert getattr(result, "vpn_observed_at", None) == old


async def test_replaced_telemetry_does_not_overwrite_current_session(cache):
    await seed(cache)
    await handle_telemetry("vpn-device", {"vpn_active": False, "battery": 1}, cache, session_id="replaced")
    result = await cache.get_status("vpn-device")
    assert result.battery == 70 and result.vpn_active is True
    assert result.ws_session_id == "current"


async def test_unscoped_telemetry_cannot_overwrite_an_owned_session(cache):
    await seed(cache)
    await handle_telemetry("vpn-device", {"vpn_active": False, "battery": 1}, cache)
    result = await cache.get_status("vpn-device")
    assert result.battery == 70 and result.vpn_active is True


async def test_telemetry_records_its_own_time_without_changing_heartbeat(cache):
    heartbeat_at = NOW - timedelta(seconds=30)
    await seed(cache, last_heartbeat=heartbeat_at.isoformat(), vpn_observed_at=None)
    await handle_telemetry("vpn-device", {"vpn_active": False}, cache, session_id="current")
    result = await cache.get_status("vpn-device")
    assert result.last_heartbeat == heartbeat_at
    assert result.vpn_active is False and result.vpn_observed_at == NOW
    assert result.vpn_observation_state == "fresh"


async def test_explicit_unknown_report_clears_the_previous_observation(cache):
    await seed(cache)
    await handle_telemetry("vpn-device", {"vpn_active": None}, cache, session_id="current")
    result = await cache.get_status("vpn-device")
    assert result.vpn_active is None and result.vpn_observed_at is None
    assert result.vpn_observation_state == "unknown"


@pytest.mark.parametrize("payload", [b"not-msgpack", msgpack.packb({"device_id": "vpn-device", "vpn_observed_at": "not-a-date"})])
async def test_malformed_cache_is_unavailable_in_single_and_bulk_reads(cache, payload):
    await cache.redis.set("device:status:vpn-device", payload)
    assert await cache.get_status("vpn-device") is None
    assert (await cache.bulk_get_status(["vpn-device"]))["vpn-device"] is None


async def test_watch_conflicts_are_bounded_and_do_not_publish_a_confirmation(cache, monkeypatch):
    from redis.exceptions import WatchError

    await seed(cache)
    factory = cache.redis.pipeline
    attempts = 0

    def contested_pipeline(*args, **kwargs):
        pipe = factory(*args, **kwargs)

        async def conflict():
            nonlocal attempts
            attempts += 1
            raise WatchError("isolated observation conflict")

        pipe.execute = conflict
        return pipe

    monkeypatch.setattr(cache.redis, "pipeline", contested_pipeline)
    heartbeat = HeartbeatManager(AsyncMock(), "vpn-device", cache, session_id="current")
    assert await heartbeat.handle_pong({"vpn_active": False, "battery": 1}) is False
    assert attempts == 3
    result = await cache.get_status("vpn-device")
    assert result.battery == 70 and result.vpn_active is True


async def test_heartbeat_write_fences_replacement_between_read_and_commit(cache, monkeypatch):
    await seed(cache)
    replacement = DeviceLiveStatus(device_id="vpn-device", status="connecting", ws_session_id="new-owner")
    injected = False
    original_get = cache.redis.get

    async def inject_after_read(getter, *args, **kwargs):
        nonlocal injected
        raw = await getter(*args, **kwargs)
        if not injected:
            injected = True
            await cache.set_status("vpn-device", replacement)
        return raw

    async def racing_get(*args, **kwargs):
        return await inject_after_read(original_get, *args, **kwargs)

    original_pipeline = cache.redis.pipeline

    def racing_pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        getter = pipe.get

        async def pipe_get(*args, **kwargs):
            return await inject_after_read(getter, *args, **kwargs)

        pipe.get = pipe_get
        return pipe

    monkeypatch.setattr(cache.redis, "get", racing_get)
    monkeypatch.setattr(cache.redis, "pipeline", racing_pipeline)
    heartbeat = HeartbeatManager(AsyncMock(), "vpn-device", cache, session_id="current")
    assert await heartbeat.handle_pong({"type": "pong", "vpn_active": True}) is False
    result = await cache.get_status("vpn-device")
    assert injected and result.ws_session_id == "new-owner"
    assert result.status == "connecting" and result.vpn_active is None
