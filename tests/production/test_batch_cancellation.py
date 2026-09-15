"""Batch cancellation must respect committed outcomes and PostgreSQL row owners."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.services.batch_service import BatchService
from backend.services.task_service import TaskService


@pytest.fixture
def queue(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr("backend.services.task_queue.TaskQueue", lambda *args, **kwargs: fake)
    return fake


async def seed_batch(world, task_status=TaskStatus.ASSIGNED):
    async with world.sessions() as db:
        batch = TaskBatch(org_id=world.org_a.id, script_id=world.script.id,
                          status=TaskBatchStatus.RUNNING, total=1)
        db.add(batch)
        await db.flush()
        task = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                    script_id=world.script.id, script_version_id=world.version.id,
                    status=task_status, batch_id=batch.id)
        db.add(task)
        await db.commit()
        return batch, task


async def cancel(db, world, batch):
    try:
        await BatchService(db, world.sessions).cancel_batch(batch.id, world.org_a.id)
        await db.commit()
        return 204
    except HTTPException as exc:
        await db.rollback()
        return exc.status_code


async def wait_for_lock_or_effect(world, pid, effect):
    """Observe the actual PostgreSQL wait, not a guessed scheduling delay."""
    async def observe():
        while not effect.is_set():
            async with world.sessions() as observer:
                wait = await observer.scalar(text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"
                ), {"pid": pid})
            if wait == "Lock":
                return
            await asyncio.sleep(0.01)
    await asyncio.wait_for(observe(), 3)


@pytest.mark.parametrize("success", [True, False])
async def test_batch_cancel_waits_for_result_commit_before_queue_effects(world, queue, success):
    batch, task = await seed_batch(world)
    effect = asyncio.Event()
    queue.cancel_task.side_effect = lambda *args: effect.set()
    async with world.sessions() as completion, world.sessions() as cancellation:
        pid = await cancellation.scalar(text("SELECT pg_backend_pid()"))
        cached_batch = await cancellation.get(TaskBatch, batch.id)
        await TaskService(completion, AsyncMock(), publisher=AsyncMock()).handle_task_result(
            str(task.id), str(task.device_id), {"success": success, "proof": "durable outcome"},
            str(world.org_a.id),
        )
        await completion.flush()  # Real handler owns Task -> TaskBatch locks.
        pending = asyncio.create_task(cancel(cancellation, world, batch))
        try:
            await wait_for_lock_or_effect(world, pid, effect)
            effects_before_commit = queue.cancel_task.await_count
            await completion.commit()
            outcome = await asyncio.wait_for(pending, 3)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        assert cached_batch is not None
    async with world.sessions() as verification:
        stored = await verification.get(Task, task.id)
        stored_batch = await verification.get(TaskBatch, batch.id)
        assert stored.status == (TaskStatus.COMPLETED if success else TaskStatus.FAILED)
        assert stored.result == {"success": success, "proof": "durable outcome"}
        assert stored_batch.status == (TaskBatchStatus.COMPLETED if success else TaskBatchStatus.FAILED)
        assert stored_batch.succeeded == int(success)
        assert stored_batch.failed == int(not success)
    assert outcome == 409
    assert effects_before_commit == 0
    queue.cancel_task.assert_not_awaited()


@pytest.mark.parametrize("preload", [False, True])
@pytest.mark.parametrize("terminal", [TaskBatchStatus.COMPLETED, TaskBatchStatus.FAILED,
                                     TaskBatchStatus.PARTIAL, TaskBatchStatus.CANCELLED])
async def test_terminal_batch_cannot_be_cancelled_from_fresh_or_stale_snapshot(world, queue, preload, terminal):
    batch, _ = await seed_batch(world)
    async with world.sessions() as cancellation:
        cached = await cancellation.get(TaskBatch, batch.id) if preload else None
        async with world.sessions() as owner:
            stored = await owner.get(TaskBatch, batch.id)
            stored.status = terminal
            await owner.commit()
        if cached is not None:
            assert cached.status == TaskBatchStatus.RUNNING
        assert await cancel(cancellation, world, batch) == 409
    async with world.sessions() as verification:
        assert (await verification.get(TaskBatch, batch.id)).status == terminal
    queue.cancel_task.assert_not_awaited()


@pytest.mark.parametrize("initial", [TaskStatus.QUEUED, TaskStatus.ASSIGNED])
async def test_batch_cancel_records_terminal_time_for_eligible_tasks(world, queue, initial):
    batch, task = await seed_batch(world, initial)
    before = datetime.now(timezone.utc)
    async with world.sessions() as db:
        assert await cancel(db, world, batch) == 204
    async with world.sessions() as db:
        stored = await db.get(Task, task.id)
        assert stored.status == TaskStatus.CANCELLED
        assert stored.finished_at is not None
        assert before <= stored.finished_at <= datetime.now(timezone.utc)
        assert (await db.get(TaskBatch, batch.id)).status == TaskBatchStatus.CANCELLED
    queue.cancel_task.assert_awaited_once_with(str(task.id), str(world.org_a.id), str(task.device_id))


async def test_batch_cancel_keeps_running_tasks_active(world, queue):
    batch, task = await seed_batch(world, TaskStatus.RUNNING)
    async with world.sessions() as db:
        assert await cancel(db, world, batch) == 204
    async with world.sessions() as db:
        stored = await db.get(Task, task.id)
        assert stored.status == TaskStatus.RUNNING
        assert stored.finished_at is None
    queue.cancel_task.assert_not_awaited()


async def test_batch_cancel_rejects_foreign_tenant_before_effects(world, queue):
    batch, _ = await seed_batch(world)
    async with world.sessions() as db:
        with pytest.raises(HTTPException) as caught:
            await BatchService(db, world.sessions).cancel_batch(batch.id, world.org_b.id)
        assert caught.value.status_code == 404
    queue.cancel_task.assert_not_awaited()


async def test_concurrent_batch_cancellations_do_not_repeat_queue_effect(world, queue):
    batch, _ = await seed_batch(world)
    effect = asyncio.Event()
    queue.cancel_task.side_effect = lambda *args: effect.set()
    async with world.sessions() as first, world.sessions() as second:
        pid = await second.scalar(text("SELECT pg_backend_pid()"))
        cached = await second.get(TaskBatch, batch.id)
        await BatchService(first, world.sessions).cancel_batch(batch.id, world.org_a.id)
        await first.flush()
        queue.cancel_task.reset_mock()
        effect.clear()
        pending = asyncio.create_task(cancel(second, world, batch))
        try:
            await wait_for_lock_or_effect(world, pid, effect)
            await first.commit()
            assert await asyncio.wait_for(pending, 3) == 409
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        assert cached is not None
    queue.cancel_task.assert_not_awaited()


async def test_batch_cancel_cannot_invert_task_then_batch_result_lock_order(world, queue):
    batch, task = await seed_batch(world)
    effect = asyncio.Event()
    queue.cancel_task.side_effect = lambda *args: effect.set()
    async with world.sessions() as completion, world.sessions() as cancellation:
        pid = await cancellation.scalar(text("SELECT pg_backend_pid()"))
        # Hold Task only. A cancellation that locks Batch first would now
        # deadlock when the result handler later aggregates this same batch.
        owner = await completion.scalar(select(Task).where(Task.id == task.id).with_for_update())
        pending = asyncio.create_task(cancel(cancellation, world, batch))
        try:
            await wait_for_lock_or_effect(world, pid, effect)
            await asyncio.wait_for(
                TaskService(completion, AsyncMock(), publisher=AsyncMock()).handle_task_result(
                    str(task.id), str(task.device_id), {"success": True}, str(world.org_a.id),
                ), 3,
            )
            await completion.commit()
            assert await asyncio.wait_for(pending, 3) == 409
            assert owner.status == TaskStatus.COMPLETED
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    queue.cancel_task.assert_not_awaited()
