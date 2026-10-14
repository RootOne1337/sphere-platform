"""Bounded, privacy-safe streaming telemetry shared by the agent and API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.schemas.stream_quality import StreamQualitySnapshot

_MAX_COUNTER = 2**53


class NativeInputTelemetry(BaseModel):
    """Small agent-process snapshot; never an input trace or execution receipt."""

    model_config = ConfigDict(extra="ignore", strict=True)

    schema_version: Literal[1]
    scope: Literal["agent_process"]
    state: Literal["disabled", "idle", "opening", "ready", "retiring", "cleanup_unknown"]
    last_failure: Literal[
        "active_owner", "retiring_owner", "capture_unavailable", "capture_changed",
        "direct_channel_unavailable", "authorization_expired", "transport_changed",
        "supervisor_busy", "cleanup_unknown", "native_startup_failed", "native_input_failed",
        "input_not_ready", "input_rejected", "receipt_unavailable", "scope_inactive",
    ] | None = None
    last_failure_age_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    last_input_detail: Literal[
        "touch_ack_timeout", "touch_ack_mismatch", "touch_ack_action_mismatch", "touch_process_exited",
        "touch_ack_eof", "native_expired", "native_rejected", "native_unknown", "touch_cleanup_unknown",
        "native_adapter_exception",
    ] | None = None
    last_input_detail_age_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    last_startup_detail: Literal[
        "root_required", "root_geometry", "root_adapter_unavailable", "root_configuration",
        "root_handshake", "root_process_exited", "root_ready_timeout", "root_handoff_unknown", "root_input_busy",
    ] | None = None
    last_startup_detail_age_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    # A confirmed native RELEASE describes cleanup, not why the owner ended.
    # Keep its first local cause separately, without input samples or owner IDs.
    last_release_reason: Literal[
        "owner_retired", "viewer_closed", "viewer_heartbeat_expired", "pending_input_expired",
        "invalid_input", "queue_overflow", "clock_regression", "authorization_expired",
        "scope_inactive", "transport_changed", "capture_changed", "direct_channel_unavailable",
        "receipt_unavailable", "native_failure", "startup_refused", "cleanup_unknown",
    ] | None = None
    last_release_age_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    open_attempts_total: int = Field(ge=0, le=_MAX_COUNTER)
    open_rejections_total: int = Field(ge=0, le=_MAX_COUNTER)
    startups_total: int = Field(ge=0, le=_MAX_COUNTER)
    startup_failures_total: int = Field(ge=0, le=_MAX_COUNTER)
    input_failures_total: int = Field(ge=0, le=_MAX_COUNTER)
    releases_total: int = Field(ge=0, le=_MAX_COUNTER)
    unknown_releases_total: int = Field(ge=0, le=_MAX_COUNTER)
    keyboard_commands_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    keyboard_accepted_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    keyboard_refused_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    keyboard_unknown_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    last_keyboard_result: Literal["accepted", "no_editor", "stale_editor", "unavailable", "unknown"] | None = None
    last_keyboard_result_age_ms: int | None = Field(default=None, ge=0, le=86_400_000)

    @model_validator(mode="after")
    def validate_failure_age(self) -> "NativeInputTelemetry":
        if (self.last_keyboard_result is None) != (self.last_keyboard_result_age_ms is None):
            raise ValueError("keyboard result and monotonic age must be paired")
        if (self.last_failure is None) != (self.last_failure_age_ms is None):
            raise ValueError("native input failure and its monotonic age must be paired")
        if (self.last_input_detail is None) != (self.last_input_detail_age_ms is None):
            raise ValueError("native input detail and its monotonic age must be paired")
        if (self.last_startup_detail is None) != (self.last_startup_detail_age_ms is None):
            raise ValueError("native startup detail and its monotonic age must be paired")
        if (self.last_release_reason is None) != (self.last_release_age_ms is None):
            raise ValueError("native release reason and its monotonic age must be paired")
        return self


class AgentStreamTelemetry(BaseModel):
    """Cumulative counters reported by one Android capture session.

    Version 1 is accepted for already-installed agents. Version 2 adds capture
    and surface-render stages so a zero encoder rate can be localized.
    """

    model_config = ConfigDict(extra="ignore", strict=True)

    schema_version: Literal[1, 2]
    active: Literal[True]
    stage: Literal["encoder_and_ws_queue", "capture_encoder_ws_queue"]
    encoder_fps: int = Field(ge=0, le=240)
    encoded_frames_total: int = Field(ge=0, le=_MAX_COUNTER)
    encoded_bytes_total: int = Field(ge=0, le=_MAX_COUNTER)
    key_frame_ratio: float = Field(ge=0.0, le=1.0)
    ws_queue_attempts_total: int = Field(ge=0, le=_MAX_COUNTER)
    ws_queue_accepted_total: int = Field(ge=0, le=_MAX_COUNTER)
    ws_queue_rejected_total: int = Field(ge=0, le=_MAX_COUNTER)
    ws_queue_accepted_bytes_total: int = Field(ge=0, le=_MAX_COUNTER)
    capture_fps: int | None = Field(default=None, ge=0, le=240)
    render_fps: int | None = Field(default=None, ge=0, le=240)
    capture_frames_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    rendered_frames_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    capture_read_failures_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    render_failures_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    encoder_errors_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    frame_throttle_drops_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    # Optional v2 extension: absent in older installed agents means unknown,
    # not zero. Keep the legacy encoded-drop field's meaning unchanged.
    capture_throttle_drops_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    # A raw picture skipped because no codec input buffer was free. Older
    # agents omit this; do not infer zero or confuse it with coded frame loss.
    encoder_input_drops_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    # Ages are local monotonic durations at the snapshot, not synchronized wall
    # clocks. A cached-picture refresh must not reset the capture/render ages.
    last_capture_age_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    last_render_age_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    last_encoded_age_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    idle_refresh_frames_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    # Deliberately skipped duplicate WS packets; never coded RTP loss.
    legacy_suppressed_packets_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    legacy_suppressed_encoded_bytes_total: int | None = Field(default=None, ge=0, le=_MAX_COUNTER)
    # Optional, process-scoped canary extension. Missing means unreported, not idle.
    native_input: NativeInputTelemetry | None = None
    # Source policy and applied encoder targets; never confuse these with measured FPS.
    source_quality: StreamQualitySnapshot | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "AgentStreamTelemetry":
        if self.ws_queue_attempts_total != (
            self.ws_queue_accepted_total + self.ws_queue_rejected_total
        ):
            raise ValueError("queue attempts must equal accepted plus rejected")
        if self.schema_version == 1:
            if self.stage != "encoder_and_ws_queue":
                raise ValueError("version 1 requires encoder_and_ws_queue stage")
            return self
        if self.stage != "capture_encoder_ws_queue":
            raise ValueError("version 2 requires capture_encoder_ws_queue stage")
        required_v2 = (
            self.capture_fps,
            self.render_fps,
            self.capture_frames_total,
            self.rendered_frames_total,
            self.capture_read_failures_total,
            self.render_failures_total,
            self.encoder_errors_total,
            self.frame_throttle_drops_total,
        )
        if any(value is None for value in required_v2):
            raise ValueError("version 2 requires all capture and render counters")
        return self


class StoredStreamDiagnostics(BaseModel):
    """Latest small snapshot; never contains video data or credentials."""

    telemetry: AgentStreamTelemetry
    observed_at: datetime
    agent_session_id: str | None = Field(default=None, max_length=128)


class StreamDiagnosticsResponse(BaseModel):
    device_id: str
    state: Literal["active_report", "not_streaming", "stale", "unavailable"]
    agent_status: str | None = None
    last_heartbeat: datetime | None = None
    age_seconds: float | None = Field(default=None, ge=0)
    diagnostics: StoredStreamDiagnostics | None = None
