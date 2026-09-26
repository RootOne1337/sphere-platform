"""Stream telemetry must preserve stage semantics and bounded metric cleanup."""
from __future__ import annotations

import math
import uuid

from backend.metrics import (
    stream_bytes_sent_total,
    stream_capture_fps,
    stream_capture_frames_session,
    stream_capture_read_failures_session,
    stream_encoder_bytes_session,
    stream_encoder_errors_session,
    stream_encoder_frames_session,
    stream_fps,
    stream_frame_drops_total,
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
from backend.websocket.stream_metrics import StreamMetrics


def _device_id() -> str:
    return f"stream-test-{uuid.uuid4()}"


def _active_stream_data(**overrides) -> dict:
    data = {
        "schema_version": 1,
        "active": True,
        "stage": "encoder_and_ws_queue",
        "encoder_fps": 8,
        "encoded_frames_total": 20,
        "encoded_bytes_total": 1024,
        "key_frame_ratio": 0.05,
        "ws_queue_attempts_total": 22,
        "ws_queue_accepted_total": 20,
        "ws_queue_rejected_total": 2,
        "ws_queue_accepted_bytes_total": 1100,
    }
    data.update(overrides)
    return data


def _active_stream_data_v2(**overrides) -> dict:
    data = _active_stream_data()
    data.update({
        "schema_version": 2,
        "stage": "capture_encoder_ws_queue",
        "capture_fps": 15,
        "render_fps": 14,
        "capture_frames_total": 150,
        "rendered_frames_total": 140,
        "capture_read_failures_total": 1,
        "render_failures_total": 2,
        "encoder_errors_total": 3,
        "frame_throttle_drops_total": 10,
    })
    data.update(overrides)
    return data


def test_active_pong_records_encoder_and_local_queue_stages_separately():
    device_id = _device_id()
    metrics = StreamMetrics(device_id)
    try:
        metrics.update_from_pong({
            "schema_version": 1,
            "active": True,
            "stage": "encoder_and_ws_queue",
            "encoder_fps": 17,
            "encoded_frames_total": 88,
            "encoded_bytes_total": 456_789,
            "key_frame_ratio": 0.125,
            "ws_queue_attempts_total": 92,
            "ws_queue_accepted_total": 90,
            "ws_queue_rejected_total": 2,
            "ws_queue_accepted_bytes_total": 440_000,
        })

        assert stream_fps.labels(device_id=device_id)._value.get() == 17
        assert stream_keyframe_ratio.labels(device_id=device_id)._value.get() == 0.125
        assert stream_encoder_frames_session.labels(device_id=device_id)._value.get() == 88
        assert stream_encoder_bytes_session.labels(device_id=device_id)._value.get() == 456_789
        assert stream_ws_queue_attempts_session.labels(device_id=device_id)._value.get() == 92
        assert stream_ws_queue_accepted_session.labels(device_id=device_id)._value.get() == 90
        assert stream_ws_queue_rejected_session.labels(device_id=device_id)._value.get() == 2
        assert stream_ws_queue_accepted_bytes_session.labels(device_id=device_id)._value.get() == 440_000
        # Encoder output and local queue acceptance are not server/viewer delivery receipts.
        assert (device_id,) not in stream_bytes_sent_total._metrics
        assert (device_id,) not in stream_frame_drops_total._metrics
    finally:
        metrics.cleanup()


def test_v2_pong_records_capture_surface_encoder_and_queue_stages():
    device_id = _device_id()
    metrics = StreamMetrics(device_id)
    try:
        telemetry = metrics.update_from_pong(_active_stream_data_v2())

        assert telemetry is not None
        assert telemetry.capture_frames_total == 150
        assert stream_capture_fps.labels(device_id=device_id)._value.get() == 15
        assert stream_render_fps.labels(device_id=device_id)._value.get() == 14
        assert stream_capture_frames_session.labels(device_id=device_id)._value.get() == 150
        assert stream_render_frames_session.labels(device_id=device_id)._value.get() == 140
        assert stream_capture_read_failures_session.labels(device_id=device_id)._value.get() == 1
        assert stream_render_failures_session.labels(device_id=device_id)._value.get() == 2
        assert stream_encoder_errors_session.labels(device_id=device_id)._value.get() == 3
        assert stream_frame_throttle_drops_session.labels(device_id=device_id)._value.get() == 10
    finally:
        metrics.cleanup()


def test_missing_or_inactive_stream_clears_live_session_gauges():
    device_id = _device_id()
    metrics = StreamMetrics(device_id)
    metrics.update_from_pong(_active_stream_data())
    metrics.update_from_pong(None)

    assert (device_id,) not in stream_fps._metrics
    assert (device_id,) not in stream_encoder_frames_session._metrics
    assert (device_id,) not in stream_capture_frames_session._metrics


def test_inactive_capture_clears_live_session_gauges():
    device_id = _device_id()
    metrics = StreamMetrics(device_id)
    metrics.update_from_pong(_active_stream_data())
    metrics.update_from_pong({"active": False})

    assert (device_id,) not in stream_fps._metrics


def test_invalid_values_are_ignored_without_creating_sampled_metrics():
    device_id = _device_id()
    metrics = StreamMetrics(device_id)
    try:
        metrics.update_from_pong(_active_stream_data(
            encoder_fps=10**1000,
            encoded_frames_total=-1,
            encoded_bytes_total=True,
            key_frame_ratio=math.nan,
            ws_queue_accepted_total=float("inf"),
        ))

        assert (device_id,) not in stream_fps._metrics
        assert (device_id,) not in stream_encoder_frames_session._metrics
        assert (device_id,) not in stream_encoder_bytes_session._metrics
        assert (device_id,) not in stream_keyframe_ratio._metrics
        assert (device_id,) not in stream_ws_queue_accepted_session._metrics
        assert (device_id,) not in stream_capture_frames_session._metrics
        metrics.update_from_pong(_active_stream_data(key_frame_ratio=10**1000))
        assert (device_id,) not in stream_keyframe_ratio._metrics
        metrics.update_from_pong(_active_stream_data(key_frame_ratio=math.nan))
        assert (device_id,) not in stream_keyframe_ratio._metrics
        metrics.update_from_pong(_active_stream_data_v2(render_fps=None))
        assert (device_id,) not in stream_capture_fps._metrics
    finally:
        metrics.cleanup()


def test_invalid_active_snapshot_clears_previous_values_instead_of_showing_stale_health():
    device_id = _device_id()
    metrics = StreamMetrics(device_id)
    metrics.update_from_pong(_active_stream_data())
    metrics.update_from_pong(_active_stream_data(ws_queue_attempts_total=100))

    assert (device_id,) not in stream_fps._metrics
    assert (device_id,) not in stream_encoder_frames_session._metrics
