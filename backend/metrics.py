# backend/metrics.py
# ВЛАДЕЛЕЦ: TZ-05 SPLIT-4 (canonical Prometheus registry).
# HIGH-1: Все метрики стриминга регистрируются ЗДЕСЬ один раз — импортируются модулями.
# Дублирование регистрации = ValueError("Duplicated timeseries") от prometheus_client.
from __future__ import annotations

from prometheus_client import Counter, Gauge

# ─── Streaming metrics ───────────────────────────────────────────────────────

stream_fps = Gauge(
    "sphere_stream_fps",
    "Current encoding/delivery FPS for active stream",
    labelnames=["device_id"],
)

stream_bitrate_kbps = Gauge(
    "sphere_stream_bitrate_kbps",
    "Current stream bitrate in kbps (from adaptive bitrate controller)",
    labelnames=["device_id"],
)

stream_frame_drops_total = Counter(
    "sphere_stream_frame_drops_total",
    "Total number of dropped frames (WS send failures or queue overflows)",
    labelnames=["device_id"],
)

stream_bytes_sent_total = Counter(
    "sphere_stream_bytes_sent_total",
    "Total bytes forwarded from agent to viewer",
    labelnames=["device_id"],
)

stream_keyframe_ratio = Gauge(
    "sphere_stream_keyframe_ratio",
    "Ratio of keyframes to total frames in the current session",
    labelnames=["device_id"],
)


def cleanup_stream_metrics(device_id: str) -> None:
    """
    Remove per-device label sets from Gauge metrics when a stream stops.
    Counters are not removed — they accumulate across sessions by design.
    """
    for metric in (stream_fps, stream_bitrate_kbps, stream_keyframe_ratio):
        try:
            metric.remove(device_id)
        except (KeyError, ValueError):
            pass
