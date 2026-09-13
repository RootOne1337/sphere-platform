"""Real Redis, separate worker registries and the actual browser WS handler."""

import asyncio
import importlib
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import WebSocketDisconnect
from redis.asyncio import Redis

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.pubsub_router import PubSubPublisher, PubSubRouter
from backend.websocket.stream_bridge import init_stream_bridge

FRAME = b"\x00" * 14 + b"\x00\x00\x00\x01\x65\xff\xfe\x80\x00"


class Viewer:
    def __init__(self, token):
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait({"token": token})
        self.frames = asyncio.Queue()
        self.messages = []
        self.closed = None

    async def accept(self):
        pass

    async def receive_json(self):
        item = await self.incoming.get()
        if item is None:
            raise WebSocketDisconnect()
        return item

    async def send_bytes(self, data):
        self.frames.put_nowait(data)

    async def send_json(self, data):
        self.messages.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)
        self.incoming.put_nowait(None)


async def until(predicate, timeout=4):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@asynccontextmanager
async def workers(world):
    # Match production socket settings: idle Pub/Sub must not inherit the
    # request timeout as a reason to restart an otherwise healthy capture.
    binary = Redis.from_url(
        os.environ["REDIS_URL"], decode_responses=False,
        socket_timeout=5.0, socket_connect_timeout=5.0,
        retry_on_timeout=True, health_check_interval=30,
    )
    owner = ConnectionManager()
    commands = []

    async def receive(command):
        commands.append(command)

    device = str(world.dev_a.id)
    await owner.connect(AsyncMock(send_json=receive), device, "android", str(world.org_a.id))
    command_router = PubSubRouter(world.redis, owner)
    await command_router.start()
    await command_router.subscribe_device(device, str(world.org_a.id))
    async with asyncio.timeout(3):
        while not dict(await world.redis.pubsub_numsub(f"sphere:agent:cmd:{device}"))[f"sphere:agent:cmd:{device}"]:
            await asyncio.sleep(0.01)
    # The existing command router sleeps for up to one second before its first
    # subscription. Warm it via an actual delivery before measuring contention.
    await PubSubPublisher(world.redis).send_command_live(device, {"type": "audit_ready"})
    await until(lambda: any(c["type"] == "audit_ready" for c in commands))
    commands.clear()
    bridges = []
    with (
        patch("backend.database.redis_client.redis", world.redis),
        patch("backend.database.redis_client.redis_binary", binary),
        patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=PubSubPublisher(world.redis)),
    ):
        for manager in (owner, ConnectionManager(), ConnectionManager()):
            bridges.append(init_stream_bridge(manager))
        try:
            yield bridges, commands
        finally:
            for bridge in bridges:
                if hasattr(bridge, "close"):
                    await bridge.close()
                else:  # Baseline reproduction must also release its background tasks.
                    tasks = [*bridge._viewer_tasks.values(), *bridge._delayed_stop_tasks.values()]
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            await command_router.stop()
            await binary.aclose()


@pytest.mark.parametrize("viewer_worker", [0, 1])
async def test_binary_frame_reaches_viewer_once_on_any_worker(world, viewer_worker):
    async with workers(world) as (bridges, commands):
        viewer = Viewer("")
        device = str(world.dev_a.id)
        await bridges[viewer_worker].register_viewer(device, viewer, "viewer-a")
        await bridges[0].handle_agent_frame(device, FRAME)
        assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME
        await asyncio.sleep(0.1)
        assert viewer.frames.empty(), "local and Redis paths must not duplicate a frame"
        await until(lambda: any(c["type"] == "start_stream" for c in commands))


async def test_no_frame_crosses_device_channel(world):
    async with workers(world) as (bridges, _):
        viewer = Viewer("")
        await bridges[1].register_viewer(str(world.dev_b.id), viewer, "other-device")
        await bridges[0].handle_agent_frame(str(world.dev_a.id), FRAME)
        await asyncio.sleep(0.15)
        assert viewer.frames.empty()


async def test_agent_reconnect_resumes_viewer_on_another_worker(world):
    async with workers(world) as (bridges, commands):
        device = str(world.dev_a.id)
        await bridges[1].register_viewer(device, Viewer(""), "viewer-a")
        await asyncio.sleep(0.1)
        commands.clear()
        await bridges[0].resume_stream_for_device(device)
        await until(lambda: any(c["type"] == "viewer_connected" for c in commands))
        assert any(c["type"] == "start_stream" for c in commands)


async def test_closing_one_worker_does_not_stop_other_viewer(world):
    async with workers(world) as (bridges, commands):
        device = str(world.dev_a.id)
        await bridges[0].register_viewer(device, Viewer(""), "a")
        await bridges[1].register_viewer(device, Viewer(""), "b")
        commands.clear()
        await bridges[0].unregister_viewer(device)
        await asyncio.sleep(2.2)
        assert not any(c["type"] == "stop_stream" for c in commands)
        await bridges[1].unregister_viewer(device)
        await until(lambda: any(c["type"] == "stop_stream" for c in commands))


async def test_old_browser_finally_cannot_remove_replacement(world):
    module = importlib.import_module("backend.api.ws.stream.router")
    token = world.auth(world.users["org_admin"])["Authorization"].split()[1]
    old, new = Viewer(token), Viewer(token)
    device = str(world.dev_a.id)
    async with workers(world) as (bridges, _):
        bridge = bridges[0]
        with patch.object(module, "AsyncSessionLocal", world.sessions), patch.object(module, "get_stream_bridge", return_value=bridge):
            old_task = asyncio.create_task(module.stream_viewer_ws(old, device))
            new_task = None
            try:
                await until(lambda: bridge._viewer_sockets.get(device) is old)
                new_task = asyncio.create_task(module.stream_viewer_ws(new, device))
                await until(lambda: bridge._viewer_sockets.get(device) is new)
                old.incoming.put_nowait(None)
                await asyncio.wait_for(old_task, 3)
                assert bridge._viewer_sockets.get(device) is new
                await bridge.handle_agent_frame(device, FRAME)
                assert await asyncio.wait_for(new.frames.get(), 2) == FRAME
            finally:
                for task in (old_task, new_task):
                    if task:
                        task.cancel()
                await asyncio.gather(*[t for t in (old_task, new_task) if t], return_exceptions=True)


async def test_redis_connection_loss_restores_frames_and_capture(world):
    async with workers(world) as (bridges, commands):
        device = str(world.dev_a.id)
        viewer = Viewer("")
        await bridges[1].register_viewer(device, viewer, "recover")
        await bridges[0].handle_agent_frame(device, FRAME)
        assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME
        await until(lambda: any(c["type"] == "start_stream" for c in commands))
        commands.clear()
        # Only this fixture's binary connections; command Redis and other tests
        # keep their own pools. Real socket loss, no mocked subscription methods.
        await bridges[1].transport.redis.connection_pool.disconnect()
        await until(lambda: any(c["type"] == "viewer_connected" for c in commands), 8)
        assert any(c["type"] == "start_stream" for c in commands)
        await bridges[0].handle_agent_frame(device, FRAME + b"recovered")
        assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME + b"recovered"


async def test_static_screen_does_not_restart_capture_after_redis_read_timeout(world):
    async with workers(world) as (bridges, commands):
        device = str(world.dev_a.id)
        viewer = Viewer("")
        await bridges[1].register_viewer(device, viewer, "static-screen")
        await bridges[0].handle_agent_frame(device, FRAME)
        assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME
        await until(lambda: any(c["type"] == "start_stream" for c in commands))
        commands.clear()
        # Android ImageReader emits no new frame on an unchanged display.
        # Wait past the actual production socket timeout with healthy Redis.
        await asyncio.sleep(6.5)
        assert not commands, "idle video must not trigger start/viewer_connected/stop"
        await bridges[0].handle_agent_frame(device, FRAME + b"motion")
        assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME + b"motion"


async def test_abandoned_viewer_worker_stops_capture(world):
    async with workers(world) as (bridges, commands):
        device = str(world.dev_a.id)
        await bridges[1].register_viewer(device, Viewer(""), "crashed")
        await until(lambda: any(c["type"] == "start_stream" for c in commands))
        commands.clear()
        # Lose the subscription without unregister/finally, as on worker death.
        await bridges[1].transport.close()
        async with asyncio.timeout(5):
            while not any(c["type"] == "stop_stream" for c in commands):
                await bridges[0].handle_agent_frame(device, FRAME)
                await asyncio.sleep(0.05)


async def test_slow_video_redis_does_not_block_agent_ingestion(world):
    async with workers(world) as (bridges, commands):
        device = str(world.dev_a.id)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def stalled(*args):
            entered.set()
            await release.wait()
            return 1

        with patch.object(bridges[0].transport, "publish", side_effect=stalled):
            await bridges[0].handle_agent_frame(device, FRAME)
            await entered.wait()
            async with asyncio.timeout(1):
                for _ in range(500):
                    await bridges[0].handle_agent_frame(device, FRAME)
                await bridges[1].send_control(device, {"type": "request_keyframe"})
                await until(lambda: any(c["type"] == "request_keyframe" for c in commands))
            assert bridges[0]._publish_queues[device].size <= 50
            release.set()


async def test_slow_browser_does_not_block_other_device_or_commands(world):
    async with workers(world) as (bridges, commands):
        device, other = str(world.dev_a.id), str(world.dev_a2.id)
        stuck = asyncio.Event()
        blocked = Viewer("")
        async def never_send(data):
            await stuck.wait()

        blocked.send_bytes = never_send
        fast = Viewer("")
        await bridges[1].register_viewer(device, blocked, "slow")
        await bridges[1].register_viewer(other, fast, "fast")
        for _ in range(150):
            await bridges[0].handle_agent_frame(device, FRAME)
        await bridges[0].handle_agent_frame(other, FRAME + b"other")
        assert await asyncio.wait_for(fast.frames.get(), 2) == FRAME + b"other"
        await bridges[1].send_control(device, {"type": "request_keyframe"})
        await until(lambda: any(c["type"] == "request_keyframe" for c in commands))
        assert bridges[1]._queues[device].size <= 50
        stuck.set()


@pytest.mark.parametrize("role,expected", [("org_admin", True), ("viewer", False)])
async def test_browser_controls_route_to_owner_with_permissions(world, role, expected):
    module = importlib.import_module("backend.api.ws.stream.router")
    device = str(world.dev_a.id)
    token = world.auth(world.users[role])["Authorization"].split()[1]
    viewer = Viewer(token)
    async with workers(world) as (bridges, commands):
        with patch.object(module, "AsyncSessionLocal", world.sessions), patch.object(module, "get_stream_bridge", return_value=bridges[1]):
            task = asyncio.create_task(module.stream_viewer_ws(viewer, device))
            try:
                await until(lambda: any(c["type"] == "viewer_connected" for c in commands))
                viewer.incoming.put_nowait({"type": "click", "x": 123, "y": 456})
                if expected:
                    await until(lambda: any(c["type"] == "touch_tap" for c in commands))
                    tap = next(c for c in commands if c["type"] == "touch_tap")
                    assert (tap["x"], tap["y"]) == (123, 456)
                else:
                    await until(lambda: any(m.get("error") == "stream_control_denied" for m in viewer.messages))
                    assert not any(c["type"] == "touch_tap" for c in commands)
            finally:
                viewer.incoming.put_nowait(None)
                await asyncio.wait_for(task, 3)
