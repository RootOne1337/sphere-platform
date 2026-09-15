"""Opaque enrollment/refresh credentials must work without granting RLS bypass."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database.engine import get_db
from backend.main import app
from backend.models import APIKey, Device
from backend.schemas.device_register import DeviceRegisterRequest
from backend.services.api_key_service import APIKeyService
from backend.services.device_registration_service import DeviceRegistrationService


@pytest.fixture
def runtime_http(runtime_db):
    async def request_db():
        async with runtime_db.sessions() as db:
            yield db
    app.dependency_overrides[get_db] = request_db
    return runtime_db.world


@pytest_asyncio.fixture
async def runtime_parallel(runtime_db):
    engine = create_async_engine(runtime_db.engine.url, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def request_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = request_db
    try:
        yield runtime_db
    finally:
        await engine.dispose()


async def wait_for_two_runtime_locks(r):
    async def observe():
        while True:
            async with r.world.sessions() as db:
                count = await db.scalar(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE usename=:role AND wait_event_type='Lock'"
                ), {"role": r.role})
            if count >= 2:
                return
            await asyncio.sleep(0.01)
    await asyncio.wait_for(observe(), 5)


async def issue_key(w, org=None, permissions=None):
    async with w.sessions() as db:
        key, raw = await APIKeyService(db).create_api_key(
            org_id=(org or w.org_a).id, name="isolated bootstrap",
            permissions=["device:register"] if permissions is None else permissions,
            created_by=w.users["org_admin" if org is None else "foreign"].id, key_type="agent",
        )
        await db.commit()
        return key, raw


async def issue_device(w):
    async with w.sessions() as db:
        result = await DeviceRegistrationService(db).register_device(
            w.org_a.id, DeviceRegisterRequest(fingerprint=w.suffix),
        )
        await db.commit()
        return result


@pytest.mark.parametrize("foreign_org", [False, True])
async def test_runtime_enrollment_and_reenrollment_uses_secret_tenant(runtime_http, foreign_org):
    w = runtime_http
    org = w.org_b if foreign_org else None
    key, raw = await issue_key(w, org)
    body = {"fingerprint": w.suffix, "model": "isolated-emulator"}
    first = await w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw}, json=body)
    assert first.status_code == 201, first.text
    second = await w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw}, json=body)
    assert second.status_code == 201, second.text
    assert first.json()["device_id"] == second.json()["device_id"]
    assert first.json()["is_new"] and not second.json()["is_new"]
    async with w.sessions() as db:
        rows = (await db.scalars(select(Device).where(Device.meta["fingerprint"].as_string() == w.suffix))).all()
        assert len(rows) == 1 and rows[0].org_id == key.org_id


@pytest.mark.parametrize("invalid", ["inactive", "expired", "permission", "unknown"])
async def test_runtime_enrollment_rejects_invalid_key(runtime_http, invalid):
    w = runtime_http
    key, raw = await issue_key(w, permissions=[] if invalid == "permission" else None)
    if invalid in {"inactive", "expired"}:
        values = {"is_active": False} if invalid == "inactive" else {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        async with w.sessions() as db:
            await db.execute(update(APIKey).where(APIKey.id == key.id).values(**values))
            await db.commit()
    response = await w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw + "x" if invalid == "unknown" else raw}, json={"fingerprint": w.suffix})
    assert response.status_code == (403 if invalid == "permission" else 401), response.text
    async with w.sessions() as db:
        assert await db.scalar(select(Device.id).where(Device.meta["fingerprint"].as_string() == w.suffix)) is None


async def test_runtime_refresh_rotates_once_and_child_is_usable(runtime_http):
    w = runtime_http
    enrolled = await issue_device(w)
    first = await w.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token})
    assert first.status_code == 200, first.text
    replay = await w.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token})
    assert replay.status_code == 401
    child = await w.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + first.json()["refresh_token"]})
    assert child.status_code == 200 and child.json()["device_id"] == str(enrolled.device_id)


@pytest.mark.parametrize("invalid", ["inactive", "expired", "unknown"])
async def test_runtime_refresh_rejects_invalid_credential(runtime_http, invalid):
    w = runtime_http
    enrolled = await issue_device(w)
    if invalid != "unknown":
        values = {"is_active": False} if invalid == "inactive" else {"refresh_token_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        async with w.sessions() as db:
            await db.execute(update(Device).where(Device.id == enrolled.device_id).values(**values))
            await db.commit()
    response = await w.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token + ("x" if invalid == "unknown" else "")})
    assert response.status_code == 401


async def test_runtime_concurrent_same_fingerprint_creates_one_device(runtime_parallel):
    r = runtime_parallel
    w = r.world
    key, raw = await issue_key(w)
    async with w.sessions() as holder:
        await holder.scalar(select(APIKey).where(APIKey.id == key.id).with_for_update())
        pending = [asyncio.create_task(
            w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw}, json={"fingerprint": w.suffix})
        ) for _ in range(3)]
        try:
            await wait_for_two_runtime_locks(r)
            await holder.commit()
            responses = await asyncio.wait_for(asyncio.gather(*pending), 5)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    assert [r.status_code for r in responses] == [201] * 3
    assert len({r.json()["device_id"] for r in responses}) == 1
    assert sum(r.json()["is_new"] for r in responses) == 1
    # Re-enrollment intentionally rotates again; it does not promise identical tokens.


async def test_runtime_concurrent_refresh_has_one_winner(runtime_parallel):
    r = runtime_parallel
    w = r.world
    enrolled = await issue_device(w)
    async with w.sessions() as holder:
        await holder.scalar(select(Device).where(Device.id == enrolled.device_id).with_for_update())
        pending = [asyncio.create_task(
            w.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token})
        ) for _ in range(2)]
        try:
            await wait_for_two_runtime_locks(r)
            await holder.commit()
            responses = await asyncio.wait_for(asyncio.gather(*pending), 5)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    assert sorted(r.status_code for r in responses) == [200, 401]


async def test_runtime_new_session_cannot_enumerate_credentials_after_auth(runtime_http, runtime_db):
    w = runtime_http
    _, raw = await issue_key(w)
    response = await w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw}, json={"fingerprint": w.suffix})
    assert response.status_code == 201, response.text
    async with runtime_db.sessions() as db:
        assert await db.scalar(text("SELECT count(*) FROM api_keys")) == 0
        assert await db.scalar(text("SELECT count(*) FROM devices")) == 0
        assert await db.scalar(text("SELECT current_setting('app.current_org_id', true)")) in (None, "")
    async with w.sessions() as db:
        assert (await db.scalar(select(APIKey).where(APIKey.key_hash == hashlib.sha256(raw.encode()).hexdigest()))).last_used_at is not None


@pytest.mark.parametrize("kind", ["api_key", "device_refresh"])
async def test_credential_resolver_is_narrow_and_does_not_change_session_scope(runtime_db, kind):
    r = runtime_db
    w = r.world
    raw = (await issue_key(w))[1] if kind == "api_key" else (await issue_device(w)).refresh_token
    name = "api_key_org" if kind == "api_key" else "device_refresh_org"
    lookup = text(f"SELECT sphere_auth.{name}(:hash)")
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    async with r.sessions() as db:
        await db.execute(text("CREATE TEMP TABLE api_keys (org_id uuid, key_hash text)"))
        await db.execute(text("CREATE TEMP TABLE devices (org_id uuid, refresh_token_hash text)"))
        await db.execute(text("SELECT set_config('search_path', 'pg_temp, public', true)"))
        assert await db.scalar(lookup, {"hash": token_hash}) == w.org_a.id
        for bad in [None, "", token_hash[:12], "0" * 64, token_hash + "'"]:
            assert await db.scalar(lookup, {"hash": bad}) is None
        assert await db.scalar(text("SELECT current_user")) == r.role
        assert await db.scalar(text("SELECT current_setting('row_security')")) == "on"
        assert await db.scalar(text("SELECT count(*) FROM public.api_keys")) == 0
        assert await db.scalar(text("SELECT count(*) FROM public.devices")) == 0


@pytest.mark.parametrize("name", ["api_key_org", "device_refresh_org"])
async def test_credential_resolver_requires_explicit_execute_and_protects_owner(runtime_db, name):
    r = runtime_db
    async with r.world.sessions() as owner:
        row = (await owner.execute(text("""
            SELECT p.prosecdef, p.proconfig,
                EXISTS(SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0) AS public_grant
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='sphere_auth' AND p.proname=:name
        """), {"name": name})).one()
        assert row.prosecdef and not row.public_grant
        assert set(row.proconfig) == {"search_path=pg_catalog, pg_temp", "row_security=off"}
        await owner.execute(text(f'REVOKE EXECUTE ON FUNCTION sphere_auth.{name}(text) FROM "{r.role}"'))
        await owner.commit()
    async with r.sessions() as db:
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.scalar(text(f"SELECT sphere_auth.{name}(:hash)"), {"hash": "0" * 64})
        await db.rollback()
        with pytest.raises(DBAPIError, match="must be owner|permission denied"):
            await db.execute(text(f"ALTER FUNCTION sphere_auth.{name}(text) SECURITY INVOKER"))


async def test_failed_refresh_commit_keeps_original_credential_usable(runtime_http, runtime_db, monkeypatch):
    w = runtime_http
    enrolled = await issue_device(w)

    async def faulting_db():
        async with runtime_db.sessions() as db:
            async def fail_commit():
                await db.flush()
                await db.execute(text("SELECT 1/0"))
            monkeypatch.setattr(db, "commit", fail_commit)
            yield db
    app.dependency_overrides[get_db] = faulting_db
    with pytest.raises(DBAPIError, match="division by zero"):
        await w.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token})

    async def healthy_db():
        async with runtime_db.sessions() as db:
            yield db
    app.dependency_overrides[get_db] = healthy_db
    retry = await w.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token})
    assert retry.status_code == 200, retry.text
