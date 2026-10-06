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
