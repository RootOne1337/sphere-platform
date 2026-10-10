"""JWT HTTP authentication and business writes with actual non-owner credentials."""

import asyncio
import uuid

import jwt
import pytest
from sqlalchemy import event, select, text, update

from backend.core.config import settings
from backend.core.security import create_access_token, decode_access_token
from backend.database.engine import get_db
from backend.main import app
from backend.models import AuditLog, Device, User


@pytest.fixture
def runtime_http(runtime_db, monkeypatch):
    async def request_db():
        async with runtime_db.sessions() as db:
            yield db

    app.dependency_overrides[get_db] = request_db
    monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", runtime_db.sessions)
    return runtime_db


@pytest.mark.parametrize("user_key", ["org_admin", "foreign"])
async def test_valid_jwt_binds_tenant_before_user_lookup(runtime_http, user_key):
    r = runtime_http
    w = r.world
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(r.engine.sync_engine, "before_cursor_execute", record)
    try:
        response = await w.client.get("/api/v1/auth/me", headers=w.auth(w.users[user_key]))
    finally:
        event.remove(r.engine.sync_engine, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(w.users[user_key].id)
    assert response.json()["org_id"] == str(w.users[user_key].org_id)
    tenant_index = next(i for i, sql in enumerate(statements) if "set_config(" in sql)
    user_index = next(i for i, sql in enumerate(statements) if "FROM users" in sql)
    assert tenant_index < user_index
    async with r.sessions() as fresh:
        assert await fresh.scalar(text("SELECT current_setting('app.current_org_id', true)")) in (None, "")
        assert await fresh.scalar(text("SELECT count(*) FROM users")) == 0


@pytest.mark.parametrize("outcome", ["own", "foreign_device", "viewer"])
async def test_runtime_jwt_device_update_and_audit_share_tenant_boundary(runtime_http, outcome):
    r = runtime_http
    w = r.world
    user = w.users["viewer"] if outcome == "viewer" else w.users["org_admin"]
    device = w.dev_b if outcome == "foreign_device" else w.dev_a
    response = await w.client.put(f"/api/v1/devices/{device.id}", headers=w.auth(user), json={"name": "jwt-runtime"})
    expected = {"own": 200, "foreign_device": 404, "viewer": 403}[outcome]
    assert response.status_code == expected, response.text
    async with w.sessions() as verification:
        stored = await verification.get(Device, device.id)
        assert stored.name == ("jwt-runtime" if outcome == "own" else device.name)
        logs = (await verification.scalars(select(AuditLog).where(AuditLog.org_id.in_([w.org_a.id, w.org_b.id])))).all()
        assert len(logs) == 1
        assert (logs[0].org_id, logs[0].user_id, logs[0].meta["http_status"]) == (user.org_id, user.id, expected)


async def test_concurrent_jwt_requests_reuse_one_connection_without_tenant_bleed(runtime_http):
    r = runtime_http
    w = r.world
    users = [w.users[key] for key in ["org_admin", "foreign", "viewer", "foreign"]]
    responses = await asyncio.gather(*(
        w.client.get("/api/v1/auth/me", headers=w.auth(user)) for user in users
    ))
    assert [response.status_code for response in responses] == [200] * len(users)
    assert [response.json()["id"] for response in responses] == [str(user.id) for user in users]
    async with r.sessions() as fresh:
        assert await fresh.scalar(text("SELECT count(*) FROM users")) == 0


@pytest.mark.parametrize("change", ["moved", "disabled", "downgraded"])
@pytest.mark.parametrize("use_runtime", [False, True], ids=["owner-control", "runtime-role"])
async def test_existing_token_cannot_keep_old_tenant_or_privileges(world, runtime_db, monkeypatch, change, use_runtime):
    if use_runtime:
        async def request_db():
            async with runtime_db.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = request_db
        monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", runtime_db.sessions)
    user = world.users["org_admin"]
    headers = world.auth(user)  # A legitimately issued token, before account changes.
    values = {"moved": {"org_id": world.org_b.id}, "disabled": {"is_active": False}, "downgraded": {"role": "viewer"}}[change]
    async with world.sessions() as admin:
        await admin.execute(update(User).where(User.id == user.id).values(**values))
        await admin.commit()
    if change == "moved":
        response = await world.client.get("/api/v1/auth/me", headers=headers)
    else:
        response = await world.client.put(f"/api/v1/devices/{world.dev_a.id}", headers=headers, json={"name": "must-not-change"})
    assert response.status_code == (403 if change == "downgraded" else 401), response.text
    async with world.sessions() as verification:
        assert (await verification.get(Device, world.dev_a.id)).name == world.dev_a.name


@pytest.mark.parametrize("claim,value", [
    ("org_id", None), ("org_id", ""), ("org_id", "invalid"), ("org_id", []),
    ("sub", "invalid"), ("sub", ""), ("type", "refresh"), ("type", "device_access"),
])
async def test_invalid_user_claims_are_401_even_when_database_bypasses_rls(world, claim, value):
    token, _ = create_access_token(str(world.users["org_admin"].id), str(world.org_a.id), "org_admin")
    payload = decode_access_token(token)
    if value is None:
        del payload[claim]
    else:
        payload[claim] = value
    malformed = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    response = await world.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + malformed})
    assert response.status_code == 401, response.text


async def test_signed_token_for_another_org_cannot_load_user_on_owner_connection(world):
    token, _ = create_access_token(str(world.users["org_admin"].id), str(world.org_b.id), "org_admin")
    response = await world.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401, response.text


async def test_unknown_user_with_valid_uuid_is_unauthorized(runtime_http):
    w = runtime_http.world
    token, _ = create_access_token(str(uuid.uuid4()), str(w.org_a.id), "org_admin")
    response = await w.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401, response.text
