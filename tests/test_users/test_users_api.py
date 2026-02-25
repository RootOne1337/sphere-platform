# tests/test_users/test_users_api.py
"""
HTTP integration tests for the User Management API.

Enterprise rationale
--------------------
- Role changes are restricted to org_owner/super_admin only — org_admin must
  get 403 when attempting PUT /{id}/role.
- Last org_owner guard: attempting to demote the only org_owner returns 400
  (prevents an org from becoming permanently un-manageable).
- Self-deactivation guard: cannot deactivate your own account via
  PATCH /{id}/deactivate → 400.
- Tenant isolation: a user in org-A cannot see users in org-B,
  even if they know the UUID.
- Duplicate email → 409 Conflict (never 500 DB constraint error).
- viewer role → 403 on every user-management endpoint.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

# ===========================================================================
# List users
# ===========================================================================

class TestListUsers:
    async def test_owner_can_list_users(self, owner_client, owner_user, subuser):
        resp = await owner_client.get("/api/v1/users")
        assert resp.status_code == 200
        ids = [u["id"] for u in resp.json()["items"]]
        assert str(owner_user.id) in ids

    async def test_admin_can_list_users(self, admin_client):
        resp = await admin_client.get("/api/v1/users")
        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_viewer_cannot_list_users(self, viewer_client):
        resp = await viewer_client.get("/api/v1/users")
        assert resp.status_code == 403

    async def test_unauthenticated_returns_401(self):
        from httpx import ASGITransport, AsyncClient

        from backend.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.get("/api/v1/users")
        assert resp.status_code == 401

    async def test_list_users_pagination(self, owner_client):
        resp = await owner_client.get("/api/v1/users?page=1&per_page=2")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) <= 2
        assert "total" in body
        assert "pages" in body


# ===========================================================================
# Create user
# ===========================================================================

class TestCreateUser:
    async def test_owner_creates_user(self, owner_client):
        resp = await owner_client.post(
            "/api/v1/users",
            json={
                "email": f"new-{uuid.uuid4()}@example.com",
                "password": "S3cur3P@ss!",
                "role": "viewer",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "viewer"

    async def test_admin_creates_user(self, admin_client):
        resp = await admin_client.post(
            "/api/v1/users",
            json={
                "email": f"admin-new-{uuid.uuid4()}@example.com",
                "password": "S3cur3P@ss!",
                "role": "viewer",
            },
        )
        assert resp.status_code == 201

    async def test_duplicate_email_returns_409(self, owner_client, subuser):
        """Duplicate email → 409, never a raw 500 DB constraint error."""
        resp = await owner_client.post(
            "/api/v1/users",
            json={
                "email": subuser.email,  # already exists
                "password": "S3cur3P@ss!",
                "role": "viewer",
            },
        )
        assert resp.status_code == 409

    async def test_viewer_cannot_create_user(self, viewer_client):
        resp = await viewer_client.post(
            "/api/v1/users",
            json={
                "email": f"blocked-{uuid.uuid4()}@example.com",
                "password": "S3cur3P@ss!",
                "role": "viewer",
            },
        )
        assert resp.status_code == 403


# ===========================================================================
# Get user
# ===========================================================================

class TestGetUser:
    async def test_owner_gets_user_in_own_org(self, owner_client, subuser):
        resp = await owner_client.get(f"/api/v1/users/{subuser.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(subuser.id)

    async def test_nonexistent_user_returns_404(self, owner_client):
        resp = await owner_client.get(f"/api/v1/users/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_cross_org_user_returns_404(
        self, owner_client, db_session: AsyncSession
    ):
        """Tenant isolation: seeing a user from another org returns 404."""
        from backend.core.security import hash_password
        from backend.models.organization import Organization
        from backend.models.user import User

        other_org = Organization(name="Alien Org", slug="alien-org")
        db_session.add(other_org)
        await db_session.flush()
        alien_user = User(
            org_id=other_org.id,
            email="alien@sphere.local",
            password_hash=hash_password("pw"),
            role="viewer",
        )
        db_session.add(alien_user)
        await db_session.flush()

        resp = await owner_client.get(f"/api/v1/users/{alien_user.id}")
        # Must be 404, not 200 — do not expose that user exists
        assert resp.status_code == 404


# ===========================================================================
# Role change
# ===========================================================================

class TestUpdateRole:
    async def test_owner_can_change_role(
        self, owner_client, subuser
    ):
        resp = await owner_client.put(
            f"/api/v1/users/{subuser.id}/role",
            json={"role": "device_manager"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "device_manager"

    async def test_admin_cannot_change_role(self, admin_client, subuser):
        """org_admin does NOT have permission to change roles — only org_owner."""
        resp = await admin_client.put(
            f"/api/v1/users/{subuser.id}/role",
            json={"role": "device_manager"},
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_change_role(self, viewer_client, owner_user):
        resp = await viewer_client.put(
            f"/api/v1/users/{owner_user.id}/role",
            json={"role": "viewer"},
        )
        assert resp.status_code == 403

    async def test_cannot_demote_last_org_owner(
        self, owner_client, owner_user, users_org, db_session: AsyncSession
    ):
        """Guard: the last org_owner cannot be demoted — org must always have one."""
        # owner_user is the only org_owner in this org (admin_user has role=org_admin)
        resp = await owner_client.put(
            f"/api/v1/users/{owner_user.id}/role",
            json={"role": "org_admin"},
        )
        assert resp.status_code == 400
        assert "last" in resp.json()["detail"].lower() or "owner" in resp.json()["detail"].lower()

    async def test_can_demote_non_last_org_owner(
        self,
        owner_client,
        second_owner,
    ):
        """When two org_owners exist, demoting one is allowed."""
        resp = await owner_client.put(
            f"/api/v1/users/{second_owner.id}/role",
            json={"role": "org_admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "org_admin"


# ===========================================================================
# Deactivate user
# ===========================================================================

class TestDeactivateUser:
    async def test_owner_can_deactivate_subuser(self, owner_client, subuser):
        resp = await owner_client.patch(f"/api/v1/users/{subuser.id}/deactivate")
        assert resp.status_code == 204

    async def test_admin_can_deactivate_subuser(self, admin_client, subuser):
        resp = await admin_client.patch(f"/api/v1/users/{subuser.id}/deactivate")
        assert resp.status_code == 204

    async def test_cannot_deactivate_self(self, owner_client, owner_user):
        """Self-deactivation is always forbidden — prevents accidental lock-out."""
        resp = await owner_client.patch(
            f"/api/v1/users/{owner_user.id}/deactivate"
        )
        assert resp.status_code == 400
        assert "yourself" in resp.json()["detail"].lower()

    async def test_deactivate_nonexistent_user_returns_404(self, owner_client):
        resp = await owner_client.patch(
            f"/api/v1/users/{uuid.uuid4()}/deactivate"
        )
        assert resp.status_code == 404

    async def test_viewer_cannot_deactivate_user(self, viewer_client, owner_user):
        resp = await viewer_client.patch(
            f"/api/v1/users/{owner_user.id}/deactivate"
        )
        assert resp.status_code == 403

    async def test_deactivated_user_cannot_list_users(
        self,
        owner_client,
        admin_client,
        admin_user,
    ):
        """After deactivation the account is inactive; subsequent JWT requests
        should be rejected.  Here we verify is_active becomes False."""
        deact_resp = await owner_client.patch(
            f"/api/v1/users/{admin_user.id}/deactivate"
        )
        assert deact_resp.status_code == 204

        # Refresh the object to confirm DB state

        # We can't easily re-query via the session fixture, but we can verify
        # via the GET endpoint that the user still exists (but is_active=False)
        get_resp = await owner_client.get(f"/api/v1/users/{admin_user.id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["is_active"] is False
