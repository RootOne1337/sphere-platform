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
