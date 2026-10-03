"""Real HTTP authentication, role refresh and permission guards in PostgreSQL."""
import json
from pathlib import Path

import pytest
from sqlalchemy import update

from backend.core.rbac import PERMISSIONS, has_permission
from backend.models.user import User


def test_web_role_fixtures_do_not_drift_from_server_permissions():
    fixture = json.loads((Path(__file__).resolve().parents[2] / "frontend/__tests__/fixtures/session-capabilities.json").read_text())
    for role, permissions in fixture.items():
        assert permissions == sorted(p for p in PERMISSIONS if has_permission(role, p))


@pytest.mark.parametrize("role", ["viewer", "script_runner", "device_manager", "org_admin", "org_owner", "super_admin", "api_user"])
async def test_capabilities_match_actual_guards_and_belong_to_authenticated_identity(world, role):
    user = world.users["org_admin"]
    headers = world.auth(user)  # Old admin claim must not override the database role.
    async with world.sessions() as db:
        await db.execute(update(User).where(User.id == user.id).values(role=role))
        await db.commit()
    response = await world.client.get("/api/v1/auth/capabilities", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "schema_version": 1, "user_id": str(user.id), "org_id": str(user.org_id),
        "role": role, "permissions": sorted(p for p in PERMISSIONS if has_permission(role, p)),
    }
    assert response.headers["cache-control"] == "no-store"
    read = await world.client.get("/api/v1/devices", headers=headers)
    assert read.status_code == (200 if has_permission(role, "device:read") else 403)
    # Foreign content must remain hidden even for an organization administrator.
    if role != "super_admin" and has_permission(role, "device:read"):
        foreign = await world.client.get(f"/api/v1/devices/{world.dev_b.id}", headers=headers)
        assert foreign.status_code == 404


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-token"}])
async def test_capabilities_never_serve_anonymous_or_invalid_tokens(world, headers):
    response = await world.client.get("/api/v1/auth/capabilities", headers=headers)
    assert response.status_code == 401
    assert "permissions" not in response.json()


async def test_revocation_is_visible_to_the_same_access_token(world):
    user = world.users["org_admin"]
    headers = world.auth(user)
    before = await world.client.get("/api/v1/auth/capabilities", headers=headers)
    assert "device:write" in before.json()["permissions"]
    async with world.sessions() as db:
        await db.execute(update(User).where(User.id == user.id).values(role="viewer"))
        await db.commit()
    after = await world.client.get("/api/v1/auth/capabilities", headers=headers)
    assert after.status_code == 200
    assert after.json()["role"] == "viewer"
    assert "device:write" not in after.json()["permissions"]
    # Actual mutation guard must agree; a denied reboot cannot reach Android.
    response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/reboot", headers=headers)
    assert response.status_code == 403


@pytest.mark.parametrize("role,operation", [
    (role, operation)
    for role in ("viewer", "script_runner")
    for operation in ("rename", "server", "reboot", "single_delete", "bulk_delete", "move_group", "assign_location", "revoke_vpn")
] + [("device_manager", "single_delete"), ("device_manager", "bulk_delete"), ("device_manager", "revoke_vpn")])
async def test_registry_permission_denial_precedes_mutation_with_a_prior_admin_token(world, role, operation):
    """A valid old admin JWT must agree with the newly advertised UI authority."""
    from backend.models.device import Device

    user = world.users["org_admin"]
    headers = world.auth(user)
    device_id = str(world.dev_a.id)
    original_name = world.dev_a.name
    async with world.sessions() as db:
        await db.execute(update(User).where(User.id == user.id).values(role=role))
        await db.commit()
    cases = {
        "rename": ("PUT", f"/devices/{device_id}", {"name": "Must not change"}, "device:write"),
        "server": ("PUT", f"/devices/{device_id}", {"server_name": "Must not change"}, "device:write"),
        "reboot": ("POST", "/devices/bulk/action", {"device_ids": [device_id], "action": "reboot"}, "device:write"),
        "single_delete": ("DELETE", f"/devices/{device_id}", None, "device:delete"),
        "bulk_delete": ("DELETE", "/devices/bulk", {"device_ids": [device_id]}, "device:delete"),
        # Valid UUID destinations need not exist: permission rejection must precede domain lookup.
        "move_group": ("POST", f"/groups/{device_id}/devices/move", {"device_ids": [device_id]}, "device:write"),
        "assign_location": ("POST", f"/locations/{device_id}/devices", {"device_ids": [device_id]}, "device:write"),
        "revoke_vpn": ("POST", "/vpn/revoke/bulk", {"device_ids": [device_id]}, "vpn:mass_operation"),
    }
    method, path, body, required = cases[operation]
    capability = await world.client.get("/api/v1/auth/capabilities", headers=headers)
    assert capability.status_code == 200
    assert required not in capability.json()["permissions"]
    response = await world.client.request(method, "/api/v1" + path, headers=headers, json=body)
    assert response.status_code == 403, response.text
    async with world.sessions() as db:
        device = await db.get(Device, world.dev_a.id)
        assert device is not None and device.is_active is True
        assert device.name == original_name


async def test_device_manager_update_is_allowed_without_granting_delete_or_vpn(world):
    from backend.models.device import Device

    user = world.users["org_admin"]
    headers = world.auth(user)
    async with world.sessions() as db:
        await db.execute(update(User).where(User.id == user.id).values(role="device_manager"))
        await db.commit()
    response = await world.client.put(
        f"/api/v1/devices/{world.dev_a.id}", headers=headers, json={"name": "Manager updated"},
    )
    assert response.status_code == 200, response.text
    async with world.sessions() as db:
        device = await db.get(Device, world.dev_a.id)
        assert device.name == "Manager updated"
    capability = await world.client.get("/api/v1/auth/capabilities", headers=headers)
    assert "device:write" in capability.json()["permissions"]
    assert "device:delete" not in capability.json()["permissions"]
    assert "vpn:mass_operation" not in capability.json()["permissions"]
