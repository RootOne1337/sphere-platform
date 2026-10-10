"""A real binary Redis presence read must survive the committed HTTP 202 path."""
import os
import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from backend.database import redis_client
from backend.models.task import Task
from backend.models.task_batch import TaskBatch
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.batch_admission import BatchAdmissionWorker
from backend.services.device_status_cache import DeviceStatusCache


async def test_broadcast_202_uses_binary_presence_and_durable_tenant_plan(world, monkeypatch):
    # A separate pool is required: reusing a text pool would retain UTF-8 decoding.
    binary = Redis.from_url(os.environ["REDIS_URL"], decode_responses=False)
    cache = DeviceStatusCache(binary)
    keys = [cache._key(str(device.id)) for device in (world.dev_a, world.dev_a2, world.dev_b)]
    monkeypatch.setattr(redis_client, "redis", world.redis)
    monkeypatch.setattr(redis_client, "redis_binary", binary)
    monkeypatch.setattr("backend.api.v1.batches.router.AsyncSessionLocal", world.sessions)
    try:
        for device, status in [(world.dev_a, "online"), (world.dev_a2, "busy"), (world.dev_b, "online")]:
            await cache.set_status(str(device.id), DeviceLiveStatus(device_id=str(device.id), status=status))
        with pytest.raises(UnicodeDecodeError):
            await world.redis.get(keys[0])
        response = await world.client.post("/api/v1/batches/broadcast", headers=world.auth(world.users["org_admin"]),
            json={"script_id": str(world.script.id), "wave_size": 1, "wave_delay_ms": 0, "jitter_ms": 0})
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["online_devices"] == body["total"] == 1
        batch_id = uuid.UUID(body["id"])
        async with world.sessions() as db:
            stored = await db.get(TaskBatch, batch_id)
            assert stored.org_id == world.org_a.id and stored.script_version_id == world.version.id
            assert [[item["device_id"] for item in wave] for wave in stored.wave_plan] == [[str(world.dev_a.id)]]
            assert await db.scalar(select(func.count()).select_from(TaskBatch).where(TaskBatch.org_id == world.org_a.id)) == 1
        await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
        async with world.sessions() as db:
            tasks = list(await db.scalars(select(Task).where(Task.batch_id == batch_id)))
            assert len(tasks) == 1 and tasks[0].device_id == world.dev_a.id
            assert tasks[0].script_version_id == world.version.id
    finally:
        await binary.delete(*keys)
        await binary.aclose()
