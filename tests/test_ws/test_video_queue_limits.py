"""A stalled viewer cannot retain an unbounded sequence of keyframes."""

from backend.websocket.frames import VideoFrame
from backend.websocket.video_queue import VideoStreamQueue


async def test_repeated_critical_frames_obey_queue_bound():
    queue = VideoStreamQueue("stalled-viewer")
    for _ in range(queue.MAX_SIZE * 4):
        await queue.put(VideoFrame(b"\x00\x00\x00\x01\x65" + b"\xff" * 100, "stalled-viewer"))
    assert queue.size <= queue.MAX_SIZE
    assert 0 <= queue.drop_ratio <= 1


async def test_large_frames_obey_byte_bound_and_oversize_is_rejected():
    queue = VideoStreamQueue("bounded")
    data = b"\x00\x00\x00\x01\x65" + b"\xff" * (1024 * 1024)
    for _ in range(20):
        await queue.put(VideoFrame(data, "bounded"))
    assert queue._bytes <= queue.MAX_BYTES
    assert not await queue.put(VideoFrame(data * 9, "bounded"))
    consumed = []
    while queue.size:
        consumed.append(await queue.get())
    assert sum(len(frame.data) for frame in consumed) <= queue.MAX_BYTES
    assert queue._bytes == 0
    assert not queue._ready.is_set()
