"""Real HTTP/SQL/Redis scope checks; Android replies are explicit RPC fixtures."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.database.redis_client import get_redis_binary


@pytest.fixture
def hierarchy_transport(world):
    from backend.main import app
    app.dependency_overrides[get_redis_binary] = lambda: world.redis
    publisher = AsyncMock()

    async def reply(device, command, **options):
        cmd = command["payload"]["cmd"]
        assert options["live_only"] is True and options["timeout"] == 8
        if cmd == "wm size":
            output = "Physical size: 540x960"
        elif cmd.startswith("cat "):
            output = '<hierarchy rotation="1"><node text="OK" bounds="[10,20][100,80]"/></hierarchy>'
        else:
            output = ""
        return {"status": "completed", "result": {"output": output}}
    publisher.send_command_wait_result.side_effect = reply
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        yield publisher
    app.dependency_overrides.pop(get_redis_binary, None)


async def test_complete_owned_snapshot_fixed_commands_cleanup_and_no_input(world, hierarchy_transport):
    response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/ui-hierarchy",
        headers=world.auth(world.users["org_admin"]), json={"command": "reboot"})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["device_id"] == str(world.dev_a.id)
    assert data["temporary_file_cleanup_confirmed"] is True
    assert (data["width"], data["height"], data["rotation"]) == (960, 540, 1)
    assert data["nodes"][0]["attributes"]["text"] == "OK"
    commands = [call.args[1] for call in hierarchy_transport.send_command_wait_result.await_args_list]
    path = "/data/local/tmp/sphere-ui-" + data["snapshot_id"] + ".xml"
    assert [c["payload"]["cmd"] for c in commands] == ["wm size", "uiautomator dump " + path, "cat " + path, "wm size", "rm -f " + path]
    assert all(c["type"] == "SHELL" and c["command_id"].startswith("interactive_") for c in commands)
    assert await world.redis.get(f"sphere:ui-inspection:{world.org_a.id}:{world.dev_a.id}") is None


@pytest.mark.parametrize("target,role,code", [("dev_b", "org_admin", 404), ("dev_a", "viewer", 403)])
async def test_scope_and_permission_checked_before_lock_or_any_command(world, hierarchy_transport, target, role, code):
    response = await world.client.post(f"/api/v1/devices/{getattr(world,target).id}/ui-hierarchy", headers=world.auth(world.users[role]))
    assert response.status_code == code
    hierarchy_transport.send_command_wait_result.assert_not_awaited()


async def test_one_dump_per_device_and_preserves_other_request_lock(world, hierarchy_transport):
    key = f"sphere:ui-inspection:{world.org_a.id}:{world.dev_a.id}"
    await world.redis.set(key, "different-owner", ex=60)
    try:
        response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/ui-hierarchy", headers=world.auth(world.users["org_admin"]))
        assert response.status_code == 429
        assert await world.redis.get(key) == "different-owner"
        hierarchy_transport.send_command_wait_result.assert_not_awaited()
    finally:
        await world.redis.delete(key)


async def test_offline_read_and_cleanup_preserve_original_503_instead_of_logging_500(world, hierarchy_transport):
    hierarchy_transport.send_command_wait_result.side_effect = HTTPException(503, "Device command channel unavailable")
    response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/ui-hierarchy", headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 503, response.text
    assert "command channel" in response.json()["detail"]
    assert hierarchy_transport.send_command_wait_result.await_count == 2
    assert await world.redis.get(f"sphere:ui-inspection:{world.org_a.id}:{world.dev_a.id}") is None


async def test_valid_tree_reports_unconfirmed_cleanup_without_losing_snapshot(world, hierarchy_transport):
    original = hierarchy_transport.send_command_wait_result.side_effect
    async def reply(device, command, **options):
        if command["payload"]["cmd"].startswith("rm -f "):
            raise HTTPException(503, "Device command channel unavailable")
        return await original(device, command, **options)
    hierarchy_transport.send_command_wait_result.side_effect = reply
    response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/ui-hierarchy", headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 200, response.text
    assert response.json()["nodes"][0]["attributes"]["text"] == "OK"
    assert response.json()["temporary_file_cleanup_confirmed"] is False


@pytest.mark.parametrize("failure", ["unsupported", "partial", "size-change", "timeout", "malformed-receipt"])
async def test_failed_snapshot_never_becomes_empty_success_and_cleanup_is_attempted(world, hierarchy_transport, failure):
    original = hierarchy_transport.send_command_wait_result.side_effect
    size_reads = 0

    async def reply(device, command, **options):
        nonlocal size_reads
        cmd = command["payload"]["cmd"]
        if cmd.startswith("uiautomator"):
            if failure == "unsupported":
                return {"status": "failed", "error": "private root error"}
            if failure == "timeout":
                raise HTTPException(504, "RPC deadline")
        if cmd == "wm size":
            size_reads += 1
            if failure == "size-change" and size_reads == 2:
                return {"status": "completed", "result": {"output": "Override size: 480x854"}}
        if cmd.startswith("cat "):
            if failure == "partial":
                return {"status": "completed", "result": {"output": '<hierarchy rotation="0"><node/>'}}
            if failure == "malformed-receipt":
                return {"status": "completed", "result": {}}
        return await original(device, command, **options)
    hierarchy_transport.send_command_wait_result.side_effect = reply
    response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/ui-hierarchy", headers=world.auth(world.users["org_admin"]))
    assert response.status_code == (409 if failure == "size-change" else 504 if failure == "timeout" else 502), response.text
    assert "private root error" not in response.text
    calls = hierarchy_transport.send_command_wait_result.await_args_list
    assert calls[-1].args[1]["payload"]["cmd"].startswith("rm -f /data/local/tmp/sphere-ui-")
    assert await world.redis.get(f"sphere:ui-inspection:{world.org_a.id}:{world.dev_a.id}") is None
