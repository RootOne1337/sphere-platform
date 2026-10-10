"""Lost refresh responses must recover from SQL under real non-owner credentials."""

import asyncio
import base64
import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database.engine import get_db
from backend.main import app
from backend.models import Device
from backend.schemas.device_register import DeviceRegisterRequest
from backend.services.device_registration_service import DeviceRegistrationService
from tests.production.test_agent_tenant_runtime import websocket
from tests.production.test_device_bootstrap_runtime import issue_device, wait_for_two_runtime_locks

PATH = "/api/v1/devices/refresh"


def headers(token, request_id=None):
    result = {"Cookie": "refresh_token=" + token}
    if request_id is not None:
        result["X-Refresh-Request-Id"] = str(request_id)
    return result


@pytest_asyncio.fixture
async def retry_http(runtime_db):
    engine = create_async_engine(runtime_db.engine.url, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def request_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = request_db
    try:
        yield SimpleNamespace(world=runtime_db.world, role=runtime_db.role,
                              engine=engine, sessions=sessions, request_db=request_db)
    finally:
        await engine.dispose()


async def test_lost_committed_response_recovers_after_connection_pool_restart(retry_http):
    r, w = retry_http, retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    discarded = []

    class LoseResponse(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            async with httpx.ASGITransport(app=app) as transport:
                response = await transport.handle_async_request(request)
                await response.aread()
                assert response.status_code == 200
                discarded.append(response.json())
                await response.aclose()
            raise httpx.ReadError("synthetic response loss after completed SQL commit")

    async with httpx.AsyncClient(transport=LoseResponse(), base_url="http://audit.local") as client:
        with pytest.raises(httpx.ReadError):
            await client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    await r.engine.dispose()  # Next request uses fresh sessions/connections, no process cache.
    recovered = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert recovered.status_code == 200
    assert recovered.json()["device_id"] == str(enrolled.device_id)
    assert recovered.json()["refresh_token"] == discarded[0]["refresh_token"]
    child = await w.client.post(PATH, headers=headers(recovered.json()["refresh_token"], uuid.uuid4()))
    assert child.status_code == 200
    assert (await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))).status_code == 401


async def test_recovered_access_authenticates_actual_asgi_ws_for_the_same_device(retry_http, monkeypatch):
    r, w = retry_http, retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    assert (await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))).status_code == 200
    retry = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert retry.status_code == 200
    monkeypatch.setattr("backend.api.ws.android.router.AsyncSessionLocal", r.sessions)
    monkeypatch.setattr("backend.api.ws.android.router.get_redis_binary", AsyncMock(return_value=w.redis))
    manager = SimpleNamespace(connect=AsyncMock(return_value="recovery-session"), disconnect=AsyncMock(return_value=False))
    monkeypatch.setattr("backend.api.ws.android.router.get_connection_manager", lambda: manager)
    monkeypatch.setattr("backend.api.ws.android.router.DeviceStatusCache", lambda _: SimpleNamespace(set_status=AsyncMock()))
    monkeypatch.setattr("backend.websocket.heartbeat.HeartbeatManager", lambda *a, **kw: SimpleNamespace(start=AsyncMock(), stop=AsyncMock()))
    for module, factory in [("pubsub_router", "get_pubsub_router"), ("event_publisher", "get_event_publisher"), ("offline_queue", "get_offline_queue"), ("stream_bridge", "get_stream_bridge")]:
        monkeypatch.setattr(f"backend.websocket.{module}.{factory}", lambda: None)
    for attempt in range(2):
        sent = await websocket(enrolled.device_id, retry.json()["access_token"])
        assert manager.connect.await_count == attempt + 1, sent
        assert manager.connect.call_args.args[1:] == (str(enrolled.device_id), "android", str(w.org_a.id))
        assert not any(message["type"] == "websocket.close" for message in sent)
    await websocket(w.dev_b.id, retry.json()["access_token"])
    assert manager.connect.await_count == 2


async def test_retry_keeps_successor_expiry_and_identity(retry_http):
    w = retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    first = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert first.status_code == 200
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    async with w.sessions() as db:
        await db.execute(update(Device).where(Device.id == enrolled.device_id).values(refresh_token_expires_at=expires))
        await db.commit()
    for _ in range(3):
        response = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
        assert response.status_code == 200
        assert response.json()["refresh_token"] == first.json()["refresh_token"]
        assert response.json()["device_id"] == str(enrolled.device_id)
    async with w.sessions() as db:
        assert await db.scalar(select(Device.refresh_token_expires_at).where(Device.id == enrolled.device_id)) == expires


@pytest.mark.parametrize("same_intent", [True, False])
async def test_concurrent_refresh_has_one_successor_with_observed_sql_waiters(retry_http, same_intent):
    r, w = retry_http, retry_http.world
    enrolled = await issue_device(w)
    intents = [uuid.uuid4(), uuid.uuid4()]
    if same_intent:
        intents[1] = intents[0]
    async with w.sessions() as holder:
        await holder.scalar(select(Device).where(Device.id == enrolled.device_id).with_for_update())
        pending = [asyncio.create_task(w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))) for intent in intents]
        try:
            await wait_for_two_runtime_locks(r)
            await holder.commit()
            responses = await asyncio.wait_for(asyncio.gather(*pending), 5)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    assert sorted(response.status_code for response in responses) == ([200, 200] if same_intent else [200, 401])
    successors = [response.json()["refresh_token"] for response in responses if response.status_code == 200]
    assert len(set(successors)) == 1


@pytest.mark.parametrize("invalid", ["missing_id", "different_id", "different_token", "stored_hash"])
async def test_receipt_requires_both_original_secret_and_matching_intent(retry_http, invalid):
    w = retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    assert (await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))).status_code == 200
    raw = enrolled.refresh_token
    if invalid == "different_token":
        raw += "x"
    if invalid == "stored_hash":
        raw = hashlib.sha256(raw.encode()).hexdigest()
    attempted = None if invalid == "missing_id" else uuid.uuid4() if invalid == "different_id" else intent
    assert (await w.client.post(PATH, headers=headers(raw, attempted))).status_code == 401


@pytest.mark.parametrize("change", ["inactive", "expired", "reenrolled", "child_consumed"])
async def test_recovery_does_not_restore_revoked_or_superseded_credentials(retry_http, change):
    w = retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    first = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert first.status_code == 200
    if change == "child_consumed":
        assert (await w.client.post(PATH, headers=headers(first.json()["refresh_token"]))).status_code == 200
    else:
        async with w.sessions() as db:
            if change == "reenrolled":
                again = await DeviceRegistrationService(db).register_device(w.org_a.id, DeviceRegisterRequest(fingerprint=w.suffix))
                assert again.device_id == enrolled.device_id
            else:
                values = {"is_active": False} if change == "inactive" else {"refresh_token_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
                await db.execute(update(Device).where(Device.id == enrolled.device_id).values(**values))
            await db.commit()
    assert (await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))).status_code == 401


async def test_recovery_ignores_supplied_foreign_org_header_and_cannot_resolve_other_device(retry_http):
    w = retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    assert (await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))).status_code == 200
    request_headers = {**headers(enrolled.refresh_token, intent), "X-Organization-Id": str(w.org_b.id), "X-Device-Id": str(w.dev_b.id)}
    response = await w.client.post(PATH, headers=request_headers)
    assert response.status_code == 200
    assert response.json()["device_id"] == str(enrolled.device_id)
    async with retry_http.sessions() as db:
        assert await db.scalar(text("SELECT count(*) FROM devices")) == 0


async def test_sql_failure_before_commit_keeps_retry_usable(retry_http, monkeypatch):
    r, w = retry_http, retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()

    async def failing_db():
        async with r.sessions() as db:
            async def fail_commit():
                await db.flush()
                await db.execute(text("SELECT 1/0"))
            monkeypatch.setattr(db, "commit", fail_commit)
            yield db

    app.dependency_overrides[get_db] = failing_db
    with pytest.raises(DBAPIError):
        await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    app.dependency_overrides[get_db] = r.request_db
    first = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    second = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert [first.status_code, second.status_code] == [200, 200]
    assert first.json()["refresh_token"] == second.json()["refresh_token"]


async def test_commit_ack_failure_recovers_committed_successor(retry_http, monkeypatch):
    r, w = retry_http, retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()

    async def failing_ack_db():
        async with r.sessions() as db:
            real_commit = db.commit

            async def fail_after_commit():
                await real_commit()
                raise OSError("synthetic lost commit acknowledgement")

            monkeypatch.setattr(db, "commit", fail_after_commit)
            yield db

    app.dependency_overrides[get_db] = failing_ack_db
    with pytest.raises(OSError, match="synthetic"):
        await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    async with w.sessions() as db:
        committed_hash = await db.scalar(select(Device.refresh_token_hash).where(Device.id == enrolled.device_id))
        assert committed_hash != hashlib.sha256(enrolled.refresh_token.encode()).hexdigest()
    app.dependency_overrides[get_db] = r.request_db
    await r.engine.dispose()
    retry = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert retry.status_code == 200
    assert hashlib.sha256(retry.json()["refresh_token"].encode()).hexdigest() == committed_hash


@pytest.mark.parametrize("invalid", ["not-a-uuid", "x" * 100])
async def test_malformed_refresh_intent_does_not_consume_credential(retry_http, invalid):
    w = retry_http.world
    enrolled = await issue_device(w)
    assert (await w.client.post(PATH, headers=headers(enrolled.refresh_token, invalid))).status_code == 422
    assert (await w.client.post(PATH, headers=headers(enrolled.refresh_token, uuid.uuid4()))).status_code == 200


@pytest.mark.parametrize("change", ["inactive", "expired", "reenrolled"])
async def test_locked_recovery_observes_credential_changes(retry_http, change):
    r, w = retry_http, retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    assert (await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))).status_code == 200
    async with w.sessions() as holder:
        device = await holder.scalar(select(Device).where(Device.id == enrolled.device_id).with_for_update())
        pending = [asyncio.create_task(w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))) for _ in range(2)]
        try:
            await wait_for_two_runtime_locks(r)
            if change == "reenrolled":
                await DeviceRegistrationService(holder).register_device(w.org_a.id, DeviceRegisterRequest(fingerprint=w.suffix))
            elif change == "inactive":
                device.is_active = False
            else:
                device.refresh_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await holder.commit()
            responses = await asyncio.wait_for(asyncio.gather(*pending), 5)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    assert [response.status_code for response in responses] == [401, 401]


async def test_expiry_is_rechecked_after_lock_wait(retry_http, monkeypatch):
    from backend.services import device_registration_service as module

    r, w = retry_http, retry_http.world
    enrolled = await issue_device(w)
    offset = timedelta()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + offset

    monkeypatch.setattr(module, "datetime", Clock)
    async with w.sessions() as holder:
        await holder.scalar(select(Device).where(Device.id == enrolled.device_id).with_for_update())
        pending = [asyncio.create_task(w.client.post(PATH, headers=headers(enrolled.refresh_token, uuid.uuid4()))) for _ in range(2)]
        try:
            await wait_for_two_runtime_locks(r)
            offset = timedelta(days=365)
            await holder.commit()
            responses = await asyncio.wait_for(asyncio.gather(*pending), 5)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    assert [response.status_code for response in responses] == [401, 401]


async def test_stored_hash_and_known_request_id_cannot_derive_a_bearer(retry_http):
    w = retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    first = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert first.status_code == 200
    # Database exposure supplies only a hash, never the HKDF input secret.
    digest = HKDF(algorithm=hashes.SHA256(), length=32, salt=intent.bytes,
        info=b"sphere/device-refresh/v1\0" + w.org_a.id.bytes + enrolled.device_id.bytes,
    ).derive(hashlib.sha256(enrolled.refresh_token.encode()).digest())
    forged = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert forged != first.json()["refresh_token"]
    assert (await w.client.post(PATH, headers=headers(forged, uuid.uuid4()))).status_code == 401
    async with w.sessions() as db:
        device = await db.get(Device, enrolled.device_id)
        assert device.refresh_previous_token_hash == hashlib.sha256(enrolled.refresh_token.encode()).hexdigest()
        assert device.refresh_rotation_key_hash == hashlib.sha256(intent.bytes).hexdigest()
        assert device.refresh_token_hash == hashlib.sha256(first.json()["refresh_token"].encode()).hexdigest()


async def test_migration_roundtrip_preserves_function_grants_and_rolls_back_receipt_loss(retry_http):
    r, w = retry_http, retry_http.world
    enrolled = await issue_device(w)
    intent = uuid.uuid4()
    first = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert first.status_code == 200
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260910_device_refresh_retry.py"
    spec = importlib.util.spec_from_file_location("refresh_retry_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with w.engine.connect() as connection:
        transaction = await connection.begin()
        try:
            def roundtrip(db):
                with Operations.context(MigrationContext.configure(db)):
                    module.downgrade()
                    assert db.scalar(text("SELECT sphere_auth.device_refresh_org(:hash)"),
                        {"hash": hashlib.sha256(enrolled.refresh_token.encode()).hexdigest()}) is None
                    module.upgrade()
                assert db.scalar(text("SELECT has_function_privilege(:role, 'sphere_auth.device_refresh_org(text)', 'EXECUTE')"), {"role": r.role})
                assert db.scalar(text("""SELECT NOT EXISTS (
                    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
                    LATERAL aclexplode(p.proacl) a
                    WHERE n.nspname='sphere_auth' AND p.proname='device_refresh_org' AND a.grantee=0
                )"""))
            await connection.run_sync(roundtrip)
        finally:
            await transaction.rollback()  # Restore real receipt and schema, no downgrade committed.
    replay = await w.client.post(PATH, headers=headers(enrolled.refresh_token, intent))
    assert replay.status_code == 200
    assert replay.json()["refresh_token"] == first.json()["refresh_token"]
