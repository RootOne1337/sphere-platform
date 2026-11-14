"""Tenant/permission checks precede the quality command's cross-worker publication."""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.parametrize("method,role,status", [("GET", "org_admin", 200), ("POST", "org_admin", 200),
    ("GET", "viewer", 200), ("POST", "viewer", 403), ("GET", "foreign", 404), ("POST", "foreign", 403)])
async def test_quality_permissions_precede_device_rpc(world, method, role, status):
    snapshot = {"supported": True, "protocol": 1, "settings": {"profile": "auto"}, "active": None}
    publisher = AsyncMock()
    publisher.send_command_wait_result.return_value = {"status": "completed", "result": snapshot}
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        response = await world.client.request(method, f"/api/v1/streaming/{world.dev_a.id}/quality",
            headers=world.auth(world.users[role]), **({"json": {"profile": "detail", "max_fps": 60}} if method == "POST" else {}))
    assert response.status_code == status, response.text
    if status == 200:
        assert response.headers["cache-control"] == "private, no-store"
        publisher.send_command_wait_result.assert_awaited_once()
    else:
        publisher.send_command_wait_result.assert_not_awaited()


@pytest.mark.parametrize("body", [{"max_fps": 0}, {"max_fps": True}, {"max_fps": "60"}, {"max_bitrate_bps": 100_000_000}, {"profile": "lossless"}])
async def test_invalid_quality_never_reaches_android(world, body):
    publisher = AsyncMock()
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        response = await world.client.post(f"/api/v1/streaming/{world.dev_a.id}/quality", json=body,
            headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 422
    publisher.send_command_wait_result.assert_not_awaited()
