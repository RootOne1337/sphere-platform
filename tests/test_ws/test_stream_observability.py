"""Server video-plane counters must distinguish ingress, routing and queue drops."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.ws.android.router import handle_agent_binary
from backend.metrics import (
    stream_backend_ingress_bytes_total,
    stream_backend_ingress_frames_total,
    stream_backend_ingress_packets_by_nal_total,
    stream_redis_publish_calls_total,
    stream_redis_publish_subscribers,
    stream_redis_published_bytes_total,
    stream_server_queue_drops_total,
)
from backend.websocket import stream_observability
from backend.websocket.frames import VideoFrame
from backend.websocket.stream_bridge import VideoStreamBridge
from backend.websocket.stream_observability import record_redis_publish
from backend.websocket.video_queue import VideoStreamQueue


def _wire_frame(nal_header: int = 0x65) -> bytes:
    payload = b"\x00\x00\x00\x01" + bytes([nal_header]) + b"\x11\x22"
    return (
        b"\x01\x00"
        + (1234).to_bytes(8, "big")
        + len(payload).to_bytes(4, "big")
        + payload
    )


@pytest.mark.asyncio
async def test_android_binary_route_records_server_ingress_even_without_bridge(monkeypatch):
    from backend.websocket import stream_bridge

    device_id = f"stream-ingress-{uuid.uuid4()}"
    frame = _wire_frame()
    monkeypatch.setattr(stream_bridge, "get_stream_bridge", lambda: None)

    await handle_agent_binary(device_id, frame, MagicMock())

    assert stream_backend_ingress_frames_total.labels(device_id=device_id)._value.get() == 1
    assert stream_backend_ingress_bytes_total.labels(device_id=device_id)._value.get() == len(frame)
    assert (
        stream_backend_ingress_packets_by_nal_total.labels(
            device_id=device_id, nal_type="idr_slice",
        )._value.get()
        == 1
    )


def test_successful_redis_publish_records_bytes_and_subscriber_receipt():
    device_id = f"stream-redis-{uuid.uuid4()}"
    record_redis_publish(device_id, size_bytes=4096, subscribers=2)

    assert stream_redis_publish_calls_total.labels(device_id=device_id)._value.get() == 1
    assert stream_redis_published_bytes_total.labels(device_id=device_id)._value.get() == 4096
    assert stream_redis_publish_subscribers.labels(device_id=device_id)._value.get() == 2


@pytest.mark.asyncio
async def test_viewer_send_counter_means_asgi_send_completed():
    device_id = f"stream-viewer-{uuid.uuid4()}"
    manager = MagicMock()
    manager.send_to_device = AsyncMock(return_value=True)
    bridge = VideoStreamBridge(manager)
    viewer = AsyncMock()
    viewer.send_bytes = AsyncMock()
    await bridge.register_viewer(device_id, viewer, "session-1")
    try:
        await bridge.receive_frame(device_id, _wire_frame())
        # The bridge's sender is asynchronous; wait until its bounded queue is drained.
        for _ in range(100):
            if viewer.send_bytes.await_count:
                break
            await asyncio.sleep(0.01)
        assert viewer.send_bytes.await_count == 1
        from backend.metrics import (
            stream_active_viewers,
            stream_viewer_send_bytes_total,
            stream_viewer_send_frames_total,
        )

        assert stream_active_viewers.labels(device_id=device_id)._value.get() == 1
        assert stream_viewer_send_frames_total.labels(device_id=device_id)._value.get() == 1
        assert stream_viewer_send_bytes_total.labels(device_id=device_id)._value.get() == len(_wire_frame())
    finally:
        await bridge.unregister_viewer(device_id, "session-1")
        assert stream_active_viewers.labels(device_id=device_id)._value.get() == 0
        await bridge.close()


@pytest.mark.asyncio
async def test_server_queue_drop_metric_has_bounded_stage_and_reason_labels():
    device_id = f"stream-queue-{uuid.uuid4()}"
    queue = VideoStreamQueue(device_id, queue_stage="viewer")
    queue.MAX_BYTES = 8
    assert not await queue.put(VideoFrame(b"x" * 9, device_id))

    assert (
        stream_server_queue_drops_total.labels(
            device_id=device_id,
            queue_stage="viewer",
            reason="oversize",
        )._value.get()
        == 1
    )


def test_metric_failure_is_best_effort_on_video_publish_path(monkeypatch):
    broken_counter = MagicMock()
    broken_counter.labels.side_effect = RuntimeError("metrics unavailable")
    monkeypatch.setattr(stream_observability, "stream_redis_publish_calls_total", broken_counter)

    # This helper runs after Redis publish; a metrics outage must not terminate
    # the bridge's publish task or convert a successful send into a failure.
    stream_observability.record_redis_publish("stream-metric-failure", 1024, 1)

    broken_counter.labels.assert_called_once_with(device_id="stream-metric-failure")


@pytest.mark.asyncio
async def test_queue_drop_survives_metrics_failure(monkeypatch):
    broken_counter = MagicMock()
    broken_counter.labels.side_effect = RuntimeError("metrics unavailable")
    monkeypatch.setattr(stream_observability, "stream_server_queue_drops_total", broken_counter)
    queue = VideoStreamQueue("stream-metric-failure", queue_stage="viewer")
    queue.MAX_BYTES = 8

    assert not await queue.put(VideoFrame(b"x" * 9, queue.device_id))
    assert queue.frames_dropped == 1
    broken_counter.labels.assert_called_once_with(
        device_id=queue.device_id,
        queue_stage="viewer",
        reason="oversize",
    )
