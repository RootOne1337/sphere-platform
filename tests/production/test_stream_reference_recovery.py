"""Real Redis separates an Android owner from slow/healthy viewer workers."""
import asyncio

from tests.production.test_stream_video_routing import Viewer, until, workers
from tests.test_ws.test_video_queue_reference_recovery import picture


async def test_slow_viewer_resumes_at_fresh_idr_without_corrupting_healthy_viewer(world):
    async with workers(world) as (bridges, commands):
        device = str(world.dev_a.id)
        slow, healthy = Viewer(""), Viewer("")
        blocked, entered = asyncio.Event(), asyncio.Event()
        original_send = slow.send_bytes

        async def stall_first(data):
            if not entered.is_set():
                entered.set()
                await blocked.wait()
            await original_send(data)

        slow.send_bytes = stall_first
        await bridges[1].register_viewer(device, slow, "slow")
        await bridges[2].register_viewer(device, healthy, "healthy")
        slow_queue = bridges[1]._viewers[device]["slow"].queue
        slow_queue.MAX_SIZE = 2
        first = picture(5, 0).data
        await bridges[0].handle_agent_frame(device, first)
        assert await asyncio.wait_for(healthy.frames.get(), 2) == first
        await asyncio.wait_for(entered.wait(), 2)
        for marker in range(1, 5):
            delta = picture(1, marker).data
            await bridges[0].handle_agent_frame(device, delta)
            assert await asyncio.wait_for(healthy.frames.get(), 2) == delta
        await until(lambda: any(c["type"] == "request_keyframe" for c in commands))
        blocked.set()
        assert await asyncio.wait_for(slow.frames.get(), 2) == first
        await asyncio.sleep(.05)
        assert slow.frames.empty(), "P1-P4 depend on discarded references"
        fresh = picture(5, 5).data
        await bridges[0].handle_agent_frame(device, fresh)
        assert await asyncio.wait_for(slow.frames.get(), 2) == fresh
        assert await asyncio.wait_for(healthy.frames.get(), 2) == fresh
        delta = picture(1, 6).data
        await bridges[0].handle_agent_frame(device, delta)
        assert await asyncio.wait_for(slow.frames.get(), 2) == delta
        assert await asyncio.wait_for(healthy.frames.get(), 2) == delta
