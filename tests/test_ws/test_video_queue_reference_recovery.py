"""A bounded queue must not send dependants of a picture it has discarded."""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from backend.websocket.frames import VideoFrame
from backend.websocket.stream_bridge import VideoStreamBridge
from backend.websocket.video_queue import VideoStreamQueue


def picture(kind: int, marker: int = 0, *, leading_sei: bool = False) -> VideoFrame:
    payload = (b"\x00\x00\x01\x06metadata" if leading_sei else b"")
    payload += b"\x00\x00\x01" + bytes([0x60 | kind, marker])
    header = bytes([1, int(kind == 5)]) + bytes(8) + len(payload).to_bytes(4, "big")
    return VideoFrame(header + payload, "device")


@pytest.mark.parametrize("stage", ["viewer", "agent_to_redis"])
async def test_overflow_does_not_forward_dependants_of_a_discarded_picture(stage):
    queue = VideoStreamQueue("device", queue_stage=stage)
    queue.MAX_SIZE = 3
    # The encoder uses a reference chain: IDR0 -> P1 -> P2 -> P3 -> P4.
    for frame in [picture(5, 0), picture(1, 1), picture(1, 2)]:
        assert await queue.put(frame)
    assert not await queue.put(picture(1, 3))
    assert not await queue.put(picture(1, 4))
    assert await queue.get() is None
    # Only a new independently decodable picture can reopen this chain.
    idr, delta = picture(5, 5), picture(1, 6)
    assert await queue.put(idr)
    assert await queue.put(delta)
    assert await queue.get() is idr
    assert await queue.get() is delta


async def test_stale_picture_found_on_read_invalidates_its_fresh_dependant(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("backend.websocket.video_queue.time.monotonic", lambda: clock[0])
    queue = VideoStreamQueue("device")
    first, dependant = picture(1, 1), picture(1, 2)
    first.timestamp, dependant.timestamp = 100.0, 100.1
    await queue.put(first)
    await queue.put(dependant)
    # No additional put(): the consumer itself stalled for 250 ms.
    clock[0] = 100.25
    assert await queue.get() is None
    assert not await queue.put(picture(1, 3))


async def test_stale_idr_is_not_exempt_from_the_latency_budget(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("backend.websocket.video_queue.time.monotonic", lambda: clock[0])
    queue = VideoStreamQueue("device")
    old = picture(5)
    old.timestamp = 100.0
    await queue.put(old)
    clock[0] = 110.0
    assert await queue.get() is None


async def test_leading_sei_does_not_hide_a_dependent_picture_after_a_gap():
    queue = VideoStreamQueue("device")
    queue.MAX_BYTES = 50
    oversized = VideoFrame(b"\x00\x00\x01\x41" + bytes(60), "device")
    assert not await queue.put(oversized)
    assert not await queue.put(picture(1, leading_sei=True))
    assert await queue.put(picture(5, leading_sei=True))


async def test_parameter_sets_can_pass_while_waiting_for_a_new_idr():
    queue = VideoStreamQueue("device")
    queue.MAX_SIZE = 1
    await queue.put(picture(1, 1))
    await queue.put(picture(1, 2))
    sps, pps = picture(7), picture(8)
    assert await queue.put(sps)
    assert await queue.get() is sps
    assert await queue.put(pps)
    assert await queue.get() is pps
    assert not await queue.put(picture(1, 3))
    assert await queue.put(picture(5, 4))


async def test_recovery_request_is_bounded_and_cannot_break_queue(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("backend.websocket.video_queue.time.monotonic", lambda: clock[0])
    recover = Mock(side_effect=RuntimeError("control unavailable"))
    queue = VideoStreamQueue("device", on_recovery=recover)
    queue.MAX_SIZE = 1
    await queue.put(picture(1, 1))
    assert not await queue.put(picture(1, 2))
    for _ in range(20):
        assert not await queue.put(picture(1, 3))
    assert recover.call_count == 1
    clock[0] += 1.1
    assert not await queue.put(picture(1, 4))
    assert recover.call_count == 2


async def test_one_congested_viewer_does_not_discard_another_viewers_chain():
    slow, healthy = VideoStreamQueue("device"), VideoStreamQueue("device")
    slow.MAX_SIZE = 1
    for frame in [picture(5), picture(1, 1), picture(1, 2)]:
        await slow.put(frame)
        assert await healthy.put(frame)
        assert await healthy.get() is frame
    assert await slow.get() is None


async def test_bridge_coalesces_keyframe_requests_and_owns_shutdown():
    manager = Mock(send_to_device=AsyncMock(return_value=True))
    bridge = VideoStreamBridge(manager)
    try:
        for _ in range(20):
            bridge._schedule_keyframe("device")
        await asyncio.sleep(0)
        manager.send_to_device.assert_awaited_once_with("device", {"type": "request_keyframe"})
        # A second viewer loses a reference while the first request is cooling.
        bridge._schedule_keyframe("device")
        await asyncio.sleep(0)
        assert manager.send_to_device.await_count == 1
        assert len(bridge._keyframe_tasks) == 1
    finally:
        await bridge.close()
    assert not bridge._keyframe_tasks


async def test_uncertain_publication_fences_the_chain_and_schedules_recovery():
    recover = Mock()
    queue = VideoStreamQueue("device", queue_stage="agent_to_redis", on_recovery=recover)
    await queue.put(picture(1, 1))
    await queue.invalidate()
    assert recover.call_count == 1
    assert await queue.get() is None
    assert not await queue.put(picture(1, 2))
    assert await queue.put(picture(5, 3))


async def test_bridge_publication_failure_fences_queue_and_requests_native_keyframe():
    manager = Mock(send_to_device=AsyncMock(return_value=True))
    bridge = VideoStreamBridge(manager)
    bridge.transport = Mock(publish=AsyncMock(side_effect=TimeoutError), close=AsyncMock())
    try:
        await bridge.handle_agent_frame("device", picture(1, 1).data)
        async with asyncio.timeout(2):
            while not manager.send_to_device.await_count:
                await asyncio.sleep(.01)
        manager.send_to_device.assert_awaited_once_with("device", {"type": "request_keyframe"})
        queue = bridge._publish_queues["device"]
        assert not await queue.put(picture(1, 2))
        assert await queue.get() is None
    finally:
        await bridge.close()
