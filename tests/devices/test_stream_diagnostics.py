"""Authenticated diagnostics endpoint: freshness and tenant isolation."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fakeredis.aioredis import FakeRedis

from backend.api.v1.devices.router import get_status_cache
from backend.main import app
from backend.schemas.device_status import DeviceLiveStatus
from backend.schemas.stream_diagnostics import AgentStreamTelemetry, StoredStreamDiagnostics
from backend.services.device_status_cache import DeviceStatusCache


def _telemetry() -> AgentStreamTelemetry:
    return AgentStreamTelemetry.model_validate({
        "schema_version": 2,
        "active": True,
        "stage": "capture_encoder_ws_queue",
        "capture_fps": 15,
        "render_fps": 15,
        "capture_frames_total": 150,
        "rendered_frames_total": 149,
        "capture_read_failures_total": 0,
        "render_failures_total": 1,
        "encoder_errors_total": 0,
        "frame_throttle_drops_total": 5,
        "encoder_fps": 15,
        "encoded_frames_total": 149,
        "encoded_bytes_total": 123_456,
        "key_frame_ratio": 0.05,
        "ws_queue_attempts_total": 151,
        "ws_queue_accepted_total": 150,
        "ws_queue_rejected_total": 1,
        "ws_queue_accepted_bytes_total": 122_000,
    })


async def _diagnostics_cache(redis: FakeRedis) -> DeviceStatusCache:
    cache = DeviceStatusCache(redis)
    async def override():
        return cache
    app.dependency_overrides[get_status_cache] = override
    return cache


async def test_stream_diagnostics_returns_fresh_stage_counters_and_session(
    device_client, mock_redis
):
    created = await device_client.post("/api/v1/devices", json={"name": "Stream telemetry"})
    device_id = created.json()["id"]
    redis = FakeRedis(decode_responses=False)
    cache = await _diagnostics_cache(redis)
    now = datetime.now(timezone.utc)
    try:
        await cache.set_status(device_id, DeviceLiveStatus(
            device_id=device_id,
            status="online",
            ws_session_id="session-123",
            last_heartbeat=now,
        ))
        await cache.set_stream_diagnostics(device_id, StoredStreamDiagnostics(
            telemetry=_telemetry(),
            observed_at=now,
            agent_session_id="session-123",
        ))

        response = await device_client.get(f"/api/v1/devices/{device_id}/stream-diagnostics")
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "active_report"
        assert body["diagnostics"]["agent_session_id"] == "session-123"
        assert body["diagnostics"]["telemetry"]["capture_frames_total"] == 150
        assert body["diagnostics"]["telemetry"]["ws_queue_accepted_total"] == 150
    finally:
        app.dependency_overrides.pop(get_status_cache, None)
        await redis.aclose()


async def test_stream_diagnostics_distinguishes_idle_and_stale_device(
    device_client,
):
    created = await device_client.post("/api/v1/devices", json={"name": "Idle stream telemetry"})
    device_id = created.json()["id"]
    redis = FakeRedis(decode_responses=False)
    cache = await _diagnostics_cache(redis)
    try:
        now = datetime.now(timezone.utc)
        await cache.set_status(device_id, DeviceLiveStatus(
            device_id=device_id,
            status="online",
            last_heartbeat=now,
        ))
        response = await device_client.get(f"/api/v1/devices/{device_id}/stream-diagnostics")
        assert response.json()["state"] == "not_streaming"

        await cache.set_stream_diagnostics(device_id, StoredStreamDiagnostics(
            telemetry=_telemetry(),
            observed_at=now - timedelta(seconds=100),
        ))
        response = await device_client.get(f"/api/v1/devices/{device_id}/stream-diagnostics")
        assert response.json()["state"] == "stale"
        assert response.json()["diagnostics"] is not None
        assert response.json()["age_seconds"] >= 99
    finally:
        app.dependency_overrides.pop(get_status_cache, None)
        await redis.aclose()


async def test_stream_diagnostics_hides_cross_tenant_device(
    device_client, db_session, other_org,
):
    from backend.models.device import Device

    foreign = Device(
        org_id=other_org.id,
        name="Foreign diagnostics",
        serial=f"diag-{uuid.uuid4().hex[:8]}",
        meta={"type": "physical"},
    )
    db_session.add(foreign)
    await db_session.flush()
    response = await device_client.get(
        f"/api/v1/devices/{foreign.id}/stream-diagnostics"
    )
    assert response.status_code == 404
