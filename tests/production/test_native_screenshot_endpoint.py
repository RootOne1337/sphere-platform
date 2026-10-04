import base64
import hashlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.database.redis_client import get_redis_binary
from tests.test_native_screenshot import png_fixture


@pytest.fixture
def screenshot_transport(world):
    from backend.main import app
    app.dependency_overrides[get_redis_binary] = lambda: world.redis
    publisher = AsyncMock()
    data = png_fixture()

    async def reply(device, command, **options):
        assert options["live_only"] is True and options["timeout"] == 8
        assert command["type"] == "SHELL" and command["command_id"].startswith("interactive_")
        cmd = command["payload"]["cmd"]
        output = ""
        if cmd == "wm size":
            output = "Physical size: 2x1"
        elif cmd.startswith("wc -c "):
            output = str(len(data))
        elif cmd.startswith("sha256sum "):
            output = hashlib.sha256(data).hexdigest() + "  " + cmd.removeprefix("sha256sum ")
        elif cmd.startswith("base64 "):
            output = base64.b64encode(data).decode()
        return {"status": "completed", "result": {"output": output}}
    publisher.send_command_wait_result.side_effect = reply
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        yield publisher
    app.dependency_overrides.pop(get_redis_binary, None)


async def test_returns_original_png_hash_geometry_owner_and_cleanup(world, screenshot_transport):
    response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/screenshot/native",
        headers=world.auth(world.users["org_admin"]), json={"command": "reboot"})
    assert response.status_code == 200, response.text
    assert response.content == png_fixture()
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-screenshot-device-id"] == str(world.dev_a.id)
    assert response.headers["x-screenshot-sha256"] == hashlib.sha256(response.content).hexdigest()
    assert response.headers["x-screenshot-android-sha256"] == response.headers["x-screenshot-sha256"]
    assert response.headers["x-screenshot-cleanup-confirmed"] == "true"
    assert len(screenshot_transport.send_command_wait_result.await_args_list) == 8
    assert await world.redis.get(f"sphere:native-screenshot:{world.org_a.id}:{world.dev_a.id}") is None


@pytest.mark.parametrize("target,role,code", [("dev_b", "org_admin", 404), ("dev_a", "viewer", 403)])
async def test_authorizes_before_lock_and_capture(world, screenshot_transport, target, role, code):
    response = await world.client.post(f"/api/v1/devices/{getattr(world,target).id}/screenshot/native", headers=world.auth(world.users[role]))
    assert response.status_code == code
    screenshot_transport.send_command_wait_result.assert_not_awaited()


async def test_busy_capture_preserves_other_owner(world, screenshot_transport):
    key = f"sphere:native-screenshot:{world.org_a.id}:{world.dev_a.id}"
    await world.redis.set(key, "different-owner", ex=120)
    try:
        response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/screenshot/native", headers=world.auth(world.users["org_admin"]))
        assert response.status_code == 429
        assert await world.redis.get(key) == "different-owner"
        screenshot_transport.send_command_wait_result.assert_not_awaited()
    finally:
        await world.redis.delete(key)


@pytest.mark.parametrize("failure", ["partial", "failed", "offline", "cleanup", "android-hash"])
async def test_never_serves_partial_png_or_hides_original_errors(world, screenshot_transport, failure):
    original = screenshot_transport.send_command_wait_result.side_effect
    async def reply(device, command, **options):
        cmd = command["payload"]["cmd"]
        if failure == "offline":
            raise HTTPException(503, "Device command channel unavailable")
        if cmd.startswith("base64 ") and failure == "partial":
            return {"status": "completed", "result": {"output": "AAAA"}}
        if cmd.startswith("sha256sum ") and failure == "android-hash":
            return {"status": "completed", "result": {"output": "f" * 64 + "  " + cmd.removeprefix("sha256sum ")}}
        if cmd.startswith("screencap ") and failure == "failed":
            return {"status": "failed", "error": "private failure"}
        if cmd.startswith("rm -f ") and failure == "cleanup":
            raise HTTPException(503, "Device command channel unavailable")
        return await original(device, command, **options)
    screenshot_transport.send_command_wait_result.side_effect = reply
    response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/screenshot/native", headers=world.auth(world.users["org_admin"]))
    assert response.status_code == (200 if failure == "cleanup" else 503 if failure == "offline" else 502), response.text
    if failure == "cleanup":
        assert response.content == png_fixture() and response.headers["x-screenshot-cleanup-confirmed"] == "false"
    else:
        assert not response.content.startswith(b"\x89PNG") and "private failure" not in response.text
    assert await world.redis.get(f"sphere:native-screenshot:{world.org_a.id}:{world.dev_a.id}") is None
