from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from backend.api.ws.stream import router as stream_router


@pytest.fixture
def authorized_viewer(monkeypatch):
    org_id = uuid4()
    user = SimpleNamespace(id=uuid4(), org_id=org_id, role="admin")
    device = SimpleNamespace(org_id=org_id)
    db = AsyncMock()
    db.get.return_value = device
    db_context = AsyncMock()
    db_context.__aenter__.return_value = db
    db_context.__aexit__.return_value = False
    monkeypatch.setattr(stream_router, "AsyncSessionLocal", lambda: db_context)

    async def authenticate(_token, _db):
        return user

    monkeypatch.setattr(stream_router, "_authenticate_viewer", authenticate)
    monkeypatch.setattr("backend.core.rbac.has_permission", lambda _role, _permission: True)

    bridge = MagicMock()
    bridge.register_viewer = AsyncMock()
    bridge.send_control = AsyncMock(return_value=True)
    bridge.unregister_viewer = AsyncMock()
    monkeypatch.setattr(stream_router, "get_stream_bridge", lambda: bridge)

    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.receive_json = AsyncMock(side_effect=[
        {"token": "test-viewer-token"},
        {"type": "request_keyframe"},
        WebSocketDisconnect(code=1000),
    ])
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws, bridge


@pytest.mark.asyncio
async def test_viewer_keyframe_request_is_forwarded_to_the_android_agent(authorized_viewer):
    ws, bridge = authorized_viewer
    device_id = str(uuid4())
    await stream_router.stream_viewer_ws(ws, device_id)

    sent_controls = bridge.send_control.await_args_list
    registered_viewer = bridge.register_viewer.await_args
    assert len(sent_controls) == 2
    assert registered_viewer.args[:2] == (device_id, ws)
    assert sent_controls[0].args == (
        device_id,
        {"type": "viewer_connected", "session_id": registered_viewer.args[2]},
    )
    assert sent_controls[1] == call(device_id, {"type": "request_keyframe"})
    bridge.unregister_viewer.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [json.JSONDecodeError("invalid json", "private-value", 0),
                                  UnicodeDecodeError("utf-8", b"private-value\xff", 13, 14, "bad byte"),
                                  ValueError("integer limit: private-value"), RecursionError("nested private-value")])
async def test_bad_json_is_rejected_without_retiring_stream_or_logging_payload(authorized_viewer, monkeypatch, error):
    ws, bridge = authorized_viewer
    ws.receive_json = AsyncMock(side_effect=[{"token": "test-viewer-token"}, error,
                                            {"type": "request_keyframe"}, WebSocketDisconnect()])
    warning = MagicMock()
    monkeypatch.setattr(stream_router.logger, "warning", warning)
    await stream_router.stream_viewer_ws(ws, str(uuid4()))
    ws.send_json.assert_awaited_once_with({"type": "error", "error": "stream_input_invalid", "reason": "invalid_message"})
    assert [call.args[1]["type"] for call in bridge.send_control.await_args_list] == ["viewer_connected", "request_keyframe"]
    ws.close.assert_not_awaited()
    bridge.unregister_viewer.assert_awaited_once()
    warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [None, [], True, "private-token", {"token": []}, {"token": 123}])
async def test_invalid_auth_shape_is_closed_before_database_or_registration(monkeypatch, message):
    ws = MagicMock(accept=AsyncMock(), receive_json=AsyncMock(return_value=message), close=AsyncMock())
    database = MagicMock()
    bridge = MagicMock()
    monkeypatch.setattr(stream_router, "AsyncSessionLocal", database)
    monkeypatch.setattr(stream_router, "get_stream_bridge", bridge)
    await stream_router.stream_viewer_ws(ws, str(uuid4()))
    ws.close.assert_awaited_once_with(code=4001, reason="invalid_auth_message")
    database.assert_not_called()
    bridge.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("message_type", [[], {}, None, 123])
async def test_malformed_type_keeps_video_and_later_control_alive(authorized_viewer, message_type):
    ws, bridge = authorized_viewer
    ws.receive_json = AsyncMock(side_effect=[{"token": "test-viewer-token"}, {"type": message_type},
                                            {"type": "request_keyframe"}, WebSocketDisconnect()])
    await stream_router.stream_viewer_ws(ws, str(uuid4()))
    ws.send_json.assert_awaited_once_with({"type": "error", "error": "stream_input_invalid", "reason": "invalid_message"})
    assert [call.args[1]["type"] for call in bridge.send_control.await_args_list] == ["viewer_connected", "request_keyframe"]
    ws.close.assert_not_awaited()
    bridge.unregister_viewer.assert_awaited_once()


@pytest.mark.asyncio
async def test_touch_probe_requires_current_control_permission(authorized_viewer, monkeypatch):
    ws, bridge = authorized_viewer
    runtime = MagicMock(register=MagicMock(return_value=True), handle=AsyncMock(),
        retire=AsyncMock(), unregister=AsyncMock())
    monkeypatch.setattr(stream_router, 'get_continuous_runtime', lambda: runtime)
    monkeypatch.setattr('backend.core.rbac.has_permission', lambda role, permission: permission == 'stream:read')
    ws.receive_json = AsyncMock(side_effect=[{'token': 'fixture'}, {'type': 'touch_probe'}, WebSocketDisconnect()])
    await stream_router.stream_viewer_ws(ws, str(uuid4()))
    runtime.handle.assert_not_awaited()
    runtime.unregister.assert_awaited_once()
    assert ws.send_json.await_args.args[0]['type'] == 'touch_error'
    assert len(bridge.send_control.await_args_list) == 1


@pytest.mark.asyncio
async def test_touch_close_is_allowed_after_control_revocation(authorized_viewer, monkeypatch):
    ws, bridge = authorized_viewer
    runtime = MagicMock(register=MagicMock(return_value=True), handle=AsyncMock(),
        retire=AsyncMock(), unregister=AsyncMock())
    monkeypatch.setattr(stream_router, 'get_continuous_runtime', lambda: runtime)
    monkeypatch.setattr('backend.core.rbac.has_permission', lambda role, permission: permission == 'stream:read')
    ws.receive_json = AsyncMock(side_effect=[{'token': 'fixture'}, {'type': 'touch_close'}, WebSocketDisconnect()])
    await stream_router.stream_viewer_ws(ws, str(uuid4()))
    runtime.handle.assert_awaited_once()
    assert runtime.handle.await_args.args[1] == {'type': 'touch_close'}


@pytest.mark.asyncio
async def test_active_touch_lease_blocks_legacy_swipe_on_same_viewer(authorized_viewer, monkeypatch):
    ws, bridge = authorized_viewer
    runtime = MagicMock(handle=AsyncMock(), retire=AsyncMock(), unregister=AsyncMock())
    def register(viewer):
        viewer.lease = object()
        viewer.closing = True  # No background auth needed for this admission case.
        return True
    runtime.register.side_effect = register
    monkeypatch.setattr(stream_router, 'get_continuous_runtime', lambda: runtime)
    ws.receive_json = AsyncMock(side_effect=[{'token': 'fixture'},
        {'type': 'swipe', 'x1': 1, 'y1': 1, 'x2': 20, 'y2': 20, 'duration_ms': 200}, WebSocketDisconnect()])
    await stream_router.stream_viewer_ws(ws, str(uuid4()))
    assert len(bridge.send_control.await_args_list) == 1
    assert ws.send_json.await_args.args[0] == {'type': 'touch_error', 'error': 'close_gestures_before_discrete_input'}
