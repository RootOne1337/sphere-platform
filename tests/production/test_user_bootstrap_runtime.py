"""User login/refresh/MFA must bootstrap tenant context under actual RLS."""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_device_bootstrap_runtime import runtime_parallel, wait_for_two_runtime_locks  # noqa: F401

from backend.core.security import decode_access_token, hash_password
from backend.database.engine import get_db
from backend.main import app
from backend.models.refresh_token import RefreshToken
from backend.models.user import User
from backend.services.auth_service import AuthService
from backend.services.cache_service import CacheService

PASSWORD = "Isolated-audit-password-2026!"
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture
def user_runtime(runtime_db, monkeypatch):
    async def request_db():
        async with runtime_db.sessions() as db:
            yield db
    app.dependency_overrides[get_db] = request_db
    original = CacheService.check_rate_limit

    async def isolated_rate_limit(self, identifier, **kwargs):
        return await original(self, identifier + ":" + runtime_db.world.suffix, **kwargs)
    monkeypatch.setattr(CacheService, "check_rate_limit", isolated_rate_limit)
    return runtime_db


async def prepare_user(w, role="org_admin", mfa=False):
    async with w.sessions() as db:
        user = await db.get(User, w.users[role].id)
        user.password_hash = PASSWORD_HASH
        user.mfa_enabled = mfa
        user.mfa_secret = pyotp.random_base32() if mfa else None
        await db.commit()
    return user


async def pair(w, user):
    async with w.sessions() as db:
        return await AuthService(db, CacheService())._issue_tokens(await db.get(User, user.id))


async def token_count(w, user):
    async with w.sessions() as db:
        return await db.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user.id))


async def unscoped(r):
    async with r.sessions() as db:
        assert await db.scalar(text("SELECT current_user")) == r.role
        assert await db.scalar(text("SELECT nullif(current_setting('app.current_org_id',true),'')")) is None
        assert await db.scalar(select(func.count()).select_from(User)) == 0
        assert await db.scalar(select(func.count()).select_from(RefreshToken)) == 0


@pytest.mark.parametrize("role", ["org_admin", "foreign"])
async def test_runtime_login_me_refresh_logout_chain(user_runtime, role):
    r = user_runtime
    w = r.world
    user = await prepare_user(w, role)
    login = await w.client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD},
                                headers={"X-Org-Id": str(w.org_b.id if role == "org_admin" else w.org_a.id)})
    assert login.status_code == 200, login.text
    first = login.json()
    claims = decode_access_token(first["access_token"])
    assert (claims["sub"], claims["org_id"]) == (str(user.id), str(user.org_id))
    me = await w.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + first["access_token"]})
    assert me.status_code == 200 and me.json()["id"] == str(user.id)
    refreshed = await w.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": first["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    second = refreshed.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert (await w.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": first["refresh_token"]})).status_code == 401
    logout = await w.client.post("/api/v1/auth/logout", headers={
        "Authorization": "Bearer " + second["access_token"], "X-Refresh-Token": second["refresh_token"],
    })
    assert logout.status_code == 204
    assert (await w.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": second["refresh_token"]})).status_code == 401
    assert (await w.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + second["access_token"]})).status_code == 401
    async with w.sessions() as db:
        assert (await db.get(User, user.id)).last_login_at is not None
        tokens = (await db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))).all()
        assert len(tokens) == 2 and all(t.revoked for t in tokens)
    await unscoped(r)


@pytest.mark.parametrize("rejected", ["password", "inactive", "unknown"])
async def test_runtime_login_denials_issue_nothing(user_runtime, rejected):
    r = user_runtime
    user = await prepare_user(r.world)
    if rejected == "inactive":
        async with r.world.sessions() as db:
            (await db.get(User, user.id)).is_active = False
            await db.commit()
    response = await r.world.client.post("/api/v1/auth/login", json={
        "email": "unknown-" + user.email if rejected == "unknown" else user.email,
        "password": "wrong-password" if rejected == "password" else PASSWORD,
    })
    assert response.status_code == 401
    assert await token_count(r.world, user) == 0
    await unscoped(r)


@pytest.mark.parametrize("source", ["cookie", "header", "json"])
async def test_runtime_refresh_opaque_sources_and_child(user_runtime, source):
    r = user_runtime
    user = await prepare_user(r.world)
    first = await pair(r.world, user)
    kwargs = {"cookie": {"headers": {"Cookie": "refresh_token=" + first["refresh_token"]}},
              "header": {"headers": {"X-Refresh-Token": first["refresh_token"]}},
              "json": {"json": {"refresh_token": first["refresh_token"]}}}[source]
    response = await r.world.client.post("/api/v1/auth/refresh", **kwargs)
    assert response.status_code == 200, response.text
    child = response.json()["refresh_token"]
    assert (await r.world.client.post("/api/v1/auth/refresh", **kwargs)).status_code == 401
    assert (await r.world.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": child})).status_code == 200
    await unscoped(r)


@pytest.mark.parametrize("rejected", ["revoked", "expired", "inactive", "moved", "unknown"])
async def test_runtime_refresh_denials_do_not_issue_child(user_runtime, rejected):
    r = user_runtime
    user = await prepare_user(r.world)
    issued = await pair(r.world, user)
    token = issued["refresh_token"]
    async with r.world.sessions() as db:
        rt = await db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))
        if rejected == "revoked":
            rt.revoked = True
        elif rejected == "expired":
            rt.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif rejected == "inactive":
            (await db.get(User, user.id)).is_active = False
        elif rejected == "moved":
            (await db.get(User, user.id)).org_id = r.world.org_b.id
        else:
            token = "unknown-refresh-token"
        await db.commit()
    response = await r.world.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": token})
    assert response.status_code == 401
    assert await token_count(r.world, user) == 1
    await unscoped(r)


@pytest.mark.parametrize("source", ["cookie", "header"])
async def test_runtime_logout_really_revokes_sql_token(user_runtime, source):
    r = user_runtime
    user = await prepare_user(r.world)
    issued = await pair(r.world, user)
    headers = {"Authorization": "Bearer " + issued["access_token"]}
    headers.update({"Cookie": "refresh_token=" + issued["refresh_token"]} if source == "cookie" else {"X-Refresh-Token": issued["refresh_token"]})
    response = await r.world.client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204
    async with r.world.sessions() as db:
        rt = await db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))
        assert rt.revoked and rt.revoked_at is not None
    await unscoped(r)


async def test_runtime_mfa_login_consumes_once(user_runtime):
    r = user_runtime
    user = await prepare_user(r.world, mfa=True)
    login = await r.world.client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["mfa_required"] is True
    assert "access_token" not in login.json()
    assert await token_count(r.world, user) == 0
    request = {"state_token": login.json()["state_token"], "code": pyotp.TOTP(user.mfa_secret).now()}
    response = await r.world.client.post("/api/v1/auth/login/mfa", json=request)
    assert response.status_code == 200, response.text
    assert decode_access_token(response.json()["access_token"])["org_id"] == str(user.org_id)
    assert (await r.world.client.post("/api/v1/auth/login/mfa", json=request)).status_code == 401
    assert await token_count(r.world, user) == 1
    await unscoped(r)


async def test_runtime_mfa_issued_by_another_request_session(user_runtime):
    r = user_runtime
    user = await prepare_user(r.world, mfa=True)
    async with r.world.sessions() as db:
        login = await AuthService(db, CacheService()).login(user.email, PASSWORD, r.world.suffix)
    response = await r.world.client.post("/api/v1/auth/login/mfa", json={
        "state_token": login["state_token"], "code": pyotp.TOTP(user.mfa_secret).now(),
    })
    assert response.status_code == 200, response.text
    assert await token_count(r.world, user) == 1
    await unscoped(r)


async def test_runtime_parallel_refresh_has_one_winner(runtime_parallel):
    r = runtime_parallel
    user = await prepare_user(r.world)
    issued = await pair(r.world, user)
    digest = hashlib.sha256(issued["refresh_token"].encode()).hexdigest()
    calls = []
    try:
        async with r.world.sessions() as blocker:
            await blocker.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest).with_for_update())
            calls = [asyncio.create_task(r.world.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": issued["refresh_token"]})) for _ in range(2)]
            await wait_for_two_runtime_locks(r)
            await blocker.commit()
        responses = await asyncio.gather(*calls)
        assert sorted(response.status_code for response in responses) == [200, 401]
        child = next(response.json()["refresh_token"] for response in responses if response.status_code == 200)
        assert (await r.world.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": child})).status_code == 200
        assert await token_count(r.world, user) == 3
    finally:
        for call in calls:
            if not call.done():
                call.cancel()
        await asyncio.gather(*calls, return_exceptions=True)


@pytest.mark.parametrize("kind", ["login", "refresh"])
async def test_user_resolver_returns_only_org_and_ignores_temp_shadow(user_runtime, kind):
    r = user_runtime
    user = await prepare_user(r.world)
    issued = await pair(r.world, user)
    name = "user_login_org" if kind == "login" else "user_refresh_org"
    value = user.email if kind == "login" else hashlib.sha256(issued["refresh_token"].encode()).hexdigest()
    async with r.sessions() as db:
        await db.execute(text("CREATE TEMP TABLE users (org_id uuid, email text)"))
        await db.execute(text("CREATE TEMP TABLE refresh_tokens (org_id uuid, token_hash text)"))
        await db.execute(text("SELECT set_config('search_path','pg_temp, public',true)"))
        lookup = text(f"SELECT sphere_auth.{name}(:value)")
        assert await db.scalar(lookup, {"value": value}) == user.org_id
        for bad in [None, "", value[:10], value + "' OR '1'='1", "x" * 256]:
            assert await db.scalar(lookup, {"value": bad}) is None
        assert await db.scalar(text("SELECT current_user")) == r.role
        assert await db.scalar(text("SELECT current_setting('row_security')")) == "on"
        assert await db.scalar(text("SELECT count(*) FROM public.users")) == 0
        assert await db.scalar(text("SELECT count(*) FROM public.refresh_tokens")) == 0


@pytest.mark.parametrize("name", ["user_login_org", "user_refresh_org"])
async def test_user_resolver_requires_grant_and_keeps_owner_protected(user_runtime, name):
    r = user_runtime
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
            await db.scalar(text(f"SELECT sphere_auth.{name}(:value)"), {"value": "unknown"})
        await db.rollback()
        with pytest.raises(DBAPIError, match="must be owner|permission denied"):
            await db.execute(text(f"ALTER FUNCTION sphere_auth.{name}(text) SECURITY INVOKER"))


@pytest.mark.parametrize("rejected", ["moved", "inactive", "disabled", "legacy", "bad_json", "array", "missing_org", "invalid_uuid"])
async def test_runtime_mfa_rejects_changed_identity_and_invalid_state(user_runtime, rejected):
    r = user_runtime
    user = await prepare_user(r.world, mfa=True)
    login = await r.world.client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200
    state = login.json()["state_token"]
    key = f"mfa:state:v2:{state}"
    if rejected in {"moved", "inactive", "disabled"}:
        async with r.world.sessions() as db:
            current = await db.get(User, user.id)
            if rejected == "moved":
                current.org_id = r.world.org_b.id
            elif rejected == "inactive":
                current.is_active = False
            else:
                current.mfa_enabled = False
            await db.commit()
    elif rejected == "legacy":
        await r.world.redis.delete(key)
        await r.world.redis.set(f"mfa:state:{state}", str(user.id), ex=300)
    else:
        value = {"bad_json": "invalid-json", "array": "[]", "missing_org": json.dumps({"user_id": str(user.id)}),
                 "invalid_uuid": json.dumps({"user_id": str(user.id), "org_id": "invalid"})}[rejected]
        await r.world.redis.set(key, value, ex=300)
    response = await r.world.client.post("/api/v1/auth/login/mfa", json={
        "state_token": state, "code": pyotp.TOTP(user.mfa_secret).now(),
    })
    assert response.status_code == 401, response.text
    assert await token_count(r.world, user) == 0
    await unscoped(r)


async def test_runtime_mfa_concurrent_consumption_issues_one_session(runtime_parallel, monkeypatch):
    r = runtime_parallel
    user = await prepare_user(r.world, mfa=True)
    async with r.world.sessions() as db:
        login = await AuthService(db, CacheService()).login(user.email, PASSWORD, r.world.suffix)
    key = f"mfa:state:v2:{login['state_token']}"
    original = CacheService.get
    both_read = asyncio.Event()
    reads = []

    async def overlapping_get(self, lookup):
        value = await original(self, lookup)
        if lookup == key:
            reads.append(value)
            if len(reads) == 2:
                both_read.set()
            await asyncio.wait_for(both_read.wait(), 3)
        return value
    monkeypatch.setattr(CacheService, "get", overlapping_get)
    request = {"state_token": login["state_token"], "code": pyotp.TOTP(user.mfa_secret).now()}
    responses = await asyncio.wait_for(asyncio.gather(*[
        r.world.client.post("/api/v1/auth/login/mfa", json=request) for _ in range(2)
    ]), 5)
    assert len(reads) == 2 and reads[0] == reads[1] and reads[0] is not None
    assert sorted(response.status_code for response in responses) == [200, 401]
    assert await token_count(r.world, user) == 1
    assert not await r.world.redis.exists(key)


@pytest.mark.parametrize("flow", ["login", "refresh", "mfa"])
async def test_runtime_auth_sql_abort_and_recovery(user_runtime, monkeypatch, flow):
    r = user_runtime
    user = await prepare_user(r.world, mfa=flow == "mfa")
    login_request = {"email": user.email, "password": PASSWORD}
    initial_count = 0
    if flow == "refresh":
        issued = await pair(r.world, user)
        request = {"headers": {"X-Refresh-Token": issued["refresh_token"]}}
        path = "/api/v1/auth/refresh"
        initial_count = 1
    elif flow == "mfa":
        challenge = await r.world.client.post("/api/v1/auth/login", json=login_request)
        request = {"json": {"state_token": challenge.json()["state_token"], "code": pyotp.TOTP(user.mfa_secret).now()}}
        path = "/api/v1/auth/login/mfa"
    else:
        path, request = "/api/v1/auth/login", {"json": login_request}
    reached = []

    async def failed_db():
        async with r.sessions() as db:
            async def abort_commit():
                await db.flush()
                reached.append(True)
                await db.execute(text("SELECT 1/0"))
            monkeypatch.setattr(db, "commit", abort_commit)
            yield db
    app.dependency_overrides[get_db] = failed_db
    with pytest.raises(DBAPIError, match="division by zero"):
        await r.world.client.post(path, **request)
    assert reached == [True]
    assert await token_count(r.world, user) == initial_count

    async def healthy_db():
        async with r.sessions() as db:
            yield db
    app.dependency_overrides[get_db] = healthy_db
    if flow == "mfa":
        # DEL won before SQL failed. No blind replay or duplicate issuance; a
        # new password step is required to obtain a fresh challenge.
        assert (await r.world.client.post(path, **request)).status_code == 401
        challenge = await r.world.client.post("/api/v1/auth/login", json=login_request)
        request["json"]["state_token"] = challenge.json()["state_token"]
    retry = await r.world.client.post(path, **request)
    assert retry.status_code == 200, retry.text
    assert await token_count(r.world, user) == initial_count + 1
    await unscoped(r)
