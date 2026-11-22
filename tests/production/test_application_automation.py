"""Application bindings and policy writes under the PostgreSQL runtime role."""

import asyncio

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database.engine import get_db
from backend.main import app
from backend.models import GameAccount, Task, User
from backend.models.task import TaskStatus
from backend.services.application_profile_service import BUILTIN_ID

CATALOG = "/api/v1/application-profiles"
SESSIONS = "/api/v1/account-sessions"


@pytest_asyncio.fixture
async def runtime_api(world, runtime_db):
    async with world.sessions() as db:
        foreign = User(
            org_id=world.org_b.id, email=f"automation-b-{world.suffix}@example.org",
            password_hash="unused-local-fixture", role="org_admin",
        )
        db.add(foreign)
        await db.commit()

    engine = create_async_engine(runtime_db.engine.url, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        yield world.auth(world.users["org_admin"]), world.auth(foreign)
    finally:
        await engine.dispose()


async def _profile(world, headers, key, package="test.example.arena"):
    response = await world.client.post(CATALOG, headers=headers, json={
        "key": key, "name": key, "android_package": package,
        "servers": [{"key": "shared", "name": "Shared", "domain": "game.example.test", "port": 9001}],
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _binding(profile_id, server_key, revision):
    return {"application_profile_id": profile_id, "application_server_key": server_key, "expected_revision": revision}


async def test_binding_and_session_share_exact_scope_and_idle_fence(world, runtime_api):
    admin, foreign_admin = runtime_api
    first = await _profile(world, admin, "arena-one")
    second = await _profile(world, admin, "arena-two")
    foreign = await _profile(world, foreign_admin, "arena-one")
    path = f"/api/v1/devices/{world.dev_a.id}/application-binding"
    viewer = world.auth(world.users["viewer"])
    read = await world.client.get(path, headers=viewer)
    assert read.headers["Cache-Control"] == "no-store"
    assert read.json() == {
        "device_id": str(world.dev_a.id), "application_profile_id": None, "application_server_key": None, "revision": 0,
    }
    assert (await world.client.get(path, headers=foreign_admin)).status_code == 404
    assert (await world.client.put(path, headers=viewer, json=_binding(first, "shared", 0))).status_code == 403
    for profile, server, status in [
        (first, None, 422), (first, "unknown", 422), (str(BUILTIN_ID), "shared", 409), (foreign, "shared", 404),
    ]:
        rejected = await world.client.put(path, headers=admin, json=_binding(profile, server, 0))
        assert rejected.status_code == status, rejected.text

    async with world.sessions() as db:
        account = GameAccount(
            org_id=world.org_a.id, game="arena-one", server_name="Shared", login="matching", password_encrypted="",
        )
        other = GameAccount(
            org_id=world.org_a.id, game="arena-two", server_name="Shared", login="other", password_encrypted="",
        )
        task = Task(org_id=world.org_a.id, script_id=world.script.id, device_id=world.dev_a.id)
        db.add_all((account, other, task))
        await db.commit()

    busy = await world.client.put(path, headers=admin, json=_binding(first, "shared", 0))
    assert busy.status_code == 409, busy.text
    async with world.sessions() as db:
        saved_task = await db.get(Task, task.id)
        saved_task.status = TaskStatus.COMPLETED
        await db.commit()

    saved = await world.client.put(path, headers=admin, json=_binding(first, "shared", 0))
    assert saved.status_code == 200, saved.text
    assert saved.headers["Cache-Control"] == "no-store"
    assert saved.json()["revision"] == 1
    assert (await world.client.put(path, headers=admin, json=_binding(second, "shared", 0))).status_code == 409
    assert (await world.client.put(path, headers=admin, json=_binding(first, "shared", 1))).json() == saved.json()

    def session_data(row):
        return {"account_id": str(row.id), "device_id": str(world.dev_a.id)}

    mismatch = await world.client.post(SESSIONS, headers=admin, json=session_data(other))
    assert mismatch.status_code == 409, mismatch.text
    session = await world.client.post(SESSIONS, headers=admin, json=session_data(account))
    assert session.status_code == 201, session.text
    assert session.json()["account_game"] == "arena-one"
    assert session.json()["device_name"] == world.dev_a.name
    assert (await world.client.put(path, headers=admin, json=_binding(second, "shared", 1))).status_code == 409

    session_path = f"{SESSIONS}/{session.json()['id']}"
    ended = await world.client.post(f"{session_path}/end", headers=admin, json={"end_reason": "manual"})
    assert ended.status_code == 200, ended.text
    cleared = await world.client.put(path, headers=admin, json=_binding(None, None, 1))
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["revision"] == 2
    historical = await world.client.get(session_path, headers=admin)
    assert historical.status_code == 200, historical.text
    assert historical.json()["account_game"] == "arena-one"


async def test_policy_first_write_is_atomic_and_independent(world, runtime_db, runtime_api):
    admin, foreign_admin = runtime_api
    first = await _profile(world, admin, "arena-one")
    second = await _profile(world, admin, "arena-two", package=None)
    first_path = f"{CATALOG}/{first}/automation-policy"
    second_path = f"{CATALOG}/{second}/automation-policy"
    read = await world.client.get(first_path, headers=admin)
    assert read.status_code == 200, read.text
    assert read.headers["Cache-Control"] == "no-store"
    assert read.json()["revision"] == 0
    assert read.json()["registration_enabled"] is read.json()["farming_enabled"] is False
    assert (await world.client.get(first_path, headers=foreign_admin)).status_code == 404
    script_id = str(world.script.id)
    requested = {
        "expected_revision": 0, "registration_script_id": script_id, "registration_enabled": True,
        "farming_script_id": script_id, "farming_enabled": True,
    }
    viewer = world.auth(world.users["viewer"])
    assert (await world.client.put(first_path, headers=viewer, json=requested)).status_code == 403
    assert (await world.client.put(second_path, headers=admin, json=requested)).status_code == 422
    missing_script = await world.client.put(first_path, headers=admin, json={
        "expected_revision": 0, "registration_enabled": True,
    })
    assert missing_script.status_code == 422, missing_script.text

    writes = await asyncio.gather(*(world.client.put(first_path, headers=admin, json={
        **requested, "max_concurrent_farming": limit,
    }) for limit in (5, 12)))
    assert sorted(response.status_code for response in writes) == [200, 409]
    enabled = next(response.json() for response in writes if response.status_code == 200)
    assert enabled["revision"] == 1
    assert enabled["registration_script_id"] == enabled["farming_script_id"] == script_id
    assert (await world.client.get(second_path, headers=admin)).json()["revision"] == 0
    catalog = (await world.client.get(CATALOG, headers=admin)).json()
    profile = next(item for item in catalog["items"] if item["id"] == first)
    clear_package = {"expected_updated_at": profile["updated_at"], "android_package": None}
    rejected = await world.client.patch(f"{CATALOG}/{first}", headers=admin, json=clear_package)
    assert rejected.status_code == 409, rejected.text

    cleared = await world.client.put(first_path, headers=admin, json={
        "expected_revision": 1, "farming_enabled": False, "farming_script_id": None,
    })
    assert cleared.status_code == 200, cleared.text
    assert cleared.headers["Cache-Control"] == "no-store"
    assert cleared.json()["farming_script_id"] is None
    assert cleared.json()["registration_enabled"] is True
    assert cleared.json()["revision"] == 2
    disabled = await world.client.put(first_path, headers=admin, json={
        "expected_revision": 2, "registration_enabled": False,
    })
    assert disabled.status_code == 200, disabled.text
    saved = await world.client.patch(f"{CATALOG}/{first}", headers=admin, json=clear_package)
    assert saved.status_code == 200, saved.text
    assert saved.json()["android_package"] is None
    async with runtime_db.engine.connect() as db:
        assert await db.scalar(text("SELECT row_security_active('application_automation_policies')")) is True
        assert await db.scalar(text("SELECT count(*) FROM application_automation_policies")) == 0
