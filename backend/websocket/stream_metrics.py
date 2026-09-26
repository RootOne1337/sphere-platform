"""Apply bounded, stage-specific metrics from Android stream heartbeats."""
from __future__ import annotations

import structlog
from pydantic import ValidationError

from backend.metrics import (
    cleanup_stream_metrics,
    stream_capture_fps,
    stream_capture_frames_session,
    stream_capture_read_failures_session,
    stream_encoder_bytes_session,
    stream_encoder_errors_session,
    stream_encoder_frames_session,
    stream_fps,
    stream_frame_throttle_drops_session,
    stream_keyframe_ratio,
    stream_render_failures_session,
    stream_render_fps,
    stream_render_frames_session,
    stream_ws_queue_accepted_bytes_session,
    stream_ws_queue_accepted_session,
    stream_ws_queue_attempts_session,
    stream_ws_queue_rejected_session,
)
from backend.schemas.stream_diagnostics import AgentStreamTelemetry

logger = structlog.get_logger()

class StreamMetrics:
    """Store active-session snapshots; these values are not delivery receipts."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id

    def update_from_pong(self, stream_data: object) -> AgentStreamTelemetry | None:
        """Record validated stage counters; return the sanitized snapshot for Redis."""
        if not isinstance(stream_data, dict) or stream_data.get("active") is not True:
            self.cleanup()
            return None

        try:
            telemetry = AgentStreamTelemetry.model_validate(stream_data)
        except ValidationError:
            # Do not leave an old healthy snapshot visible after malformed telemetry.
            self.cleanup()
            logger.warning("stream.invalid_session_telemetry", device_id=self.device_id)
            return None

        metric_fields = (
            ("encoded_frames_total", stream_encoder_frames_session),
            ("encoded_bytes_total", stream_encoder_bytes_session),
            ("ws_queue_attempts_total", stream_ws_queue_attempts_session),
            ("ws_queue_accepted_total", stream_ws_queue_accepted_session),
            ("ws_queue_rejected_total", stream_ws_queue_rejected_session),
            ("ws_queue_accepted_bytes_total", stream_ws_queue_accepted_bytes_session),
        )
        stream_fps.labels(device_id=self.device_id).set(telemetry.encoder_fps)
        stream_keyframe_ratio.labels(device_id=self.device_id).set(telemetry.key_frame_ratio)
        for field, metric in metric_fields:
            metric.labels(device_id=self.device_id).set(getattr(telemetry, field))

        optional_metric_fields = (
            ("capture_fps", stream_capture_fps),
            ("render_fps", stream_render_fps),
            ("capture_frames_total", stream_capture_frames_session),
            ("rendered_frames_total", stream_render_frames_session),
            ("capture_read_failures_total", stream_capture_read_failures_session),
            ("render_failures_total", stream_render_failures_session),
            ("encoder_errors_total", stream_encoder_errors_session),
            ("frame_throttle_drops_total", stream_frame_throttle_drops_session),
        )
        for field, metric in optional_metric_fields:
            value = getattr(telemetry, field)
            if value is not None:
                metric.labels(device_id=self.device_id).set(value)

        logger.debug(
            "stream.session_metrics_updated",
            device_id=self.device_id,
            encoder_fps=telemetry.encoder_fps,
            encoded_frames=telemetry.encoded_frames_total,
            ws_queue_accepted=telemetry.ws_queue_accepted_total,
            ws_queue_rejected=telemetry.ws_queue_rejected_total,
        )
        return telemetry

    def cleanup(self) -> None:
        """Remove per-device gauge series when capture or its agent session ends."""
        cleanup_stream_metrics(self.device_id)
