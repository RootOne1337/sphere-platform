"""Multiple browser sessions must share capture without stealing its frames."""

import asyncio
from unittest.mock import patch

import pytest

from tests.production.test_stream_video_routing import FRAME, Viewer, until, workers


@pytest.mark.parametrize("closed_session", ["first", "second"])
async def test_same_worker_viewers_receive_frames_and_close_independently(world, closed_session):
    async with workers(world) as (bridges, commands):
        bridge = bridges[1]
        device = str(world.dev_a.id)
        viewers = {name: Viewer("") for name in ("first", "second")}
        for name, viewer in viewers.items():
            await bridge.register_viewer(device, viewer, name)

        await bridges[0].handle_agent_frame(device, FRAME)
        for viewer in viewers.values():
            assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME
        commands.clear()
        await bridge.unregister_viewer(device, closed_session)
        await asyncio.sleep(2.2)
        assert not any(c["type"] == "stop_stream" for c in commands)
        survivor = next(name for name in viewers if name != closed_session)
        await bridges[0].handle_agent_frame(device, FRAME + b"survivor")
        assert await asyncio.wait_for(viewers[survivor].frames.get(), 2) == FRAME + b"survivor"
        assert viewers[closed_session].frames.empty()
        await bridge.unregister_viewer(device, survivor)
        await until(lambda: any(c["type"] == "stop_stream" for c in commands))


async def test_later_slow_viewer_does_not_steal_fast_viewers_stream(world):
    async with workers(world) as (bridges, commands):
        bridge = bridges[1]
        device = str(world.dev_a.id)
        fast, slow = Viewer(""), Viewer("")
        release = asyncio.Event()

        async def blocked_send(data):
            await release.wait()

        slow.send_bytes = blocked_send
        await bridge.register_viewer(device, fast, "fast")
        await bridge.register_viewer(device, slow, "slow")
        try:
            await bridges[0].handle_agent_frame(device, FRAME)
            assert await asyncio.wait_for(fast.frames.get(), 2) == FRAME
            for _ in range(150):
                await bridge.receive_frame(device, FRAME)
            slow_queue = bridge._viewers[device]["slow"].queue
            assert slow_queue.size <= slow_queue.MAX_SIZE
            assert slow_queue._bytes <= slow_queue.MAX_BYTES
            assert slow_queue.frames_dropped > 0
            await bridge.send_control(device, {"type": "request_keyframe"})
            await until(lambda: any(c["type"] == "request_keyframe" for c in commands))
        finally:
            release.set()


async def test_failed_second_start_preserves_existing_viewer(world):
    async with workers(world) as (bridges, _):
        bridge = bridges[1]
        device = str(world.dev_a.id)
        viewer = Viewer("")
        await bridge.register_viewer(device, viewer, "existing")
        with patch.object(bridge, "send_control", return_value=False):
            with pytest.raises(ConnectionError):
                await bridge.register_viewer(device, Viewer(""), "rejected")
        # The WS handler's late finally must also be harmless.
        await bridge.unregister_viewer(device, "rejected")
        await bridges[0].handle_agent_frame(device, FRAME)
        assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME
        assert list(bridge._viewers[device]) == ["existing"]


async def test_failed_browser_write_removes_only_that_session(world):
    async with workers(world) as (bridges, _):
        bridge = bridges[1]
        device = str(world.dev_a.id)
        failed, healthy = Viewer(""), Viewer("")

        async def broken_send(data):
            raise ConnectionError("browser connection lost")

        failed.send_bytes = broken_send
        await bridge.register_viewer(device, healthy, "healthy")
        await bridge.register_viewer(device, failed, "failed")
        await bridges[0].handle_agent_frame(device, FRAME)
        assert await asyncio.wait_for(healthy.frames.get(), 2) == FRAME
        await until(lambda: failed.closed is not None)
        assert failed.closed == (1013, "stream_send_failed")
        await bridge.unregister_viewer(device, "failed")
        await bridges[0].handle_agent_frame(device, FRAME + b"still-live")
        assert await asyncio.wait_for(healthy.frames.get(), 2) == FRAME + b"still-live"


async def test_last_close_racing_new_viewer_keeps_subscription(world):
    async with workers(world) as (bridges, _):
        bridge = bridges[1]
        device, other = str(world.dev_a.id), str(world.dev_a2.id)
        await bridge.register_viewer(device, Viewer(""), "old")
        entered, release = asyncio.Event(), asyncio.Event()
        unsubscribe = bridge.transport.unsubscribe

        async def delayed_unsubscribe(device_id):
            entered.set()
            await release.wait()
            await unsubscribe(device_id)

        new, unrelated = Viewer(""), Viewer("")
        with patch.object(bridge.transport, "unsubscribe", side_effect=delayed_unsubscribe):
            closing = asyncio.create_task(bridge.unregister_viewer(device, "old"))
            opening = None
            try:
                await asyncio.wait_for(entered.wait(), 2)
                opening = asyncio.create_task(bridge.register_viewer(device, new, "new"))
                # Network waits for one device must not hold up another device.
                await asyncio.wait_for(bridge.register_viewer(other, unrelated, "other"), 2)
                release.set()
                await asyncio.wait_for(asyncio.gather(closing, opening), 3)
            finally:
                release.set()
                for task in (closing, opening):
                    if task:
                        task.cancel()
                await asyncio.gather(*[t for t in (closing, opening) if t], return_exceptions=True)
        await bridges[0].handle_agent_frame(device, FRAME)
        assert await asyncio.wait_for(new.frames.get(), 2) == FRAME
        await bridge.unregister_viewer(device, "old")
        assert bridge.is_streaming(device)


async def test_concurrent_viewers_share_one_subscription_and_recover_together(world):
    async with workers(world) as (bridges, commands):
        bridge = bridges[1]
        device = str(world.dev_a.id)
        viewers = [Viewer("") for _ in range(6)]
        await asyncio.gather(*(bridge.register_viewer(device, v, str(i)) for i, v in enumerate(viewers)))
        channel = "sphere:stream:video:" + device
        assert dict(await world.redis.pubsub_numsub(channel))[channel] == 1
        commands.clear()
        await bridge.transport.redis.connection_pool.disconnect()
        await until(lambda: any(c["type"] == "viewer_connected" for c in commands), 8)
        await bridges[0].handle_agent_frame(device, FRAME)
        for viewer in viewers:
            assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME
        tasks = [v.task for v in bridge._viewers[device].values()]
        await bridge.close()
        assert all(t.done() for t in tasks)
        assert not bridge.is_streaming(device)
        assert not bridge._device_locks
        assert dict(await world.redis.pubsub_numsub(channel))[channel] == 0
        with pytest.raises(ConnectionError):
            await bridge.register_viewer(device, Viewer(""), "after-close")
