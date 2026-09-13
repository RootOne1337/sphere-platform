"""Security policy regressions using real local PostgreSQL, Redis and JWT authentication."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _sockets import FakeSocket

from backend.core.security import create_access_token


@pytest.mark.asyncio
async def test_F04_device_token_authenticates_as_another_device(world):
    w = world
    router = importlib.import_module("backend.api.ws.android.router")
    token, _ = create_access_token(subject=str(w.dev_a.id), org_id=str(w.org_a.id), role="device")
    ws = FakeSocket([{"token": token}])
    manager = SimpleNamespace(
        connect=AsyncMock(return_value="session"), disconnect=AsyncMock(return_value=None)
    )
    status = SimpleNamespace(set_status=AsyncMock())
    heartbeat = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    with (
        patch.object(router, "AsyncSessionLocal", w.sessions),
        patch.object(router, "get_redis_binary", AsyncMock(return_value=w.redis)),
        patch.object(router, "DeviceStatusCache", return_value=status),
        patch.object(router, "get_connection_manager", return_value=manager),
        patch("backend.websocket.heartbeat.HeartbeatManager", return_value=heartbeat),
    ):
        await router.android_agent_ws(ws, str(w.dev_a2.id))
    manager.connect.assert_not_awaited()
    assert ws.closed


@pytest.mark.asyncio
async def test_F05_viewer_can_send_touch_actions(world):
    w = world
    router = importlib.import_module("backend.api.ws.stream.router")
    token = w.auth(w.users["viewer"])["Authorization"].split()[1]
    ws = FakeSocket(
        [
            {"token": token},
            {"type": "click", "x": 123, "y": 456},
            {"type": "text", "text": "audit-marker"},
        ]
    )
    manager = SimpleNamespace(send_to_device=AsyncMock())
    bridge = SimpleNamespace(register_viewer=AsyncMock(), unregister_viewer=AsyncMock())
    with (
        patch.object(router, "AsyncSessionLocal", w.sessions),
        patch.object(router, "get_stream_bridge", return_value=bridge),
        patch.object(router, "get_connection_manager", return_value=manager),
    ):
        await router.stream_viewer_ws(ws, str(w.dev_a.id))
    sent = [c.args[1]["type"] for c in manager.send_to_device.await_args_list]
    assert "touch_tap" not in sent and "text" not in sent
