"""Regressions for binary presence and the response after durable batch commit."""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.database import redis_client
from backend.models.device import Device
from backend.models.organization import Organization
from backend.models.script import ScriptVersion
from backend.models.task import Task
from backend.models.task_batch import TaskBatch
from backend.schemas.batch import BroadcastBatchRequest
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.batch_service import BatchService
from backend.services.device_status_cache import DeviceStatusCache


@pytest.fixture
async def test_user(test_user, db_session):
    # Use a supported permission-bearing role, without bypassing auth/RBAC.
    test_user.role = "org_admin"
    await db_session.flush()
    return test_user


@pytest.fixture(autouse=True)
def local_audit_session(monkeypatch, db_session):
    from backend.middleware import audit

    @asynccontextmanager
    async def sessions():
        yield db_session

    monkeypatch.setattr(audit, "AsyncSessionLocal", sessions)


@pytest.fixture
async def presence(monkeypatch):
    server = FakeServer()
    binary = FakeRedis(server=server, decode_responses=False)
    text = FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(redis_client, "redis", text)
    monkeypatch.setattr(redis_client, "redis_binary", binary)
    yield binary
    await binary.aclose()
    await text.aclose()


async def test_broadcast_reads_msgpack_and_returns_202_for_the_committed_plan(
    authenticated_client, db_session, test_org, test_device, test_script, presence,
):
    version = ScriptVersion(org_id=test_org.id, script_id=test_script.id, dag={"nodes": []})
    db_session.add(version)
    await db_session.flush()
    test_script.current_version_id = version.id
    foreign_org = Organization(name="Other broadcast tenant", slug="other-broadcast-tenant")
    db_session.add(foreign_org)
    await db_session.flush()
    devices = {
        "foreign": Device(org_id=foreign_org.id, name="foreign"),
        "inactive": Device(org_id=test_org.id, name="inactive", is_active=False),
        "busy": Device(org_id=test_org.id, name="busy"),
        "offline": Device(org_id=test_org.id, name="offline"),
        "missing": Device(org_id=test_org.id, name="missing"),
        "corrupt": Device(org_id=test_org.id, name="corrupt"),
    }
    db_session.add_all(devices.values())
    await db_session.flush()
    cache = DeviceStatusCache(presence)
    for device, status in [(test_device, "online"), (devices["foreign"], "online"),
                           (devices["inactive"], "online"), (devices["busy"], "busy"),
                           (devices["offline"], "offline")]:
        await cache.set_status(str(device.id), DeviceLiveStatus(device_id=str(device.id), status=status))
    await presence.set(cache._key(str(devices["corrupt"].id)), b"\xde\x00", ex=120)
    # A text Redis client must really fail on this fixture, not silently emulate bytes.
    with pytest.raises(UnicodeDecodeError):
        await redis_client.redis.get(cache._key(str(test_device.id)))

    response = await authenticated_client.post("/api/v1/batches/broadcast", json={
        "script_id": str(test_script.id), "wave_size": 1, "wave_delay_ms": 0,
        "jitter_ms": 0, "stagger_by_workstation": False,
    })
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["online_devices"] == body["total"] == 1
    assert body["succeeded"] == body["failed"] == 0
    batch = await db_session.get(TaskBatch, uuid.UUID(body["id"]))
    assert batch is not None and batch.script_version_id == version.id
    assert [[item["device_id"] for item in wave] for wave in batch.wave_plan] == [[str(test_device.id)]]
    assert await db_session.scalar(select(func.count()).select_from(TaskBatch)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Task)) == 0
    # No startup admission worker runs in this HTTP test; 202 proves the plan, not Android execution.


async def test_broadcast_response_supplies_online_count_before_validation(
    authenticated_client, test_org, test_script, test_user,
):
    from backend.api.v1.batches.router import get_batch_service
    from backend.main import app

    now = datetime.now(timezone.utc)
    batch = SimpleNamespace(id=uuid.uuid4(), org_id=test_org.id, script_id=test_script.id,
        name="Committed batch", status="running", total=2, succeeded=0, failed=0,
        wave_config={}, created_at=now, updated_at=now)
    service = SimpleNamespace(broadcast_batch=AsyncMock(return_value=(batch, 2)))
    app.dependency_overrides[get_batch_service] = lambda: service
    try:
        response = await authenticated_client.post("/api/v1/batches/broadcast", json={"script_id": str(test_script.id)})
    finally:
        app.dependency_overrides.pop(get_batch_service, None)
    assert response.status_code == 202, response.text
    assert response.json()["id"] == str(batch.id) and response.json()["online_devices"] == 2
    service.broadcast_batch.assert_awaited_once_with(BroadcastBatchRequest(script_id=test_script.id), test_org.id, test_user.id)


async def test_broadcast_with_no_online_target_creates_no_intent(db_session, test_org, test_user, test_device, presence):
    service = BatchService(db_session, AsyncMock())
    service.start_batch = AsyncMock()
    await DeviceStatusCache(presence).set_status(str(test_device.id), DeviceLiveStatus(device_id=str(test_device.id), status="busy"))
    with pytest.raises(HTTPException) as exc:
        await service.broadcast_batch(BroadcastBatchRequest(script_id=uuid.uuid4()), test_org.id, test_user.id)
    assert exc.value.status_code == 409
    service.start_batch.assert_not_awaited()
