# backend/metrics.py
# Центральный реестр всех Prometheus-метрик Sphere Platform.
# Импортируй отсюда — не создавай метрики в отдельных модулях.
#
# Device snapshots and legacy device counters are development-only. Production
# multiprocess collection projects additive stream counters onto bounded fleet
# labels and keeps per-device snapshots in the diagnostics API (see runbook).
from __future__ import annotations

import contextlib

from prometheus_client import Counter, Gauge, Histogram

from backend.monitoring.metric_scope import (
    device_additive_gauge,
    device_counter,
    device_gauge,
    multiprocess_enabled,
)

if multiprocess_enabled():
    metrics_worker_processes = Gauge(
        "sphere_metrics_worker_processes",
        "Live worker processes that initialized Sphere instrumentation (not readiness)",
        multiprocess_mode="livesum",
    )
    metrics_worker_processes.set(1)

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
http_requests_total = Counter(
    "sphere_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
http_request_duration_seconds = Histogram(
    "sphere_http_request_duration_seconds",
    "HTTP response-header latency in seconds (not streamed response-body duration)",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
ws_connections_active = Gauge(
    "sphere_ws_connections_active",
    "Active WebSocket connections",
    ["role"],
    multiprocess_mode="livesum",
)
ws_messages_total = Counter(
    "sphere_ws_messages_total",
    "WebSocket messages processed",
    ["direction", "role"],
)
android_ws_keepalive_ack_total = Counter(
    "sphere_android_ws_keepalive_ack_total",
    "Authenticated Android WebSocket keepalive acknowledgements received",
)
android_ws_keepalive_ack_rtt_seconds = Histogram(
    "sphere_android_ws_keepalive_ack_rtt_seconds",
    "Round-trip time for the 10-second Android WebSocket keepalive",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------
devices_total = Gauge(
    "sphere_devices_total",
    "Total registered devices",
    ["org_id"],
    multiprocess_mode="livemax",
)
devices_online = Gauge(
    "sphere_devices_online",
    "Online devices right now",
    ["org_id"],
    multiprocess_mode="livemax",
)
device_commands_total = Counter(
    "sphere_device_commands_total",
    "Commands sent to devices",
    ["command_type", "status"],
)

# ---------------------------------------------------------------------------
# Tasks / Script Engine
# ---------------------------------------------------------------------------
task_queue_depth = Gauge(
    "sphere_task_queue_depth",
    "Tasks waiting in queue",
    multiprocess_mode="livemax",
)
tasks_total = Counter(
    "sphere_tasks_total",
    "Total tasks processed",
    ["status"],
)
task_execution_duration_seconds = Histogram(
    "sphere_task_execution_duration_seconds",
    "Task execution time in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# ---------------------------------------------------------------------------
# VPN (AmneziaWG)
# ---------------------------------------------------------------------------
vpn_pool_total = Gauge(
    "sphere_vpn_pool_total",
    "Total VPN IP addresses in pool",
    multiprocess_mode="livemax",
)
vpn_pool_allocated = Gauge(
    "sphere_vpn_pool_allocated",
    "Allocated VPN IP addresses",
    multiprocess_mode="livemax",
)
vpn_reconnects_total = Counter(
    "sphere_vpn_reconnects_total",
    "VPN reconnect events",
)
vpn_handshake_stale_total = Counter(
    "sphere_vpn_handshake_stale_total",
    "Stale VPN handshakes detected",
)

# ---------------------------------------------------------------------------
# Database (SQLAlchemy pool)
# ---------------------------------------------------------------------------
db_pool_size = Gauge(
    "sphere_db_pool_size",
    "SQLAlchemy connection pool size",
    multiprocess_mode="livesum",
)
db_pool_checked_out = Gauge(
    "sphere_db_pool_checked_out",
    "SQLAlchemy connections currently in use",
    multiprocess_mode="livesum",
)
db_query_duration_seconds = Histogram(
    "sphere_db_query_duration_seconds",
    "DB query duration in seconds",
    ["query_name"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
)

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
redis_commands_total = Counter(
    "sphere_redis_commands_total",
    "Redis commands executed",
    ["command"],
)
redis_errors_total = Counter(
    "sphere_redis_errors_total",
    "Redis errors encountered",
)

# ---------------------------------------------------------------------------
# H264 Streaming
# ⚠️  device_id — высокая кардинальность!
# ОБЯЗАТЕЛЬНО вызывать cleanup_stream_metrics(device_id) при остановке стрима.
# ---------------------------------------------------------------------------
stream_fps = device_gauge(
    "sphere_stream_fps",
    "Android encoder output FPS over its trailing one-second window",
    ["device_id"],
)
stream_bitrate_kbps = device_gauge(
    "sphere_stream_bitrate_kbps",
    "Current stream bitrate in kbps (from adaptive bitrate controller)",
    ["device_id"],
)
stream_frame_drops_total = device_counter(
    "sphere_stream_frame_drops_total",
    "Legacy metric; no longer populated from estimated FPS differences",
    ["device_id"],
)
stream_bytes_sent_total = device_counter(
    "sphere_stream_bytes_sent_total",
    "Legacy metric; stage-specific session gauges report current stream bytes",
    ["device_id"],
)
stream_keyframe_ratio = device_gauge(
    "sphere_stream_keyframe_ratio",
    "Ratio of keyframes to total frames in the current session",
    ["device_id"],
)
stream_encoder_frames_session = device_gauge(
    "sphere_stream_encoder_frames_session",
    "Encoder output frames counted in the current Android capture session",
    ["device_id"],
)
stream_encoder_bytes_session = device_gauge(
    "sphere_stream_encoder_bytes_session",
    "Encoded bytes counted in the current Android capture session",
    ["device_id"],
)
stream_ws_queue_attempts_session = device_gauge(
    "sphere_stream_ws_queue_attempts_session",
    "Binary frame send attempts in the current Android capture session",
    ["device_id"],
)
stream_ws_queue_accepted_session = device_gauge(
    "sphere_stream_ws_queue_accepted_session",
    "Frames accepted by the Android WebSocket client's local queue in this session",
    ["device_id"],
)
stream_ws_queue_rejected_session = device_gauge(
    "sphere_stream_ws_queue_rejected_session",
    "Frames rejected by the Android WebSocket client's local queue in this session",
    ["device_id"],
)
stream_ws_queue_accepted_bytes_session = device_gauge(
    "sphere_stream_ws_queue_accepted_bytes_session",
    "Bytes accepted by the Android WebSocket client's local queue in this session",
    ["device_id"],
)
stream_capture_fps = device_gauge(
    "sphere_stream_capture_fps",
    "ImageReader frames acquired in the current one-second Android window",
    ["device_id"],
)
stream_render_fps = device_gauge(
    "sphere_stream_render_fps",
    "Frames posted to the encoder surface in the current one-second Android window",
    ["device_id"],
)
stream_capture_frames_session = device_gauge(
    "sphere_stream_capture_frames_session",
    "ImageReader frames acquired in the current Android capture session",
    ["device_id"],
)
stream_render_frames_session = device_gauge(
    "sphere_stream_render_frames_session",
    "Frames posted to the encoder surface in the current Android capture session",
    ["device_id"],
)
stream_capture_read_failures_session = device_gauge(
    "sphere_stream_capture_read_failures_session",
    "ImageReader acquisition failures in the current Android capture session",
    ["device_id"],
)
stream_render_failures_session = device_gauge(
    "sphere_stream_render_failures_session",
    "Capture-to-encoder-surface render failures in the current Android session",
    ["device_id"],
)
stream_encoder_errors_session = device_gauge(
    "sphere_stream_encoder_errors_session",
    "MediaCodec errors reported in the current Android capture session",
    ["device_id"],
)
stream_frame_throttle_drops_session = device_gauge(
    "sphere_stream_frame_throttle_drops_session",
    "Encoded frames intentionally dropped by the Android FPS throttle in this session",
    ["device_id"],
)
stream_capture_throttle_drops_session = device_gauge(
    "sphere_stream_capture_throttle_drops_session",
    "Raw images skipped before CPU copy and encoder submission in the Android session",
    ["device_id"],
)
stream_encoder_input_drops_session = device_gauge(
    "sphere_stream_encoder_input_drops_session",
    "Raw pictures skipped when no codec input buffer is free in the current Android session",
    ["device_id"],
)
stream_backend_ingress_frames_total = device_counter(
    "sphere_stream_backend_ingress_frames_total",
    "Binary video packets received from Android WebSocket connections",
    ["device_id"],
)
stream_backend_ingress_bytes_total = device_counter(
    "sphere_stream_backend_ingress_bytes_total",
    "Binary video bytes received from Android WebSocket connections",
    ["device_id"],
)
stream_backend_ingress_packets_by_nal_total = device_counter(
    "sphere_stream_backend_ingress_packets_by_nal_total",
    "Android ingress packets classified by their first recognized H.264 NAL type",
    ["device_id", "nal_type"],
)
stream_redis_publish_calls_total = device_counter(
    "sphere_stream_redis_publish_calls_total",
    "Video messages successfully passed to Redis Pub/Sub publish",
    ["device_id"],
)
stream_redis_published_bytes_total = device_counter(
    "sphere_stream_redis_published_bytes_total",
    "Video bytes successfully passed to Redis Pub/Sub publish",
    ["device_id"],
)
stream_redis_publish_subscribers = device_gauge(
    "sphere_stream_redis_publish_subscribers",
    "Subscriber count returned by the latest successful Redis video publish",
    ["device_id"],
)
stream_redis_publish_failures_total = device_counter(
    "sphere_stream_redis_publish_failures_total",
    "Redis Pub/Sub video publish errors",
    ["device_id"],
)
stream_viewer_send_frames_total = device_counter(
    "sphere_stream_viewer_send_frames_total",
    "Video frames whose ASGI WebSocket send_bytes call completed for browser viewers",
    ["device_id"],
)
stream_viewer_send_bytes_total = device_counter(
    "sphere_stream_viewer_send_bytes_total",
    "Video bytes whose ASGI WebSocket send_bytes call completed for browser viewers",
    ["device_id"],
)
stream_viewer_send_failures_total = device_counter(
    "sphere_stream_viewer_send_failures_total",
    "Browser viewer WebSocket send_bytes failures",
    ["device_id"],
)
stream_active_viewers = device_additive_gauge(
    "sphere_stream_active_viewers",
    "Browser viewer sessions currently registered in this backend process",
    ["device_id"],
)
stream_server_queue_drops_total = device_counter(
    "sphere_stream_server_queue_drops_total",
    "Video packets dropped from bounded server queues by stage and reason",
    ["device_id", "queue_stage", "reason"],
)


def cleanup_stream_metrics(device_id: str) -> None:
    """
    Удалить Prometheus time series устройства при завершении стрима.
    Gauge метрики удаляются. Counter метрики остаются (accumulate by design).
    """
    for metric in (
        stream_fps,
        stream_bitrate_kbps,
        stream_keyframe_ratio,
        stream_encoder_frames_session,
        stream_encoder_bytes_session,
        stream_ws_queue_attempts_session,
        stream_ws_queue_accepted_session,
        stream_ws_queue_rejected_session,
        stream_ws_queue_accepted_bytes_session,
        stream_capture_fps,
        stream_render_fps,
        stream_capture_frames_session,
        stream_render_frames_session,
        stream_capture_read_failures_session,
        stream_render_failures_session,
        stream_encoder_errors_session,
        stream_frame_throttle_drops_session,
        stream_capture_throttle_drops_session,
        stream_encoder_input_drops_session,
    ):
        with contextlib.suppress(KeyError, ValueError):
            metric.remove(device_id)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
auth_attempts_total = Counter(
    "sphere_auth_attempts_total",
    "Authentication attempts",
    ["status"],
)
auth_token_refresh_total = Counter(
    "sphere_auth_token_refresh_total",
    "JWT token refresh operations",
)
