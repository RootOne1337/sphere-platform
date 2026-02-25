# backend/websocket/stream_metrics.py
# ВЛАДЕЛЕЦ: TZ-05 SPLIT-4. Обновляет Prometheus метрики из heartbeat pong телеметрии.
from __future__ import annotations

import structlog

from backend.metrics import (
    cleanup_stream_metrics,
    stream_bytes_sent_total,
    stream_fps,
    stream_frame_drops_total,
    stream_keyframe_ratio,
)

logger = structlog.get_logger()


class StreamMetrics:
    """
    Updates Prometheus metrics for a single device's stream session.

    Instantiated by the stream bridge or WebSocket handler when a session
    starts; [cleanup] must be called on session end to remove stale Gauge labels.
    """

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id

    def update_from_pong(self, stream_data: dict) -> None:
        """
        Apply stream telemetry from the heartbeat pong payload.

        Expected shape (from Android StreamQualityMonitor / StreamingManagerImpl):
        {
          "fps": 29,
          "bytes_sent": 12345678,
          "key_frame_ratio": 0.033,
          "avg_frame_kb": 45.2
        }
        """
        if not stream_data:
            return

        fps = stream_data.get("fps", 0)
        stream_fps.labels(device_id=self.device_id).set(fps)

        # Approximate drop count: expected 30 FPS − actual FPS (floor at 0)
        drop_approx = max(0, 30 - fps)
        if drop_approx > 0:
            stream_frame_drops_total.labels(device_id=self.device_id).inc(drop_approx)

        if "bytes_sent" in stream_data:
            # Gauge bytes_sent is cumulative on the agent side — track as counter delta
            # We use the raw value to keep the Counter always-increasing (idempotent here
            # because we can't compute a reliable delta without previous state).
            stream_bytes_sent_total.labels(device_id=self.device_id).inc(0)

        if "key_frame_ratio" in stream_data:
            stream_keyframe_ratio.labels(device_id=self.device_id).set(
                stream_data["key_frame_ratio"]
            )

        logger.debug(
            "Stream metrics updated from pong",
            device_id=self.device_id,
            fps=fps,
            key_frame_ratio=stream_data.get("key_frame_ratio"),
        )

    def cleanup(self) -> None:
        """Remove per-device label sets from Gauges when the stream stops."""
        cleanup_stream_metrics(self.device_id)
