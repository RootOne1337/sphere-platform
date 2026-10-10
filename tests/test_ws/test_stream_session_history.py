from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
from fastapi import HTTPException, Response
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.api.v1.direct_probe.router import stream_session_history
from backend.schemas.stream_diagnostics import AgentStreamTelemetry
from backend.websocket.stream_session_history import (
    RETENTION_SECONDS,
    SESSION_BYTES,
    StreamSessionHistory,
)

ORG, DEVICE = str(uuid4()), str(uuid4())
SAMPLE = dict(schema_version=1, transport="server_websocket", visibility="visible", received_packets=100,
              received_bytes=1024, rendered_frames=90, decoded_frames=90, invalid_packets=0,
              decode_errors=0, render_errors=0, queue_recoveries=0, stale_output_drops=0,
              decoder_queue=0, pending_outputs=0, incoming_fps=30, rendered_fps=30,
              packet_age_ms=10, frame_age_ms=20, control_state="ready", control_failure="none",
              control_rtt_ms=15, recovery_attempts=0)
PROBE = dict(schema_version=1, mode="readonly_video", trigger="automatic", profile="host", state="finished",
             path="host", protocol="udp", reason=None, echoes=20, echo_rtt_p95_ms=15, presented_frames=80,
             width=960, height=540, ice_state="connected", dtls_state="connected")


@pytest_asyncio.fixture
async def store():
    server = FakeServer()
    text = FakeRedis(server=server, decode_responses=True)
    binary = FakeRedis(server=server, decode_responses=False)
    try:
        yield StreamSessionHistory(text, binary)
    finally:
        await text.aclose()
        await binary.aclose()


async def test_ten_sessions_are_evicted_atomically_and_late_writers_cannot_resurrect(store):
    for i in range(11):
        assert await store.begin(ORG, DEVICE, f"session-{i}")
    rows = await store.read(ORG, DEVICE)
    assert [r["session_id"] for r in rows] == [f"session-{i}" for i in range(10, 0, -1)]
    assert not await store.browser(ORG, DEVICE, "session-0", SAMPLE)
    assert not await store.end(ORG, DEVICE, "session-0")
    order, records = store.keys(ORG, DEVICE)
    assert await store.redis.hlen(records) == await store.redis.llen(order) == 10
    assert 0 < await store.redis.ttl(records) <= RETENTION_SECONDS


async def test_concurrent_viewers_and_samples_stay_bounded_and_keep_aggregates(store):
    await asyncio.gather(*(store.begin(ORG, DEVICE, str(i)) for i in range(20)))
    assert len(await store.read(ORG, DEVICE)) == 10
    current = (await store.read(ORG, DEVICE))[0]["session_id"]
    for i in range(50):
        assert await store.browser(ORG, DEVICE, current, SAMPLE | {"received_packets": i, "control_rtt_ms": 50-i})
        assert await store.observe_agent(ORG, DEVICE, current)
    row = (await store.read(ORG, DEVICE))[0]
    assert len(row["browser_samples"]) == len(row["agent_samples"]) == 15
    assert row["browser_summary"]["reports"] == 50
    assert row["browser_summary"]["max_control_rtt_ms"] == 50
    assert row["browser_samples"][-1]["received_packets"] == 49
    assert len(json.dumps(row).encode()) < SESSION_BYTES


@pytest.mark.parametrize("change", [
    {"received_bytes": -1}, {"control_rtt_ms": float("nan")}, {"received_packets": True},
    {"control_state": "secret-text"}, {"pixels": "private screenshot"},
    {"transport": "unknown_transport"}, {"incoming_fps": float("inf")}, {"control_rtt_ms": "20"},
    {"direct_network_rtt_ms": float("nan")}, {"direct_path": "192.168.0.9"}, {"direct_frames": True},
    {"direct_failure": "private SDP"}, {"direct_state": "private state"},
    {"direct_ice_state": "private address"}, {"direct_dtls_state": "private key"},
    {"direct_protocol": "private endpoint"}, {"control_failure_detail": "private native exception"},
])
async def test_invalid_and_private_browser_fields_are_never_retained(store, change):
    assert await store.begin(ORG, DEVICE, "viewer")
    assert not await store.browser(ORG, DEVICE, "viewer", SAMPLE | change)
    assert "browser_samples" not in (await store.read(ORG, DEVICE))[0]


async def test_native_failure_cause_survives_healthy_sample_eviction_without_unbounded_logs(store):
    assert await store.begin(ORG, DEVICE, "viewer")
    assert await store.browser(ORG, DEVICE, "viewer", SAMPLE | {
        "control_failure": "other", "control_failure_detail": "native_input_rejected_or_unknown",
        "direct_protocol": "udp", "direct_path": "nat", "direct_frames": 12,
    })
    for _ in range(20):
        assert await store.browser(ORG, DEVICE, "viewer", SAMPLE)
    row = (await store.read(ORG, DEVICE))[0]
    assert len(row["browser_samples"]) == 15
    assert all("control_failure_detail" not in sample for sample in row["browser_samples"])
    assert row["browser_summary"]["last_control_failure_detail"] == "native_input_rejected_or_unknown"
    assert datetime.fromisoformat(row["browser_summary"]["last_control_failure_at"]).tzinfo is not None
    assert len(json.dumps(row).encode()) < SESSION_BYTES


async def test_tenant_separation_closed_fencing_and_unavailable_are_explicit(store):
    assert await store.begin(ORG, DEVICE, "viewer")
    assert not await store.browser("another-org", DEVICE, "viewer", SAMPLE)
    assert await store.read("another-org", DEVICE) == []
    assert await store.end(ORG, DEVICE, "viewer")
    assert not await store.browser(ORG, DEVICE, "viewer", SAMPLE)
    assert (await store.read(ORG, DEVICE))[0]["state"] == "closed"
    unavailable = StreamSessionHistory(AsyncMock(eval=AsyncMock(side_effect=RedisConnectionError())))
    assert not await unavailable.begin(ORG, DEVICE, "other")
    assert await unavailable.read(ORG, DEVICE) is None


async def test_probe_outcomes_have_no_media_keys_and_ring_does_not_accept_arbitrary_reasons(store):
    assert await store.begin(ORG, DEVICE, "viewer")
    for i in range(5):
        assert await store.probe(ORG, DEVICE, "viewer", PROBE | {"presented_frames": i})
    assert not await store.probe(ORG, DEVICE, "viewer", PROBE | {"sdp": "private"})
    assert not await store.probe(ORG, DEVICE, "viewer", PROBE | {"reason": "arbitrary_private_data"})
    row = (await store.read(ORG, DEVICE))[0]
    assert len(row["direct_diagnostics"]) == 3
    assert row["direct_diagnostics"][-1]["presented_frames"] == 4


async def test_worker_loss_is_stale_not_a_confirmed_disconnect(store):
    assert await store.begin(ORG, DEVICE, "viewer")
    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    assert await store.update(ORG, DEVICE, "viewer", {"last_seen_at": old})
    row = (await store.read(ORG, DEVICE))[0]
    assert row["state"] == "stale" and "ended_at" not in row


async def test_individual_expiry_is_not_extended_by_another_viewer(store):
    assert await store.begin(ORG, DEVICE, "expired")
    order, records = store.keys(ORG, DEVICE)
    row = json.loads(await store.redis.hget(records, "expired"))
    row["expires_at_ms"] = 0
    await store.redis.hset(records, "expired", json.dumps(row))
    assert await store.begin(ORG, DEVICE, "current")
    assert not await store.browser(ORG, DEVICE, "expired", SAMPLE)
    assert [r["session_id"] for r in await store.read(ORG, DEVICE)] == ["current"]
    assert await store.redis.llen(order) == await store.redis.hlen(records) == 1


async def test_missing_control_receipt_stays_unknown_instead_of_zero_latency(store):
    assert await store.begin(ORG, DEVICE, "viewer")
    assert await store.browser(ORG, DEVICE, "viewer", SAMPLE | {"control_rtt_ms": None})
    assert "max_control_rtt_ms" not in (await store.read(ORG, DEVICE))[0]["browser_summary"]


async def test_primary_picture_reports_its_own_transport_and_keeps_network_and_receive_delays_separate(store):
    assert await store.begin(ORG, DEVICE, "viewer")
    sample = SAMPLE | dict(transport="direct_webrtc", control_transport="server_websocket", direct_frames=120,
        direct_fps=30, direct_frame_age_ms=20, direct_network_rtt_ms=2, direct_jitter_buffer_ms=45,
        direct_decode_ms=1.5, direct_path="host", direct_attempts=1)
    assert await store.browser(ORG, DEVICE, "viewer", sample)
    row = (await store.read(ORG, DEVICE))[0]["browser_samples"][-1]
    assert row["transport"] == "direct_webrtc" and row["control_transport"] == "server_websocket"
    assert row["direct_jitter_buffer_ms"] == 45 and row["direct_network_rtt_ms"] == 2
    assert "video_latency_ms" not in row


async def test_failed_primary_connection_records_the_exact_phase_without_claiming_direct_frames(store):
    assert await store.begin(ORG, DEVICE, "viewer")
    sample = SAMPLE | dict(direct_frames=0, direct_attempts=2, direct_state="failed",
        direct_failure="connection_deadline", direct_ice_state="checking", direct_dtls_state="new")
    assert await store.browser(ORG, DEVICE, "viewer", sample)
    row = (await store.read(ORG, DEVICE))[0]["browser_samples"][-1]
    assert row["transport"] == "server_websocket" and row["direct_frames"] == 0
    assert row["direct_failure"] == "connection_deadline" and row["direct_dtls_state"] == "new"


async def test_full_width_counters_cannot_block_recent_observations_or_session_closure(store):
    assert await store.begin(ORG, DEVICE, "viewer")
    telemetry = {
        name: 2**53 for name in AgentStreamTelemetry.model_fields
        if name.endswith("_total")
    }
    telemetry.update(schema_version=2, active=True, stage="capture_encoder_ws_queue", encoder_fps=240,
                     capture_fps=240, render_fps=240, key_frame_ratio=0.9999999999999999,
                     ws_queue_rejected_total=0)
    native = AgentStreamTelemetry.model_validate(telemetry).model_dump()
    browser = SAMPLE | {
        name: 2**53 - 1 for name in SAMPLE
        if name.endswith("_frames") or name in {"received_packets", "received_bytes", "decode_errors", "render_errors",
                                                "invalid_packets", "queue_recoveries", "stale_output_drops"}
    }
    for i in range(25):
        assert await store.browser(ORG, DEVICE, "viewer", browser | {"received_packets": i})
        assert await store.update(ORG, DEVICE, "viewer", {
            "kind": "agent_samples", "sample": {"telemetry": native, "received_at": datetime.now(timezone.utc).isoformat(),
                "observed_at": datetime.now(timezone.utc).isoformat(), "current_agent_session": True, "available": True,
                "status": "online", "version_code": 2147483647, "cpu_percent": 99.99999999999999,
                "ram_mb": 2**53 - 1, "heartbeat_at": datetime.now(timezone.utc).isoformat()},
        })
        assert await store.probe(ORG, DEVICE, "viewer", PROBE | {"presented_frames": 2**53 - 1})
        assert await store.update(ORG, DEVICE, "viewer", {"kind": "control_events", "sample": {
            "operation": "touch_event", "error": "input_rejected_or_unavailable", "reason": "agent_reconnecting",
            "retryable": True, "owner_bound": True, "received_at": datetime.now(timezone.utc).isoformat(),
        }}, limit=8)
    assert await store.end(ORG, DEVICE, "viewer")
    row = (await store.read(ORG, DEVICE))[0]
    assert row["state"] == "closed" and row["browser_samples"][-1]["received_packets"] == 24
    assert 1 <= len(row["browser_samples"]) <= 15 and 1 <= len(row["agent_samples"]) <= 15
    _, records = store.keys(ORG, DEVICE)
    assert len((await store.redis.hget(records, "viewer")).encode()) <= SESSION_BYTES


async def test_history_api_checks_ownership_before_redis_and_reports_outage(store):
    org, device_id = uuid4(), uuid4()
    user = SimpleNamespace(org_id=org)
    db = AsyncMock(get=AsyncMock(return_value=SimpleNamespace(org_id=uuid4(), is_active=True)))
    with patch("backend.api.v1.direct_probe.router.bind_tenant_context", AsyncMock()), \
         patch("backend.api.v1.direct_probe.router.StreamSessionHistory.read", AsyncMock()) as read:
        with pytest.raises(HTTPException) as denied:
            await stream_session_history(device_id, Response(), user, db)
        assert denied.value.status_code == 404
        read.assert_not_awaited()
        db.get.return_value.org_id = org
        read.return_value = None
        with pytest.raises(HTTPException) as unavailable:
            await stream_session_history(device_id, Response(), user, db)
        assert unavailable.value.status_code == 503
        read.return_value = []
        response = Response()
        history = await stream_session_history(device_id, response, user, db)
        assert history.sessions == [] and history.session_limit == 10
        assert response.headers["Cache-Control"] == "private, no-store"
