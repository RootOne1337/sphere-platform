"""Real Redis, separate worker registries and the actual browser WS handler."""

import asyncio
import importlib
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy import update

from backend.models.device import Device
from backend.models.user import User
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
    # The isolation/backpressure cases also view these devices. Give each a
    # real command receiver; an offline capture start must now be rejected.
    for other in (world.dev_a2, world.dev_b):
        await owner.connect(AsyncMock(send_json=receive), str(other.id), "android", str(other.org_id))
        await command_router.subscribe_device(str(other.id), str(other.org_id))
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
                await bridge.close()
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


async def test_browser_handlers_share_frames_and_close_only_their_own_session(world):
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
                await until(lambda: len(bridge._viewers.get(device, {})) == 1)
                new_task = asyncio.create_task(module.stream_viewer_ws(new, device))
                await until(lambda: len(bridge._viewers.get(device, {})) == 2)
                await bridge.handle_agent_frame(device, FRAME)
                for viewer in (old, new):
                    assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME
                old.incoming.put_nowait(None)
                await asyncio.wait_for(old_task, 3)
                assert [v.socket for v in bridge._viewers[device].values()] == [new]
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
        assert bridges[1]._viewers[device]["slow"].queue.size <= 50
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


@pytest.mark.parametrize("malformed,reason", [
    ([], "invalid_message"), ({"type": []}, "invalid_message"),
    ({"type": "click"}, "invalid_parameter"), ({"type": "click", "x": True, "y": 20}, "invalid_parameter"),
    ({"type": "click", "x": "private-coordinate", "y": 20}, "invalid_parameter"),
    ({"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 60_001}, "invalid_parameter"),
    ({"type": "text", "text": {"private": "value"}}, "invalid_parameter"),
    ({"type": "touch_down", "x": 1, "y": 2}, "unsupported_message"),
])
async def test_malformed_input_never_dispatches_and_keeps_video_and_later_input_alive(world, malformed, reason):
    module = importlib.import_module("backend.api.ws.stream.router")
    device = str(world.dev_a.id)
    viewer = Viewer(world.auth(world.users["org_admin"])["Authorization"].split()[1])
    async with workers(world) as (bridges, commands):
        with patch.object(module, "AsyncSessionLocal", world.sessions), patch.object(module, "get_stream_bridge", return_value=bridges[1]):
            task = asyncio.create_task(module.stream_viewer_ws(viewer, device))
            try:
                await until(lambda: any(c["type"] == "viewer_connected" for c in commands))
                owner = next(c for c in commands if c["type"] == "viewer_connected")
                session_metadata = {
                    "type": "stream_session", "schema_version": 1,
                    "session_id": owner["session_id"], "history_enabled": True,
                    "report_interval_seconds": 10,
                }
                assert viewer.messages == [session_metadata]
                viewer.incoming.put_nowait(malformed)
                # Session admission precedes input. Wait for the error itself;
                # the metadata alone must not satisfy this regression check.
                await until(lambda: any(m.get("type") == "error" for m in viewer.messages))
                assert viewer.messages == [session_metadata, {
                    "type": "error", "error": "stream_input_invalid", "reason": reason,
                }]
                assert not any(c["type"] in {"touch_tap", "touch_swipe", "keyevent", "text"} for c in commands)
                assert viewer.closed is None
                await bridges[0].handle_agent_frame(device, FRAME)
                assert await asyncio.wait_for(viewer.frames.get(), 2) == FRAME
                viewer.incoming.put_nowait({"type": "click", "x": 123, "y": 456, "session_id": "spoofed"})
                await until(lambda: any(c["type"] == "touch_tap" for c in commands))
                tap = next(c for c in commands if c["type"] == "touch_tap")
                assert tap == {"type": "touch_tap", "x": 123, "y": 456, "session_id": owner["session_id"]}
            finally:
                viewer.incoming.put_nowait(None)
                await asyncio.wait_for(task, 3)
            assert device not in bridges[1]._viewers


@pytest.mark.parametrize("message,command_type", [
    ({"type": "click", "x": 123, "y": 456}, "touch_tap"),
    ({"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4}, "touch_swipe"),
    ({"type": "keyevent", "code": 3}, "keyevent"),
    ({"type": "text", "text": "test"}, "text"),
])
@pytest.mark.parametrize("use_runtime_role", [False, True], ids=["owner-db", "restricted-rls-db"])
async def test_open_viewer_rechecks_control_after_database_role_change(world, runtime_db, message, command_type, use_runtime_role):
    module = importlib.import_module("backend.api.ws.stream.router")
    user = world.users["org_admin"]
    device = str(world.dev_a.id)
    viewer = Viewer(world.auth(user)["Authorization"].split()[1])
    async with workers(world) as (bridges, commands):
        sessions = runtime_db.sessions if use_runtime_role else world.sessions
        with patch.object(module, "AsyncSessionLocal", sessions), patch.object(module, "get_stream_bridge", return_value=bridges[1]):
            task = asyncio.create_task(module.stream_viewer_ws(viewer, device))
            try:
                await until(lambda: any(c["type"] == "viewer_connected" for c in commands))
                viewer.incoming.put_nowait(message)
                await until(lambda: any(c["type"] == command_type for c in commands))
                async with world.sessions() as db:
                    await db.execute(update(User).where(User.id == user.id).values(role="viewer"))
                    await db.commit()
                viewer.incoming.put_nowait(message)
                await until(lambda: any(m.get("error") == "stream_control_denied" for m in viewer.messages)
                            or sum(c["type"] == command_type for c in commands) > 1)
                assert sum(c["type"] == command_type for c in commands) == 1
                assert any(m.get("error") == "stream_control_denied" for m in viewer.messages)
                # The same socket may still view pictures; an explicit fresh
                # server grant can restore control without trusting the old JWT role.
                assert viewer.closed is None
                async with world.sessions() as db:
                    await db.execute(update(User).where(User.id == user.id).values(role="org_admin"))
                    await db.commit()
                viewer.incoming.put_nowait(message)
                await until(lambda: sum(c["type"] == command_type for c in commands) == 2)
            finally:
                viewer.incoming.put_nowait(None)
                await asyncio.wait_for(task, 3)


@pytest.mark.parametrize("change,expected_code", [
    ("inactive", 4001), ("user_moved", 4001), ("revoked_token", 4001),
    ("device_moved", 4004), ("expired_token", 4001), ("read_permission_removed", 4003),
])
async def test_open_viewer_cannot_control_after_identity_or_ownership_revocation(world, monkeypatch, change, expected_code):
    from backend.core.security import decode_access_token
    from backend.services.cache_service import CacheService

    module = importlib.import_module("backend.api.ws.stream.router")
    user = world.users["org_admin"]
    device = str(world.dev_a.id)
    token = world.auth(user)["Authorization"].split()[1]
    viewer = Viewer(token)
    async with workers(world) as (bridges, commands):
        with patch.object(module, "AsyncSessionLocal", world.sessions), patch.object(module, "get_stream_bridge", return_value=bridges[1]):
            task = asyncio.create_task(module.stream_viewer_ws(viewer, device))
            try:
                await until(lambda: any(c["type"] == "viewer_connected" for c in commands))
                if change == "revoked_token":
                    await CacheService().blacklist_token(decode_access_token(token)["jti"], 60)
                elif change == "expired_token":
                    # Advance only the verifier clock after the real JWT was
                    # admitted. Keep its actual signature/claims/Redis checks.
                    class ExpiredClock(datetime):
                        @classmethod
                        def now(cls, tz=None):
                            return datetime.now(tz) + timedelta(hours=2)

                    monkeypatch.setattr("jwt.api_jwt.datetime", ExpiredClock)
                else:
                    async with world.sessions() as db:
                        if change == "device_moved":
                            await db.execute(update(Device).where(Device.id == world.dev_a.id).values(org_id=world.org_b.id))
                        else:
                            values = {
                                "inactive": {"is_active": False},
                                "read_permission_removed": {"role": "api_user"},
                                "user_moved": {"org_id": world.org_b.id},
                            }[change]
                            await db.execute(update(User).where(User.id == user.id).values(**values))
                        await db.commit()
                viewer.incoming.put_nowait({"type": "click", "x": 1, "y": 2})
                await until(lambda: viewer.closed is not None or any(c["type"] == "touch_tap" for c in commands))
                assert not any(c["type"] == "touch_tap" for c in commands)
                assert viewer.closed[0] == expected_code
                await asyncio.wait_for(task, 3)
                assert device not in bridges[1]._viewers
            finally:
                viewer.incoming.put_nowait(None)
                await asyncio.wait_for(task, 3)


async def test_passive_viewer_loses_video_access_when_account_is_disabled(world, monkeypatch):
    module = importlib.import_module("backend.api.ws.stream.router")
    monkeypatch.setattr(module, "VIEWER_AUTH_RECHECK_SECONDS", 0.05, raising=False)
    user = world.users["org_admin"]
    device = str(world.dev_a.id)
    viewer = Viewer(world.auth(user)["Authorization"].split()[1])

    async def unacknowledged_close(code=1000, reason=""):
        viewer.closed = (code, reason)

    # Closing ASGI output alone need not unblock an uncooperative peer's
    # pending receive. The route must retire both its sender and receiver.
    viewer.close = unacknowledged_close
    async with workers(world) as (bridges, commands):
        with patch.object(module, "AsyncSessionLocal", world.sessions), patch.object(module, "get_stream_bridge", return_value=bridges[1]):
            task = asyncio.create_task(module.stream_viewer_ws(viewer, device))
            try:
                await until(lambda: any(c["type"] == "viewer_connected" for c in commands))
                async with world.sessions() as db:
                    await db.execute(update(User).where(User.id == user.id).values(is_active=False))
                    await db.commit()
                await until(lambda: viewer.closed is not None, timeout=2)
                assert viewer.closed[0] == 4001
                await asyncio.wait_for(task, 3)
                assert device not in bridges[1]._viewers
            finally:
                viewer.incoming.put_nowait(None)
                await asyncio.wait_for(task, 3)


@pytest.mark.parametrize("outage", ["sql", "redis", "deadline"])
async def test_viewer_authorization_outage_never_dispatches_or_replays_input(world, monkeypatch, outage):
    from redis.exceptions import ConnectionError as RedisConnectionError

    from backend.services.cache_service import CacheService

    module = importlib.import_module("backend.api.ws.stream.router")
    device = str(world.dev_a.id)
    viewer = Viewer(world.auth(world.users["org_admin"])["Authorization"].split()[1])
    async with workers(world) as (bridges, commands):
        with patch.object(module, "AsyncSessionLocal", world.sessions), patch.object(module, "get_stream_bridge", return_value=bridges[1]):
            task = asyncio.create_task(module.stream_viewer_ws(viewer, device))
            try:
                await until(lambda: any(c["type"] == "viewer_connected" for c in commands))
                if outage == "sql":
                    unavailable = AsyncMock(side_effect=ConnectionError("isolated database outage"))
                    monkeypatch.setattr(module, "_authenticate_viewer", unavailable)
                elif outage == "redis":
                    monkeypatch.setattr(CacheService, "is_token_blacklisted", AsyncMock(side_effect=RedisConnectionError()))
                else:
                    async def stalled_check(*_args):
                        await asyncio.Event().wait()

                    monkeypatch.setattr(CacheService, "is_token_blacklisted", stalled_check)
                    monkeypatch.setattr(module, "VIEWER_AUTH_TIMEOUT_SECONDS", 0.03)
                viewer.incoming.put_nowait({"type": "text", "text": "must-not-run"})
                await until(lambda: viewer.closed is not None)
                assert viewer.closed == (1013, "stream_auth_unavailable")
                assert not any(c["type"] == "text" for c in commands)
                await asyncio.wait_for(task, 3)
                assert device not in bridges[1]._viewers
            finally:
                viewer.incoming.put_nowait(None)
                await asyncio.wait_for(task, 3)
