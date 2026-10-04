"""Bounded-cardinality counters at server video-plane boundaries."""
from __future__ import annotations

import structlog

from backend.metrics import (
    stream_active_viewers,
    stream_backend_ingress_bytes_total,
    stream_backend_ingress_frames_total,
    stream_backend_ingress_packets_by_nal_total,
    stream_redis_publish_calls_total,
    stream_redis_publish_failures_total,
    stream_redis_publish_subscribers,
    stream_redis_published_bytes_total,
    stream_server_queue_drops_total,
    stream_viewer_send_bytes_total,
    stream_viewer_send_failures_total,
    stream_viewer_send_frames_total,
)
from backend.websocket.frames import detect_first_nal_type

logger = structlog.get_logger()


def _metric_error(operation: str, error: Exception) -> None:
    # Metrics are best-effort and must never interrupt video delivery.
    try:
        logger.debug(
            "stream.metric_update_failed",
            operation=operation,
            error_type=type(error).__name__,
        )
    except Exception:
        # A broken log sink must not turn a metrics failure into a media failure.
        pass


def record_backend_ingress(device_id: str, data: bytes) -> None:
    """Count bytes received by the Android WebSocket route, without storing them."""
    try:
        stream_backend_ingress_frames_total.labels(device_id=device_id).inc()
        stream_backend_ingress_bytes_total.labels(device_id=device_id).inc(len(data))
        nal_type = detect_first_nal_type(data)
        stream_backend_ingress_packets_by_nal_total.labels(
            device_id=device_id,
            nal_type=nal_type.name.lower(),
        ).inc()
    except Exception as error:
        _metric_error("backend_ingress", error)


def record_redis_publish(device_id: str, size_bytes: int, subscribers: int) -> None:
    """Record a successful Redis publish call and its subscriber count."""
    try:
        stream_redis_publish_calls_total.labels(device_id=device_id).inc()
        stream_redis_published_bytes_total.labels(device_id=device_id).inc(size_bytes)
        stream_redis_publish_subscribers.labels(device_id=device_id).set(subscribers)
    except Exception as error:
        _metric_error("redis_publish", error)


def record_redis_publish_failure(device_id: str) -> None:
    try:
        stream_redis_publish_failures_total.labels(device_id=device_id).inc()
    except Exception as error:
        _metric_error("redis_publish_failure", error)


def record_viewer_send(device_id: str, size_bytes: int) -> None:
    try:
        stream_viewer_send_frames_total.labels(device_id=device_id).inc()
        stream_viewer_send_bytes_total.labels(device_id=device_id).inc(size_bytes)
    except Exception as error:
        _metric_error("viewer_send", error)


def record_viewer_send_failure(device_id: str) -> None:
    try:
        stream_viewer_send_failures_total.labels(device_id=device_id).inc()
    except Exception as error:
        _metric_error("viewer_send_failure", error)


def record_active_viewer_delta(device_id: str, delta: int) -> None:
    try:
        gauge = stream_active_viewers.labels(device_id=device_id)
        if delta > 0:
            gauge.inc(delta)
        elif delta < 0:
            gauge.dec(-delta)
    except Exception as error:
        _metric_error("active_viewer", error)


def record_server_queue_drop(device_id: str, queue_stage: str, reason: str) -> None:
    try:
        stream_server_queue_drops_total.labels(
            device_id=device_id,
            queue_stage=queue_stage,
            reason=reason,
        ).inc()
    except Exception as error:
        _metric_error("server_queue_drop", error)
