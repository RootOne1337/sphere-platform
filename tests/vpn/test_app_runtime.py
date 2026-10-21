from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from backend.api.ws.android.router import handle_agent_message
from backend.schemas.device_status import DeviceLiveStatus
from backend.schemas.vpn.runtime import AppVpnObservation, AppVpnSnapshot, parse_app_vpn_report
from backend.services.device_status_cache import DeviceStatusCache

NOW = datetime.now(timezone.utc)
SESSION = "a27c2ce8-90fe-453e-b465-65f5efe5cd34"


def report(**changes):
    return {"type": "app_vpn_status", "schema_version": 1, "snapshot": {
        "phase": "AWAITING_HANDSHAKE", "sessionId": SESSION,
        "sampledAtEpochMs": int(NOW.timestamp() * 1000), "providerPid": 23901, **changes,
    }}


@pytest.mark.parametrize("field,value", [
    ("config_text", "private-sentinel"), ("rxBytes", -1), ("txBytes", True),
    ("sampledAtEpochMs", "123"), ("providerPid", 0), ("phase", "CONNECTED"),
    ("reason", "[Interface] PrivateKey=private-sentinel"), ("sessionId", "other"),
])
def test_rejects_secrets_and_unbounded_or_coerced_reports(field, value):
    assert parse_app_vpn_report(report(**{field: value})) is None


def test_not_observed_counters_remain_unknown_and_handshake_is_not_invented():
    sample = parse_app_vpn_report(report())
    assert sample.rxBytes is None and sample.handshakeEpochSeconds is None
    assert parse_app_vpn_report(report(rxBytes=0)).rxBytes == 0
    assert parse_app_vpn_report(report() | {"schema_version": True}) is None
    assert parse_app_vpn_report(report() | {"device_id": "forged"}) is None


@pytest.mark.parametrize("sample_age,receipt_age,session,online,expected", [
    (0, 0, "current", True, "fresh"), (16, 0, "current", True, "stale"),
    (0, 16, "current", True, "stale"), (-10, 0, "current", True, "stale"),
    (0, 0, "replaced", True, "unknown"), (0, 0, "current", False, "unknown"),
])
def test_heartbeat_and_status_read_cannot_refresh_native_evidence(sample_age, receipt_age, session, online, expected):
    observation = AppVpnObservation(
        snapshot=AppVpnSnapshot.model_validate(report(sampledAtEpochMs=int((NOW.timestamp() - sample_age) * 1000))["snapshot"]),
        received_at=NOW - timedelta(seconds=receipt_age), ws_session_id="current",
    )
    assert observation.freshness(session, online, NOW) == expected


async def test_old_socket_and_regular_telemetry_cannot_overwrite_current_native_state():
    redis = FakeRedis(decode_responses=False)
    try:
        cache = DeviceStatusCache(redis)
        await cache.set_status("device", DeviceLiveStatus(device_id="device", status="online", ws_session_id="current", last_heartbeat=NOW))
        await handle_agent_message("device", "org", report(), AsyncMock(), cache, session_id="old")
        assert (await cache.get_status("device")).app_vpn is None
        await handle_agent_message("device", "org", report(), AsyncMock(), cache, session_id="current")
        first = (await cache.get_status("device")).app_vpn
        assert first.snapshot.sessionId == SESSION
        await handle_agent_message("device", "org", {"type": "telemetry", "app_vpn": {"phase": "CONNECTED"}, "cpu": 3}, AsyncMock(), cache, session_id="current")
        await cache.merge_agent_status("device", {"battery": 90}, session_id="current", heartbeat_at=NOW + timedelta(seconds=20))
        after = (await cache.get_status("device")).app_vpn
        assert after == first
        assert after.freshness("current", True, NOW + timedelta(seconds=20)) == "stale"
    finally:
        await redis.aclose()


async def test_cache_failure_does_not_disconnect_management():
    cache = AsyncMock()
    cache.merge_agent_status.side_effect = ConnectionError("private-sentinel")
    await handle_agent_message("device", "org", report(), AsyncMock(), cache, session_id="current")
    cache.merge_agent_status.assert_awaited_once()
