"""Credential disclosure must not inherit the ordinary account-read permission."""

import uuid

import pytest
import pytest_asyncio

from backend.models.game_account import GameAccount
from backend.models.user import User
from backend.services.account_credentials import set_account_password

PASSWORD = "audit-secret-do-not-disclose"


@pytest_asyncio.fixture
async def account_world(world, account_credential_key):
    async with world.sessions() as db:
        account = GameAccount(org_id=world.org_a.id, game="Audit Game",
                              login="audit-" + uuid.uuid4().hex)
        set_account_password(account, PASSWORD)
        db.add(account)
        users = {}
        for role in ("viewer", "script_runner", "device_manager", "org_admin", "org_owner", "super_admin"):
            user = User(org_id=world.org_a.id, email=f"audit-{uuid.uuid4().hex}@example.org",
                        password_hash="unused-audit-password", role=role)
            db.add(user)
            users[role] = user
        await db.commit()
    return world, account, users


@pytest.mark.parametrize("role", ["viewer", "script_runner", "device_manager"])
async def test_account_read_permission_cannot_reveal_credentials(account_world, role):
    world, account, users = account_world
    response = await world.client.get(f"/api/v1/game-accounts/{account.id}?show_password=true",
                                      headers=world.auth(users[role]))
    assert response.status_code == 403, "Account-read access must not disclose a reusable credential"
    assert PASSWORD not in response.text


@pytest.mark.parametrize("role", ["org_admin", "org_owner", "super_admin"])
async def test_authorized_credential_disclosure_is_not_cacheable(account_world, role):
    world, account, users = account_world
    response = await world.client.get(f"/api/v1/game-accounts/{account.id}?show_password=true",
                                      headers=world.auth(users[role]))
    assert response.status_code == 200
    assert response.json()["password"] == PASSWORD
    assert "no-store" in response.headers.get("Cache-Control", "")


async def test_normal_viewer_reads_still_work_without_password(account_world):
    world, account, users = account_world
    response = await world.client.get(f"/api/v1/game-accounts/{account.id}", headers=world.auth(users["viewer"]))
    assert response.status_code == 200
    assert "password" not in response.json()
    assert PASSWORD not in response.text


async def test_credential_permission_does_not_cross_tenant_boundary(account_world):
    world, account, users = account_world
    async with world.sessions() as db:
        user = await db.get(User, users["org_admin"].id)
        user.org_id = world.org_b.id
        await db.commit()
    response = await world.client.get(f"/api/v1/game-accounts/{account.id}?show_password=true",
                                      headers=world.auth(user))
    assert response.status_code == 404
    assert PASSWORD not in response.text
