"""Capture presence must never become a hidden video relay or input grant."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from starlette.websockets import WebSocketDisconnect

from backend.api.ws.stream import router
from backend.schemas.stream_quality import StreamQualitySnapshot
from backend.websocket import capture_lifecycle
from backend.websocket.channels import ChannelPattern
from backend.websocket.stream_bridge import VideoStreamBridge
from tests.test_stream_quality import snapshot
from tests.test_ws.test_stream_viewer_keyframe import authorized_viewer  # noqa: F401


async def test_capture_presence_has_no_queue_sender_or_video_subscription():
    redis = FakeRedis(decode_responses=False)
    bridge = VideoStreamBridge(AsyncMock(), redis)
    ws, other = AsyncMock(), AsyncMock()
    try:
        await bridge.register_viewer("d", ws, "capture", capture_only=True)
        viewer = bridge._viewers["d"]["capture"]
        assert viewer.capture_only and not viewer.legacy
        assert viewer.queue is None and viewer.task is None
        assert await bridge.transport.has_viewers("d")
        topic = ChannelPattern.video_stream("d")
        assert dict(await redis.pubsub_numsub(topic))[topic.encode()] == 0
        assert not await bridge.set_legacy_delivery("d", "capture", True)
        await bridge.receive_frame("d", b"\x00\x00\x01\x65\xff")
        ws.send_bytes.assert_not_awaited()
        assert bridge.get_drop_ratio("d") == 0
        # A normal viewer on the same worker still receives its own fallback.
        await bridge.register_viewer("d", other, "browser")
        assert dict(await redis.pubsub_numsub(topic))[topic.encode()] == 1
        await bridge.receive_frame("d", b"\x00\x00\x01\x65\xff")
        async with asyncio.timeout(1):
            while not other.send_bytes.await_count:
                await asyncio.sleep(.005)
        await bridge.unregister_viewer("d", "capture")
        assert bridge.is_streaming("d")
        other.close.assert_not_awaited()
    finally:
        await bridge.close()
        await redis.aclose()


async def test_missing_peer_renewal_expires_presence_without_relay(monkeypatch):
    monkeypatch.setattr("backend.websocket.stream_bridge.CAPTURE_SETUP_SECONDS", .03)
    bridge = VideoStreamBridge(AsyncMock())
    ws = AsyncMock()
    try:
        await bridge.register_viewer("d", ws, "c", capture_only=True)
        async with asyncio.timeout(1):
            while bridge.is_streaming("d"):
                await asyncio.sleep(.005)
        ws.close.assert_awaited_once_with(code=4008, reason="capture_lease_expired")
        ws.send_bytes.assert_not_awaited()
    finally:
        await bridge.close()


async def test_direct_renewal_keeps_capture_only_immutable(monkeypatch):
    monkeypatch.setattr("backend.websocket.stream_bridge.CAPTURE_SETUP_SECONDS", .01)
    monkeypatch.setattr("backend.websocket.stream_bridge.DIRECT_DELIVERY_SECONDS", .15)
    bridge = VideoStreamBridge(AsyncMock())
    ws = AsyncMock()
    try:
        await bridge.register_viewer("d", ws, "c", capture_only=True)
        assert await bridge.set_legacy_delivery("d", "c", False)
        await asyncio.sleep(.03)
        assert bridge.is_streaming("d") and not bridge._viewers["d"]["c"].legacy
        ws.close.assert_not_awaited()
    finally:
        await bridge.close()


async def test_active_lease_expires_before_longer_setup_grace(monkeypatch):
    monkeypatch.setattr("backend.websocket.stream_bridge.CAPTURE_SETUP_SECONDS", 40)
    monkeypatch.setattr("backend.websocket.stream_bridge.DIRECT_DELIVERY_SECONDS", .02)
    bridge = VideoStreamBridge(AsyncMock())
    ws = AsyncMock()
    try:
        await bridge.register_viewer("d", ws, "c", capture_only=True)
        await asyncio.sleep(0)  # Let the original 40-second timer start sleeping.
        assert await bridge.set_legacy_delivery("d", "c", False)
        async with asyncio.timeout(.5):
            while bridge.is_streaming("d"):
                await asyncio.sleep(.005)
        ws.close.assert_awaited_once_with(code=4008, reason="capture_lease_expired")
        ws.send_bytes.assert_not_awaited()
    finally:
        await bridge.close()


async def test_ready_requires_completed_native_active_source(monkeypatch):
    inactive = snapshot() | {"active": None}
    rpc = AsyncMock(side_effect=[StreamQualitySnapshot.model_validate(inactive),
                                StreamQualitySnapshot.model_validate(snapshot())])
    monkeypatch.setattr(capture_lifecycle, "quality_rpc", rpc)
    assert await capture_lifecycle.await_capture_ready("d") == {"width": 960, "height": 540}
    assert rpc.await_count == 2
    assert all(c.args == ("d", None) for c in rpc.await_args_list)


async def test_uncertain_readiness_is_never_retried(monkeypatch):
    rpc = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(capture_lifecycle, "quality_rpc", rpc)
    with pytest.raises(TimeoutError):
        await capture_lifecycle.await_capture_ready("d")
    rpc.assert_awaited_once()


async def test_capture_only_auth_and_readiness_never_grant_socket_input(authorized_viewer, monkeypatch):
    ws, bridge = authorized_viewer
    ready = AsyncMock(return_value={"width": 960, "height": 540})
    monkeypatch.setattr(router, "await_capture_ready", ready)
    runtime = MagicMock(register=MagicMock(), unregister=AsyncMock())
    monkeypatch.setattr(router, "get_continuous_runtime", lambda: runtime)
    ws.receive_json = AsyncMock(side_effect=[{"token": "fixture", "delivery": "capture_only"},
        {"type": "touch_open"}, {"type": "keyevent", "keycode": 3}, WebSocketDisconnect()])
    await router.stream_viewer_ws(ws, str(uuid4()))
    assert bridge.register_viewer.await_args.kwargs == {"capture_only": True}
    runtime.register.assert_not_called()
    bridge.send_control.assert_not_awaited()
    sent = [c.args[0] for c in ws.send_json.await_args_list]
    assert sent[0]["delivery"] == "capture_only" and sent[2]["type"] == "capture_ready"
    assert sent[2]["session_id"] == sent[0]["session_id"]
    assert sent[-2:] == [{"type": "error", "error": "capture_only_message_rejected"}] * 2
    bridge.unregister_viewer.assert_awaited_once()


async def test_failed_readiness_unregisters_capture_presence(authorized_viewer, monkeypatch):
    ws, bridge = authorized_viewer
    monkeypatch.setattr(router, "await_capture_ready", AsyncMock(side_effect=TimeoutError()))
    ws.receive_json = AsyncMock(return_value={"token": "fixture", "delivery": "capture_only"})
    await router.stream_viewer_ws(ws, str(uuid4()))
    ws.close.assert_awaited_once_with(code=1013, reason="capture_readiness_unavailable")
    bridge.unregister_viewer.assert_awaited_once()


@pytest.mark.parametrize("delivery", [None, "direct", [], True, "capture-only"])
async def test_unknown_capture_admission_never_registers(authorized_viewer, delivery):
    ws, bridge = authorized_viewer
    ws.receive_json = AsyncMock(return_value={"token": "fixture", "delivery": delivery})
    await router.stream_viewer_ws(ws, str(uuid4()))
    ws.close.assert_awaited_once_with(code=4001, reason="invalid_capture_admission")
    bridge.register_viewer.assert_not_awaited()
