"""Cancellation must serialize with wave admission, including uncommitted tasks."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.services.batch_service import BatchService
from backend.services.task_service import TaskService
from backend.tasks.task_heartbeat_watchdog import _aggregate_batches
from tests.production.test_batch_cancellation import wait_for_lock_or_effect
from tests.production.test_batch_wave_outcomes import finish, run_waves, seed


@pytest.fixture
def queue(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr("backend.services.task_queue.TaskQueue", lambda *args: fake)
    return fake


@pytest.mark.parametrize("terminal", [TaskBatchStatus.CANCELLED, TaskBatchStatus.COMPLETED,
                                     TaskBatchStatus.FAILED, TaskBatchStatus.PARTIAL])
async def test_terminal_batch_cannot_admit_new_wave(world, queue, terminal):
    batch, request = await seed(world, [world.dev_a.id])
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        stored.status = terminal
        await db.commit()
    await run_waves(world, batch, request)
    async with world.sessions() as db:
        assert await db.scalar(select(Task.id).where(Task.batch_id == batch.id)) is None
        assert (await db.get(TaskBatch, batch.id)).status == terminal


async def test_cancel_between_waves_prevents_next_device_admission(world, queue):
    batch, request = await seed(world, [world.dev_a.id, world.dev_a2.id])
    cancelled = False

    @asynccontextmanager
    async def sessions():
        nonlocal cancelled
        async with world.sessions() as db:
            commit = db.commit

            async def commit_then_cancel():
                nonlocal cancelled
                await commit()
                if not cancelled:
                    cancelled = True
                    async with world.sessions() as cancellation:
                        await BatchService(cancellation, world.sessions).cancel_batch(batch.id, world.org_a.id)
                        await cancellation.commit()

            db.commit = commit_then_cancel
            yield db

    async with world.sessions() as db:
        await BatchService(db, sessions)._execute_waves(
            batch.id, [[world.dev_a.id], [world.dev_a2.id]], request, world.org_a.id,
        )
    async with world.sessions() as db:
        tasks = list(await db.scalars(select(Task).where(Task.batch_id == batch.id)))
        assert [(task.device_id, task.status) for task in tasks] == [(world.dev_a.id, TaskStatus.CANCELLED)]
        assert (await db.get(TaskBatch, batch.id)).status == TaskBatchStatus.CANCELLED


async def test_cancel_waits_for_inflight_wave_then_cancels_its_committed_tasks(world, queue, monkeypatch):
    batch, request = await seed(world, [world.dev_a.id])
    created = asyncio.Event()
    release = asyncio.Event()
    cancel_done = asyncio.Event()
    create = TaskService.create_task

    async def hold_uncommitted_task(service, **kwargs):
        task = await create(service, **kwargs)
        created.set()
        await release.wait()
        return task

    monkeypatch.setattr(TaskService, "create_task", hold_uncommitted_task)
    async with world.sessions() as cancellation:
        pid = await cancellation.scalar(text("SELECT pg_backend_pid()"))
        producer = asyncio.create_task(run_waves(world, batch, request))

        async def cancel():
            await BatchService(cancellation, world.sessions).cancel_batch(batch.id, world.org_a.id)
            await cancellation.commit()
            cancel_done.set()

        pending = None
        try:
            await asyncio.wait_for(created.wait(), 3)
            pending = asyncio.create_task(cancel())
            await wait_for_lock_or_effect(world, pid, cancel_done)
            early_cancel = cancel_done.is_set()
            release.set()
            await asyncio.wait_for(asyncio.gather(producer, pending), 3)
        finally:
            release.set()
            producer.cancel()
            if pending is not None:
                pending.cancel()
            await asyncio.gather(producer, *([pending] if pending else []), return_exceptions=True)
    async with world.sessions() as db:
        task = await db.scalar(select(Task).where(Task.batch_id == batch.id))
        assert task.status == TaskStatus.CANCELLED
        assert (await db.get(TaskBatch, batch.id)).status == TaskBatchStatus.CANCELLED
    assert not early_cancel
    queue.cancel_task.assert_awaited_once()


async def test_wave_waits_for_cancel_commit_before_task_creation(world, queue, monkeypatch):
    batch, request = await seed(world, [world.dev_a.id])
    effect = asyncio.Event()
    create = TaskService.create_task
    pid_ready = asyncio.Event()
    producer_pid = None

    async def observe_create(service, **kwargs):
        effect.set()
        return await create(service, **kwargs)

    monkeypatch.setattr(TaskService, "create_task", observe_create)

    @asynccontextmanager
    async def sessions():
        nonlocal producer_pid
        async with world.sessions() as db:
            producer_pid = await db.scalar(text("SELECT pg_backend_pid()"))
            pid_ready.set()
            yield db

    async with world.sessions() as cancellation:
        await BatchService(cancellation, world.sessions).cancel_batch(batch.id, world.org_a.id)
        await cancellation.flush()
        producer = asyncio.create_task(run_waves(world, batch, request, sessions))
        try:
            await asyncio.wait_for(pid_ready.wait(), 3)
            await wait_for_lock_or_effect(world, producer_pid, effect)
            early_effect = effect.is_set()
            await cancellation.commit()
            await asyncio.wait_for(producer, 3)
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
    assert not early_effect
    assert not effect.is_set()
    async with world.sessions() as db:
        assert await db.scalar(select(Task.id).where(Task.batch_id == batch.id)) is None


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
async def test_running_task_outcome_cannot_reopen_cancelled_batch(world, queue, outcome):
    batch, _ = await seed(world, [world.dev_a.id])
    async with world.sessions() as db:
        task = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                    script_id=world.script.id, script_version_id=world.version.id,
                    batch_id=batch.id, status=TaskStatus.RUNNING)
        db.add(task)
        await db.commit()
    async with world.sessions() as db:
        await BatchService(db, world.sessions).cancel_batch(batch.id, world.org_a.id)
        await db.commit()
    if outcome == "timeout":
        async with world.sessions() as db:
            timed = await db.get(Task, task.id)
            timed.status = TaskStatus.TIMEOUT
            await _aggregate_batches(db, [timed], datetime.now(timezone.utc), TaskBatch, TaskBatchStatus)
            await db.commit()
    else:
        await finish(world, task, outcome == "success")
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.status == TaskBatchStatus.CANCELLED
        assert (stored.succeeded, stored.failed) == (int(outcome == "success"), int(outcome != "success"))


async def test_foreign_worker_context_cannot_modify_batch_counts(world, queue):
    batch, request = await seed(world, [world.dev_a.id])
    async with world.sessions() as db:
        await BatchService(db, world.sessions)._execute_waves(
            batch.id, [[world.dev_a.id]], request, world.org_b.id,
        )
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert (stored.status, stored.succeeded, stored.failed) == (TaskBatchStatus.RUNNING, 0, 0)


async def test_database_rollback_releases_production_lock_for_cancellation(world, queue, monkeypatch):
    batch, request = await seed(world, [world.dev_a.id])
    create = TaskService.create_task

    async def fail_after_insert(service, **kwargs):
        await create(service, **kwargs)
        await service.db.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(TaskService, "create_task", fail_after_insert)
    with pytest.raises(DBAPIError):
        await run_waves(world, batch, request)
    async with world.sessions() as db:
        await asyncio.wait_for(BatchService(db, world.sessions).cancel_batch(batch.id, world.org_a.id), 3)
        await db.commit()
    async with world.sessions() as db:
        assert await db.scalar(select(Task.id).where(Task.batch_id == batch.id)) is None
        assert (await db.get(TaskBatch, batch.id)).status == TaskBatchStatus.CANCELLED
    queue.cancel_task.assert_not_awaited()


async def test_overlapping_batches_acquire_devices_without_reverse_order_deadlock(world, queue, monkeypatch):
    devices = sorted([world.dev_a.id, world.dev_a2.id])
    first, request_a = await seed(world, devices)
    second, request_b = await seed(world, list(reversed(devices)))
    first_held = asyncio.Event()
    second_held = asyncio.Event()
    release = asyncio.Event()
    pid_ready = asyncio.Event()
    producer_pid = None
    create = TaskService.create_task

    async def hold_first_device(service, **kwargs):
        task = await create(service, **kwargs)
        event = first_held if kwargs["batch_id"] == first.id else second_held
        if not event.is_set():
            event.set()
            await release.wait()
        return task

    monkeypatch.setattr(TaskService, "create_task", hold_first_device)

    @asynccontextmanager
    async def sessions():
        nonlocal producer_pid
        async with world.sessions() as db:
            producer_pid = await db.scalar(text("SELECT pg_backend_pid()"))
            pid_ready.set()
            yield db

    first_job = asyncio.create_task(run_waves(world, first, request_a))
    second_job = None
    try:
        await asyncio.wait_for(first_held.wait(), 3)
        second_job = asyncio.create_task(run_waves(world, second, request_b, sessions))
        await asyncio.wait_for(pid_ready.wait(), 3)
        await wait_for_lock_or_effect(world, producer_pid, second_held)
        release.set()
        await asyncio.wait_for(asyncio.gather(first_job, second_job), 3)
    finally:
        release.set()
        first_job.cancel()
        if second_job is not None:
            second_job.cancel()
        await asyncio.gather(first_job, *([second_job] if second_job else []), return_exceptions=True)
    async with world.sessions() as db:
        assert (await db.get(TaskBatch, first.id)).status == TaskBatchStatus.RUNNING
        rejected = await db.get(TaskBatch, second.id)
        assert (rejected.status, rejected.failed) == (TaskBatchStatus.FAILED, 2)
        tasks = list(await db.scalars(select(Task).where(Task.batch_id.in_([first.id, second.id]))))
        assert len(tasks) == 2
        assert all(task.batch_id == first.id and task.status == TaskStatus.QUEUED for task in tasks)
