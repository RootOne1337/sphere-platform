"""Security policy regressions using real local PostgreSQL, Redis and JWT authentication."""

import pytest


@pytest.mark.asyncio
async def test_F01_org_admin_creates_super_admin_and_reads_other_org(world):
    w = world
    response = await w.client.post(
        "/api/v1/users",
        headers=w.auth(w.users["org_admin"]),
        json={
            "email": f"escalated-{w.suffix}@example.org",
            "password": "Audit-only-pass-81927",
            "role": "super_admin",
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_F02_viewer_mints_privileged_agent_key(world):
    w = world
    response = await w.client.post(
        "/api/v1/auth/api-keys",
        headers=w.auth(w.users["viewer"]),
        json={
            "name": "audit-agent",
            "key_type": "agent",
            "permissions": ["device:register", "device:write", "*"],
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_owner_cannot_promote_user_to_platform_admin(world):
    w = world
    response = await w.client.put(
        f"/api/v1/users/{w.users['viewer'].id}/role",
        headers=w.auth(w.users["org_owner"]),
        json={"role": "super_admin"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_viewer_but_cannot_deactivate_owner(world):
    w = world
    response = await w.client.post(
        "/api/v1/users",
        headers=w.auth(w.users["org_admin"]),
        json={
            "email": f"allowed-{w.suffix}@example.org",
            "password": "Audit-only-pass-81927",
            "role": "viewer",
        },
    )
    assert response.status_code == 201, response.text
    response = await w.client.patch(
        f"/api/v1/users/{w.users['org_owner'].id}/deactivate", headers=w.auth(w.users["org_admin"])
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_create_scoped_key_but_cannot_delegate_wildcard(world):
    w = world
    response = await w.client.post(
        "/api/v1/auth/api-keys",
        headers=w.auth(w.users["org_owner"]),
        json={
            "name": "allowed-agent",
            "key_type": "agent",
            "permissions": ["device:register"],
        },
    )
    assert response.status_code == 201, response.text
    response = await w.client.post(
        "/api/v1/auth/api-keys",
        headers=w.auth(w.users["org_owner"]),
        json={
            "name": "invalid-wildcard",
            "permissions": ["*"],
        },
    )
    assert response.status_code == 403
