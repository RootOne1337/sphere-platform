# backend/metrics.py
# Центральный реестр всех Prometheus-метрик Sphere Platform.
# Импортируй отсюда — не создавай метрики в отдельных модулях.
#
# ⚠️  КАРТОЧНОСТЬ: не используй device_id/user_id как label в Counter/Histogram —
#     это приведёт к стремительному росту series. Допустимо только в Gauge с
#     обязательной функцией cleanup (cleanup_stream_metrics ниже).
from __future__ import annotations

import contextlib

from prometheus_client import Counter, Gauge, Histogram

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
    "HTTP request duration in seconds",
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
)
ws_messages_total = Counter(
    "sphere_ws_messages_total",
    "WebSocket messages processed",
    ["direction", "role"],
)

# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------
devices_total = Gauge(
    "sphere_devices_total",
    "Total registered devices",
    ["org_id"],
)
devices_online = Gauge(
    "sphere_devices_online",
    "Online devices right now",
    ["org_id"],
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
)
vpn_pool_allocated = Gauge(
    "sphere_vpn_pool_allocated",
    "Allocated VPN IP addresses",
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
)
db_pool_checked_out = Gauge(
    "sphere_db_pool_checked_out",
    "SQLAlchemy connections currently in use",
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
stream_fps = Gauge(
    "sphere_stream_fps",
    "Current encoding/delivery FPS for active stream",
    ["device_id"],
)
stream_bitrate_kbps = Gauge(
    "sphere_stream_bitrate_kbps",
    "Current stream bitrate in kbps (from adaptive bitrate controller)",
    ["device_id"],
)
stream_frame_drops_total = Counter(
    "sphere_stream_frame_drops_total",
    "Total number of dropped frames (WS send failures or queue overflows)",
    ["device_id"],
)
stream_bytes_sent_total = Counter(
    "sphere_stream_bytes_sent_total",
    "Total bytes forwarded from agent to viewer",
    ["device_id"],
)
stream_keyframe_ratio = Gauge(
    "sphere_stream_keyframe_ratio",
    "Ratio of keyframes to total frames in the current session",
    ["device_id"],
)


def cleanup_stream_metrics(device_id: str) -> None:
    """
    Удалить Prometheus time series устройства при завершении стрима.
    Gauge метрики удаляются. Counter метрики остаются (accumulate by design).
    """
    for metric in (stream_fps, stream_bitrate_kbps, stream_keyframe_ratio):
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
