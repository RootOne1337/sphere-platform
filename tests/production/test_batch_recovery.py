"""Durable wave plan, pinned version and atomic admission on disposable SQL."""

import asyncio
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from backend.database.tenant import bind_tenant_context
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.schemas.batch import BatchExecutionRequest
from backend.services.batch_admission import BatchAdmissionWorker, advance_batch
from backend.services.batch_service import BatchService
from backend.services.task_service import TaskService


def request(world, **overrides):
    return BatchExecutionRequest(**{
        "script_id": world.script.id, "device_ids": [world.dev_a.id, world.dev_a2.id],
        "wave_size": 1, "wave_delay_ms": 0, "jitter_ms": 0,
        "stagger_by_workstation": False, **overrides,
    })


async def start(world, monkeypatch, **overrides):
    # Stop only the old in-memory producer. A durable implementation has none.
    monkeypatch.setattr(BatchService, "_execute_waves", AsyncMock(), raising=False)
    async with world.sessions() as db:
        batch = await BatchService(db, world.sessions).start_batch(
            request(world, **overrides), world.org_a.id, world.users["org_admin"].id,
        )
    await asyncio.sleep(0)
    return batch


async def test_committed_batch_retains_all_targets_when_producer_never_runs(world, monkeypatch):
    batch = await start(world, monkeypatch)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        plan = getattr(stored, "wave_plan", None)
        assert plan is not None, "remaining targets exist only in worker memory"
        assert [[item["device_id"] for item in wave] for wave in plan] == [
            [str(world.dev_a.id)], [str(world.dev_a2.id)],
        ]
        assert len({item["task_id"] for wave in plan for item in wave}) == 2


async def test_batch_pins_script_version_before_background_admission(world, monkeypatch):
    batch = await start(world, monkeypatch)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert getattr(stored, "script_version_id", None) == world.version.id


async def test_duplicate_targets_cannot_leave_total_greater_than_durable_work(world):
    with pytest.raises(ValidationError, match="unique"):
        request(world, device_ids=[world.dev_a.id, world.dev_a.id])


async def tasks(world, batch):
    async with world.sessions() as db:
        return list(await db.scalars(select(Task).where(Task.batch_id == batch.id).order_by(Task.wave_index)))


async def test_lost_commit_response_then_restart_does_not_repeat_completed_wave(world, monkeypatch):
    batch = await start(world, monkeypatch)

    @asynccontextmanager
    async def lost_ack():
        async with world.sessions() as db:
            commit = db.commit

            async def commit_then_lose():
                await commit()
                raise ConnectionError("isolated lost commit acknowledgement")

            db.commit = commit_then_lose
            yield db

    with pytest.raises(ConnectionError):
        await advance_batch(lost_ack, batch.id, world.org_a.id)
    first = (await tasks(world, batch))[0]
    async with world.sessions() as db:
        (await db.get(Task, first.id)).status = TaskStatus.COMPLETED
        await db.commit()
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    stored_tasks = await tasks(world, batch)
    assert len(stored_tasks) == 2 and stored_tasks[0].id == first.id
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.next_wave_index == 2 and stored.admission_state == "submitted"
        assert len(stored.admission_receipts) == 2
        assert stored.status == TaskBatchStatus.RUNNING  # admission is not execution


async def test_new_script_publication_between_waves_keeps_pinned_version(world, monkeypatch):
    batch = await start(world, monkeypatch)
    await advance_batch(world.sessions, batch.id, world.org_a.id)
    async with world.sessions() as db:
        version = ScriptVersion(org_id=world.org_a.id, script_id=world.script.id, version=2, dag={"nodes": []})
        db.add(version)
        await db.flush()
        (await db.get(Script, world.script.id)).current_version_id = version.id
        await db.commit()
    await advance_batch(world.sessions, batch.id, world.org_a.id)
    assert {task.script_version_id for task in await tasks(world, batch)} == {world.version.id}


async def test_wave_rollback_leaves_no_tasks_receipts_or_cursor_advance(world, monkeypatch):
    batch = await start(world, monkeypatch, wave_size=2)
    create = TaskService.create_task

    async def fail(service, **kwargs):
        await create(service, **kwargs)
        await service.db.execute(text("SELECT 1/0"))

    monkeypatch.setattr(TaskService, "create_task", fail)
    with pytest.raises(DBAPIError):
        await advance_batch(world.sessions, batch.id, world.org_a.id)
    assert await tasks(world, batch) == []
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.next_wave_index == 0 and stored.admission_receipts == []
    monkeypatch.setattr(TaskService, "create_task", create)
    await advance_batch(world.sessions, batch.id, world.org_a.id)
    assert len(await tasks(world, batch)) == 2


async def test_concurrent_producer_skips_locked_wave_without_duplicate_admission(world, monkeypatch):
    batch = await start(world, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    create = TaskService.create_task

    async def hold(service, **kwargs):
        task = await create(service, **kwargs)
        entered.set()
        await release.wait()
        return task

    monkeypatch.setattr(TaskService, "create_task", hold)
    first = asyncio.create_task(advance_batch(world.sessions, batch.id, world.org_a.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert not await asyncio.wait_for(advance_batch(world.sessions, batch.id, world.org_a.id), 1)
        release.set()
        assert await asyncio.wait_for(first, 3)
    finally:
        release.set()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
    assert len(await tasks(world, batch)) == 1


async def test_delay_is_persisted_and_fresh_worker_cannot_admit_early(world, monkeypatch):
    batch = await start(world, monkeypatch, wave_delay_ms=60000)
    await advance_batch(world.sessions, batch.id, world.org_a.id)
    async with world.sessions() as db:
        due = (await db.get(TaskBatch, batch.id)).next_wave_at
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    assert not await advance_batch(world.sessions, batch.id, world.org_a.id)
    assert len(await tasks(world, batch)) == 1
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.next_wave_at == due
        stored.next_wave_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    assert len(await tasks(world, batch)) == 2


async def test_rejection_receipt_and_counter_are_not_repeated_on_restart(world, monkeypatch):
    missing = uuid.uuid4()
    batch = await start(world, monkeypatch, device_ids=[missing, world.dev_a.id])
    await advance_batch(world.sessions, batch.id, world.org_a.id)
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.failed == 1 and stored.succeeded == 0
        assert stored.admission_receipts[0] == {
            **stored.wave_plan[0][0], "wave_index": 0, "outcome": "rejected", "http_status": 404,
        }
    assert len(await tasks(world, batch)) == 1


async def test_cancelled_plan_is_not_resumed_by_fresh_worker(world, monkeypatch):
    batch = await start(world, monkeypatch)
    await advance_batch(world.sessions, batch.id, world.org_a.id)
    async with world.sessions() as db:
        await BatchService(db, world.sessions).cancel_batch(batch.id, world.org_a.id)
        await db.commit()
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    assert not await advance_batch(world.sessions, batch.id, world.org_a.id)
    assert len(await tasks(world, batch)) == 1
    async with world.sessions() as db:
        assert (await db.get(TaskBatch, batch.id)).admission_state == "cancelled"


async def test_legacy_batch_without_targets_is_not_guessed_or_replayed(world):
    async with world.sessions() as db:
        batch = TaskBatch(org_id=world.org_a.id, script_id=world.script.id, status=TaskBatchStatus.RUNNING, total=2)
        db.add(batch)
        await db.commit()
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    assert not await advance_batch(world.sessions, batch.id, world.org_a.id)
    assert await tasks(world, batch) == []
    async with world.sessions() as db:
        assert (await db.get(TaskBatch, batch.id)).admission_state == "legacy_unknown"


async def test_corrupt_pinned_version_never_admits_another_tenants_script(world, monkeypatch):
    batch = await start(world, monkeypatch)
    async with world.sessions() as db:
        script = Script(org_id=world.org_b.id, name="foreign")
        db.add(script)
        await db.flush()
        foreign = ScriptVersion(org_id=world.org_b.id, script_id=script.id, dag={})
        db.add(foreign)
        await db.flush()
        (await db.get(TaskBatch, batch.id)).script_version_id = foreign.id
        await db.commit()
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    assert await tasks(world, batch) == []


async def test_runtime_rls_role_uses_granted_lookup_then_scoped_admission(runtime_db, monkeypatch):
    r, world = runtime_db, runtime_db.world
    batch = await start(world, monkeypatch)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        stored.created_at = datetime(1900, 1, 1, tzinfo=timezone.utc)
        await db.commit()
    async with r.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TaskBatch)) == 0
        with pytest.raises(DBAPIError):
            await db.execute(text("SELECT * FROM sphere_auth.due_batch_admissions()"))
    async with world.sessions() as db:
        await db.execute(text(f'GRANT EXECUTE ON FUNCTION sphere_auth.due_batch_admissions() TO "{r.role}"'))
        await db.commit()
    try:
        async with r.sessions() as db:
            rows = (await db.execute(text("SELECT * FROM sphere_auth.due_batch_admissions()"))).all()
            assert len(rows) <= 32 and (batch.id, world.org_a.id) in rows
        # Constrain this runtime test to its two random tenants. The global
        # lookup was verified above without dispatching other fixture tenants.
        await BatchAdmissionWorker(r.sessions).poll(org_id=world.org_a.id)
        assert len(await tasks(world, batch)) == 1
        assert not await advance_batch(r.sessions, batch.id, world.org_b.id)
        async with r.sessions() as db:
            await bind_tenant_context(db, str(world.org_b.id))
            assert await db.get(TaskBatch, batch.id) is None
    finally:
        async with world.sessions() as db:
            await db.execute(text(f'REVOKE EXECUTE ON FUNCTION sphere_auth.due_batch_admissions() FROM "{r.role}"'))
            await db.commit()


async def test_worker_failure_backoff_preserves_pending_intent(world, monkeypatch):
    batch = await start(world, monkeypatch)
    monkeypatch.setattr("backend.services.batch_admission.advance_batch", AsyncMock(side_effect=ConnectionError("isolated")))
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.admission_state == "pending" and stored.next_wave_index == 0
        assert stored.next_wave_at > datetime.now(timezone.utc)
    assert await tasks(world, batch) == []


async def test_retry_after_lost_commit_cannot_shorten_the_persisted_wave_delay(world, monkeypatch):
    batch = await start(world, monkeypatch, wave_delay_ms=60000)
    began = datetime.now(timezone.utc)
    real_advance = advance_batch

    async def lose_after_commit(*args, **kwargs):
        await real_advance(*args, **kwargs)
        raise ConnectionError("isolated lost ACK")

    monkeypatch.setattr("backend.services.batch_admission.advance_batch", lose_after_commit)
    await BatchAdmissionWorker(world.sessions).poll(org_id=world.org_a.id)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.next_wave_index == 1
        assert stored.next_wave_at >= began + timedelta(seconds=60)


async def test_os_kill_between_waves_then_fresh_process_admits_only_remaining_target(world, monkeypatch, tmp_path):
    batch = await start(world, monkeypatch, wave_delay_ms=3_600_000)
    processes = []

    async def wait_cursor(expected):
        async def inspect():
            while True:
                async with world.sessions() as db:
                    stored = await db.get(TaskBatch, batch.id)
                    if stored.next_wave_index == expected:
                        return
                await asyncio.sleep(0.025)
        await asyncio.wait_for(inspect(), 15)

    with (tmp_path / "batch-worker.log").open("w", encoding="utf-8") as log:
        def launch():
            process = subprocess.Popen(
                [sys.executable, "-m", "tests.production.batch_worker_probe", str(world.org_a.id)],
                env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            processes.append(process)
            return process

        try:
            first = launch()
            await wait_cursor(1)
            first.kill()  # Only the exact subprocess owned by this test.
            await asyncio.to_thread(first.wait, 5)
            initial = (await tasks(world, batch))[0]
            async with world.sessions() as db:
                (await db.get(Task, initial.id)).status = TaskStatus.COMPLETED
                (await db.get(TaskBatch, batch.id)).next_wave_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await db.commit()
            second = launch()
            await wait_cursor(2)
            assert second.pid != first.pid
            recovered = await tasks(world, batch)
            assert len(recovered) == 2 and recovered[0].id == initial.id
            assert recovered[1].device_id == world.dev_a2.id
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, 5)
