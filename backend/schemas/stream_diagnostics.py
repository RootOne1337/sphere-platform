"""Bounded, privacy-safe streaming telemetry shared by the agent and API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_MAX_COUNTER = 2**53


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
