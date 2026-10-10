"""Ten bounded diagnostic records per tenant/device; never store media or input."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.exceptions import RedisError

from backend.services.device_status_cache import DeviceStatusCache

SESSION_LIMIT = 10
SAMPLE_LIMIT = 15  # Last 15 browser + 15 Android observations, independently.
SESSION_BYTES = 32 * 1024
RETENTION_SECONDS = 7 * 86400
REPORT_INTERVAL_SECONDS = 10

Counter = Annotated[int, Field(ge=0, le=2**53 - 1)]
Milliseconds = Annotated[float, Field(ge=0, le=86400000, allow_inf_nan=False)]
DirectFailure = Literal[
    "probe_deadline", "gathering_deadline", "signaling_deadline", "connection_deadline",
    "invalid_description", "missing_binding", "signaling_unavailable", "invalid_ice_grant",
    "invalid_answer", "invalid_signal", "signaling_closed", "webrtc_unavailable", "invalid_video_track",
    "video_track_ended", "video_renderer_failed", "peer_disconnected", "echo_timeout", "channel_backpressure",
    "echo_send_failed", "invalid_video_binding", "invalid_echo", "channel_failed", "channel_closed", "offer_failed",
    "video_access_rejected", "video_first_frame_timeout", "video_renderer_unavailable", "capture_changed", "session_lifetime", "other",
]


class BrowserStreamSample(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    transport: Literal["server_websocket", "direct_webrtc"]
    control_transport: Literal["server_websocket"] = "server_websocket"
    direct_frames: Counter | None = None
    direct_frame_age_ms: Milliseconds | None = None
    direct_path: Literal["host", "nat", "relay", "unknown"] | None = None
    direct_protocol: Literal["udp", "tcp"] | None = None
    direct_network_rtt_ms: Milliseconds | None = None
    direct_jitter_buffer_ms: Milliseconds | None = None
    direct_decode_ms: Milliseconds | None = None
    direct_fps: Annotated[float, Field(ge=0, le=1024, allow_inf_nan=False)] | None = None
    direct_attempts: Annotated[int, Field(ge=0, le=1000000)] | None = None
    direct_state: Literal["gathering", "signaling", "connecting", "connected", "finished", "stopped", "failed"] | None = None
    direct_failure: DirectFailure | None = None
    direct_ice_state: Literal["new", "checking", "connected", "completed", "disconnected", "failed", "closed"] | None = None
    direct_dtls_state: Literal["new", "connecting", "connected", "closed", "failed"] | None = None
    visibility: Literal["visible", "hidden"]
    received_packets: Counter
    received_bytes: Counter
    rendered_frames: Counter
    decoded_frames: Counter
    invalid_packets: Counter
    decode_errors: Counter
    render_errors: Counter
    queue_recoveries: Counter
    stale_output_drops: Counter
    decoder_queue: Annotated[int, Field(ge=0, le=1024)]
    pending_outputs: Annotated[int, Field(ge=0, le=1024)]
    incoming_fps: Annotated[float, Field(ge=0, le=1024, allow_inf_nan=False)]
    rendered_fps: Annotated[float, Field(ge=0, le=1024, allow_inf_nan=False)]
    packet_age_ms: Milliseconds | None
    frame_age_ms: Milliseconds | None
    control_state: Literal["idle", "probing", "opening", "ready", "closing", "closed", "fenced", "destroyed"]
    control_failure: Literal["none", "timeout", "server_rejected", "admission_retry", "runtime_retry", "other"]
    control_failure_detail: Literal[
        "native_receipt_timeout", "native_startup_busy", "native_input_rejected_or_unknown",
        "server_rejected", "server_runtime_retry", "server_admission_retry", "release_unknown", "pointer_release_unknown",
        "discrete_result_unknown", "scheduler_gap", "socket_backpressure", "socket_send_failed",
        "invalid_native_receipt", "invalid_startup_receipt", "invalid_input_receipt", "receipt_action_mismatch",
    ] | None = None
    control_rtt_ms: Milliseconds | None
    recovery_attempts: Annotated[int, Field(ge=0, le=1000000)]


class DirectDiagnosticResult(BaseModel):
    """Client-reported outcome, not evidence of native input execution."""
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    mode: Literal["readonly_video"]
    trigger: Literal["automatic", "manual"]
    profile: Literal["host", "public-stun", "turn"]
    state: Literal["finished", "stopped", "failed"]
    path: Literal["host", "nat", "relay", "unknown"]
    protocol: Literal["udp", "tcp"] | None
    reason: DirectFailure | None
    echoes: Annotated[int, Field(ge=0, le=20)]
    echo_rtt_p95_ms: Milliseconds | None
    presented_frames: Counter
    width: Annotated[int, Field(ge=1, le=16384)] | None
    height: Annotated[int, Field(ge=1, le=16384)] | None
    ice_state: Literal["new", "checking", "connected", "completed", "disconnected", "failed", "closed"] | None
    dtls_state: Literal["new", "connecting", "connected", "closed", "failed"] | None


# Both keys share a Redis Cluster hash slot. Atomic eviction prevents a late
# report from reintroducing an eleventh session or overwriting a newer viewer.
_BEGIN = """
for _, id in ipairs(redis.call('LRANGE', KEYS[1], 0, 9)) do
  local raw = redis.call('HGET', KEYS[2], id)
  if raw and cjson.decode(raw).expires_at_ms <= tonumber(ARGV[5]) then
    redis.call('HDEL', KEYS[2], id); redis.call('LREM', KEYS[1], 0, id)
  end
end
if redis.call('HEXISTS', KEYS[2], ARGV[1]) == 1 then return 0 end
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('LPUSH', KEYS[1], ARGV[1])
local old = redis.call('LRANGE', KEYS[1], tonumber(ARGV[3]), -1)
for _, id in ipairs(old) do redis.call('HDEL', KEYS[2], id) end
redis.call('LTRIM', KEYS[1], 0, tonumber(ARGV[3])-1)
redis.call('EXPIRE', KEYS[1], ARGV[4]); redis.call('EXPIRE', KEYS[2], ARGV[4])
return 1
"""
_UPDATE = """
local raw = redis.call('HGET', KEYS[2], ARGV[1])
if not raw then return 0 end
local record = cjson.decode(raw)
if record.expires_at_ms <= tonumber(ARGV[6]) then
  redis.call('HDEL', KEYS[2], ARGV[1]); redis.call('LREM', KEYS[1], 0, ARGV[1]); return 0
end
if record.ended_at then return 0 end
local patch = cjson.decode(ARGV[2])
if patch.sample then
  local name = patch.kind
  local samples = record[name] or {}
  table.insert(samples, patch.sample)
  while #samples > tonumber(ARGV[3]) do table.remove(samples, 1) end
  record[name] = samples
  if name == 'browser_samples' then
    local summary = record.browser_summary or {reports=0, max_decode_errors=0, max_render_errors=0}
    summary.reports = math.min(summary.reports + 1, 9007199254740991)
    if patch.sample.control_rtt_ms then
      summary.max_control_rtt_ms = math.max(summary.max_control_rtt_ms or 0, patch.sample.control_rtt_ms)
    end
    summary.max_decode_errors = math.max(summary.max_decode_errors, patch.sample.decode_errors)
    summary.max_render_errors = math.max(summary.max_render_errors, patch.sample.render_errors)
    if patch.sample.control_failure_detail then
      summary.last_control_failure_detail = patch.sample.control_failure_detail
      summary.last_control_failure_at = patch.sample.received_at
    end
    record.browser_summary = summary
  end
end
if patch.ended_at then record.ended_at = patch.ended_at end
if patch.last_seen_at then record.last_seen_at = patch.last_seen_at end
record.expires_at_ms = tonumber(ARGV[6]) + tonumber(ARGV[5])*1000
local encoded = cjson.encode(record)
-- Preserve the latest observations and session closure even when every
-- counter uses its maximum width. Discard oldest detail before dropping a
-- whole update; each collection still retains its newest observation.
while #encoded > tonumber(ARGV[4]) do
  local largest = nil
  local largest_size = 0
  for _, name in ipairs({'browser_samples', 'agent_samples', 'control_events', 'direct_diagnostics'}) do
    local samples = record[name]
    if samples and #samples > 1 then
      local size = #cjson.encode(samples)
      if size > largest_size then largest = name; largest_size = size end
    end
  end
  if not largest then return 0 end
  table.remove(record[largest], 1)
  encoded = cjson.encode(record)
end
if #encoded > tonumber(ARGV[4]) then return 0 end
redis.call('HSET', KEYS[2], ARGV[1], encoded)
redis.call('EXPIRE', KEYS[1], ARGV[5]); redis.call('EXPIRE', KEYS[2], ARGV[5])
return 1
"""
_READ = """
local result = {}
for _, id in ipairs(redis.call('LRANGE', KEYS[1], 0, 9)) do
  local raw = redis.call('HGET', KEYS[2], id)
  if raw then
    if cjson.decode(raw).expires_at_ms > tonumber(ARGV[1]) then table.insert(result, raw)
    else redis.call('HDEL', KEYS[2], id); redis.call('LREM', KEYS[1], 0, id) end
  end
end
return result
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StreamSessionHistory:
    def __init__(self, redis: Any, binary_redis: Any = None) -> None:
        self.redis = redis
        self.cache = DeviceStatusCache(binary_redis)

    @staticmethod
    def keys(org: str, device: str) -> tuple[str, str]:
        # org/device values come exclusively from authenticated server identity.
        base = f"stream:history:v1:{{{org}:{device}}}"
        return base + ":order", base + ":records"

    async def _eval(self, script: str, org: str, device: str, *args: Any) -> Any:
        if self.redis is None:
            return None
        try:
            async with asyncio.timeout(0.5):
                return await self.redis.eval(script, 2, *self.keys(org, device), *args)
        except (RedisError, TimeoutError):
            return None  # Diagnostic storage must never interrupt video/input.

    async def begin(self, org: str, device: str, session: str) -> bool:
        now = utc_now()
        record = {"schema_version": 1, "session_id": session, "device_id": device,
                  "opened_at": now, "last_seen_at": now, "transport": "server_websocket",
                  "expires_at_ms": int(time.time() * 1000) + RETENTION_SECONDS * 1000}
        return bool(await self._eval(_BEGIN, org, device, session, json.dumps(record), SESSION_LIMIT,
                                    RETENTION_SECONDS, int(time.time() * 1000)))

    async def update(self, org: str, device: str, session: str, patch: dict[str, Any], limit: int = SAMPLE_LIMIT) -> bool:
        encoded = json.dumps(patch, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) > 4096:
            return False
        return bool(await self._eval(_UPDATE, org, device, session, encoded, limit, SESSION_BYTES,
                                    RETENTION_SECONDS, int(time.time() * 1000)))

    @staticmethod
    def validated_sample(data: Any, *, probe: bool = False) -> dict[str, Any] | None:
        try:
            value = DirectDiagnosticResult.model_validate(data) if probe else BrowserStreamSample.model_validate(data)
            return value.model_dump(exclude_none=True)
        except ValidationError:
            return None

    async def browser(self, org: str, device: str, session: str, data: Any) -> bool:
        sample = self.validated_sample(data)
        if sample is None:
            return False
        return await self.update(org, device, session, {
            "kind": "browser_samples", "sample": sample | {"received_at": utc_now()},
        })

    async def probe(self, org: str, device: str, session: str, data: Any) -> bool:
        result = self.validated_sample(data, probe=True)
        if result is None:
            return False
        return await self.update(org, device, session, {
            "kind": "direct_diagnostics", "sample": result | {"received_at": utc_now()},
        }, limit=3)

    async def observe_agent(self, org: str, device: str, session: str) -> bool:
        now = utc_now()
        sample: dict[str, Any] = {"received_at": now, "available": False}
        try:
            async with asyncio.timeout(0.5):
                status = await self.cache.get_status(device)
                snapshot = await self.cache.get_stream_diagnostics(device)
            if status:
                sample["status"] = status.status
                sample["version_code"] = status.agent_version_code
                sample["heartbeat_at"] = status.last_heartbeat.isoformat() if status.last_heartbeat else None
                sample["cpu_percent"] = status.cpu_usage
                sample["ram_mb"] = min(2**53 - 1, max(0, status.ram_usage_mb)) if status.ram_usage_mb is not None else None
            if snapshot:
                # Preserve source timestamp and ownership match; old counters
                # never become fresh because the observer read them again.
                sample.update(available=True, observed_at=snapshot.observed_at.isoformat(),
                              current_agent_session=bool(status and status.ws_session_id == snapshot.agent_session_id),
                              telemetry=snapshot.telemetry.model_dump(exclude_none=True))
        except (RedisError, TimeoutError):
            pass
        return await self.update(org, device, session, {"kind": "agent_samples", "sample": sample, "last_seen_at": now})

    async def end(self, org: str, device: str, session: str) -> bool:
        return await self.update(org, device, session, {"ended_at": utc_now()})

    async def read(self, org: str, device: str) -> list[dict[str, Any]] | None:
        values = await self._eval(_READ, org, device, int(time.time() * 1000))
        if values is None:
            return None
        records = []
        for value in values[:SESSION_LIMIT]:
            if len(value) > SESSION_BYTES:
                continue
            try:
                record = json.loads(value)
                last_seen = datetime.fromisoformat(record["last_seen_at"]).timestamp()
                record["state"] = "closed" if record.get("ended_at") else "active" if time.time() - last_seen < 45 else "stale"
                records.append(record)
            except (ValueError, KeyError, TypeError):
                continue
        return records
