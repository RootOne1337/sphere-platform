"""Viewer login must work with the shipped non-owner PostgreSQL role and RLS."""

import importlib
from unittest.mock import AsyncMock, patch

import pytest
from _sockets import FakeSocket


@pytest.mark.parametrize("foreign", [False, True])
async def test_viewer_auth_on_restricted_runtime_role(runtime_db, foreign):
    world = runtime_db.world
    module = importlib.import_module("backend.api.ws.stream.router")
    token = world.auth(world.users["org_admin"])["Authorization"].split()[1]
    bridge = AsyncMock()
    socket = FakeSocket([{"token": token}])
    device = world.dev_b if foreign else world.dev_a
    with patch.object(module, "AsyncSessionLocal", runtime_db.sessions), patch.object(module, "get_stream_bridge", return_value=bridge):
        await module.stream_viewer_ws(socket, str(device.id))
    if foreign:
        bridge.register_viewer.assert_not_awaited()
    else:
        bridge.register_viewer.assert_awaited_once()
        assert bridge.register_viewer.await_args.args[0] == str(device.id)
