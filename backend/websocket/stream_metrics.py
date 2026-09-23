"""Apply bounded, stage-specific metrics from Android stream heartbeats."""
from __future__ import annotations

import math

import structlog

from backend.metrics import (
    cleanup_stream_metrics,
    stream_encoder_bytes_session,
    stream_encoder_frames_session,
    stream_fps,
    stream_keyframe_ratio,
    stream_ws_queue_accepted_bytes_session,
    stream_ws_queue_accepted_session,
    stream_ws_queue_attempts_session,
    stream_ws_queue_rejected_session,
)

logger = structlog.get_logger()

_MAX_SESSION_COUNTER = 2**53
_MAX_ENCODER_FPS = 240


def _nonnegative_number(value: object, *, maximum: int = _MAX_SESSION_COUNTER) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value > maximum:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return int(value)


class StreamMetrics:
    """Store active-session snapshots; these values are not delivery receipts."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id

    def update_from_pong(self, stream_data: object) -> None:
        """Record encoder outputs and local WebSocket queue acceptance separately."""
        if (
            not isinstance(stream_data, dict)
            or type(stream_data.get("schema_version")) is not int
            or stream_data.get("schema_version") != 1
            or stream_data.get("active") is not True
            or stream_data.get("stage") != "encoder_and_ws_queue"
        ):
            self.cleanup()
            return

        fps = _nonnegative_number(stream_data.get("encoder_fps"), maximum=_MAX_ENCODER_FPS)
        keyframe_ratio = stream_data.get("key_frame_ratio")
        valid_keyframe_ratio = (
            isinstance(keyframe_ratio, (int, float))
            and not isinstance(keyframe_ratio, bool)
            and 0 <= keyframe_ratio <= 1
        )

        metric_fields = (
            ("encoded_frames_total", stream_encoder_frames_session),
            ("encoded_bytes_total", stream_encoder_bytes_session),
            ("ws_queue_attempts_total", stream_ws_queue_attempts_session),
            ("ws_queue_accepted_total", stream_ws_queue_accepted_session),
            ("ws_queue_rejected_total", stream_ws_queue_rejected_session),
            ("ws_queue_accepted_bytes_total", stream_ws_queue_accepted_bytes_session),
        )
        values: dict[str, int] = {}
        for field, metric in metric_fields:
            value = _nonnegative_number(stream_data.get(field))
            if value is not None:
                values[field] = value

        attempts = values.get("ws_queue_attempts_total")
        accepted = values.get("ws_queue_accepted_total")
        rejected = values.get("ws_queue_rejected_total")
        if (
            fps is None
            or not valid_keyframe_ratio
            or len(values) != len(metric_fields)
            or attempts != accepted + rejected
        ):
            # Do not leave an old healthy snapshot visible after malformed telemetry.
            self.cleanup()
            logger.warning("stream.invalid_session_telemetry", device_id=self.device_id)
            return

        stream_fps.labels(device_id=self.device_id).set(fps)
        stream_keyframe_ratio.labels(device_id=self.device_id).set(keyframe_ratio)
        for field, metric in metric_fields:
            metric.labels(device_id=self.device_id).set(values[field])

        logger.debug(
            "stream.session_metrics_updated",
            device_id=self.device_id,
            encoder_fps=fps,
            encoded_frames=stream_data.get("encoded_frames_total"),
            ws_queue_accepted=stream_data.get("ws_queue_accepted_total"),
            ws_queue_rejected=stream_data.get("ws_queue_rejected_total"),
        )

    def cleanup(self) -> None:
        """Remove per-device gauge series when capture or its agent session ends."""
        cleanup_stream_metrics(self.device_id)
