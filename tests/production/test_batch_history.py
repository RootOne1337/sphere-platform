"""Read durable batch history without publishing commands to a device."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.models.device import Device
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch
from backend.services.batch_admission import advance_batch
from backend.services.task_service import TaskService


@pytest.mark.parametrize("size", [10, 100])
async def test_batch_detail_preserves_all_targets_and_cancellation_receipts(world, size):
    devices = [Device(org_id=world.org_a.id, name=f"batch-fixture-{index}") for index in range(size - 3)]
    async with world.sessions() as db:
        db.add_all(devices)
        await db.commit()

    # One tenant-owned target and one unknown target in the first wave. The
    # unknown ID is a rejected admission, so its planned UUID never becomes a task.
    target_ids = [world.dev_a.id, uuid.uuid4(), world.dev_a2.id, *(device.id for device in devices)]
    auth = world.auth(world.users["org_admin"])
    response = await world.client.post("/api/v1/batches", headers=auth, json={
        "script_id": str(world.script.id), "device_ids": list(map(str, target_ids)),
        "wave_size": 2, "wave_delay_ms": 0, "jitter_ms": 0, "stagger_by_workstation": False,
    })
    assert response.status_code == 202, response.text
    batch_id = uuid.UUID(response.json()["id"])
    url = f"/api/v1/batches/{batch_id}"

    response = await world.client.get(url, headers=auth)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["script_name"] == world.script.name
    assert first["script_version_id"] == str(world.version.id)
    assert first["wave_count"] == size // 2 and first["next_wave_index"] == 0
    assert first["target_counts"]["pending_admission"] == size
    assert [item["device_id"] for item in first["targets"]] == list(map(str, target_ids))
    assert all(item["task_id"] is None for item in first["targets"])

    assert await advance_batch(world.sessions, batch_id, world.org_a.id)
    async with world.sessions() as db:
        task = await db.scalar(select(Task).where(Task.batch_id == batch_id))
        assert task is not None
        task.status = TaskStatus.ASSIGNED
        await db.commit()

    response = await world.client.delete(url, headers=auth)
    assert response.status_code == 204, response.text
    response = await world.client.get(url, headers=auth)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == detail["admission_state"] == "cancelled"
    assert detail["next_wave_at"] is None
    admitted, rejected, waiting = detail["targets"][:3]
    assert admitted["device_name"] == world.dev_a.name and admitted["wave_index"] == 0
    assert admitted["task_id"] == str(task.id) and admitted["state"] == "assigned"
    assert admitted["cancel_requested_at"] is not None
    assert rejected["state"] == "rejected" and rejected["admission_http_status"] == 404
    assert rejected["task_id"] is None and rejected["device_name"] is None
    assert waiting["wave_index"] == 1 and waiting["state"] == "not_admitted_cancelled"
    assert waiting["task_id"] is None
    assert detail["target_counts"]["not_admitted_cancelled"] == size - 2
    assert sum(detail["target_counts"].values()) == size
    assert not await advance_batch(world.sessions, batch_id, world.org_a.id)


async def test_batch_history_is_tenant_scoped_and_legacy_targets_are_unknown(world):
    async with world.sessions() as db:
        legacy = TaskBatch(org_id=world.org_a.id, script_id=world.script.id, total=1)
        second = TaskBatch(org_id=world.org_a.id, script_id=world.script.id, total=0, status="cancelled")
        db.add_all([legacy, second])
        await db.commit()

    auth = world.auth(world.users["org_admin"])
    response = await world.client.get("/api/v1/batches", headers=auth, params={"per_page": 1})
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["total"] == first["pages"] == 2 and len(first["items"]) == 1
    response = await world.client.get("/api/v1/batches", headers=auth, params={"per_page": 1, "page": 2})
    assert response.status_code == 200, response.text
    assert {first["items"][0]["id"], response.json()["items"][0]["id"]} == {str(legacy.id), str(second.id)}
    response = await world.client.get("/api/v1/batches", headers=auth,
                                      params={"status": "cancelled", "script_id": str(world.script.id)})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(second.id)]

    foreign = world.auth(world.users["foreign"])
    response = await world.client.get("/api/v1/batches", headers=foreign)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    response = await world.client.get(f"/api/v1/batches/{legacy.id}", headers=foreign)
    assert response.status_code == 404, response.text

    viewer = world.auth(world.users["viewer"])
    response = await world.client.delete(f"/api/v1/batches/{legacy.id}", headers=viewer)
    assert response.status_code == 403, response.text
    response = await world.client.get(f"/api/v1/batches/{legacy.id}", headers=viewer)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["wave_count"] is detail["targets"] is detail["target_counts"] is None
    assert detail["admission_receipts"] == [] and detail["admission_state"] == "legacy_unknown"


@pytest.mark.parametrize("missing_version", [True, False])
async def test_dispatch_failure_updates_the_task_and_its_batch_in_the_same_commit(world, monkeypatch, missing_version):
    from backend.services import task_service

    async with world.sessions() as db:
        batch = TaskBatch(org_id=world.org_a.id, script_id=world.script.id, total=1, status="running")
        db.add(batch)
        await db.flush()
        task = Task(org_id=world.org_a.id, device_id=world.dev_a.id, script_id=world.script.id,
                    script_version_id=None if missing_version else world.version.id, batch_id=batch.id,
                    status=TaskStatus.QUEUED)
        db.add(task)
        await db.commit()

    monkeypatch.setattr(task_service, "pointer_path_admission_error", lambda *_: "unsupported_fixture")
    cache = AsyncMock()
    cache.bulk_get_status.return_value = {str(world.dev_a.id): SimpleNamespace(status="online")}
    publisher = AsyncMock()
    async with world.sessions() as db:
        await TaskService(db, publisher=publisher, status_cache=cache).dispatch_pending_tasks(
            org_id=world.org_a.id, device_id=world.dev_a.id, include_cancellations=False,
        )
    async with world.sessions() as db:
        stored_task = await db.get(Task, task.id)
        stored_batch = await db.get(TaskBatch, batch.id)
        assert stored_task is not None and stored_task.status == TaskStatus.FAILED
        assert stored_task.error_message == ("Script version not found" if missing_version else "unsupported_fixture")
        assert stored_batch is not None and (stored_batch.status, stored_batch.failed) == ("failed", 1)
    publisher.send_command_live.assert_not_awaited()
