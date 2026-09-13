"""Wave admission is not device completion; exercise real SQL/task writers."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.schemas.batch import BatchExecutionRequest
from backend.services.batch_service import BatchService
from backend.services.task_service import TaskService


@pytest.fixture
def webhook(monkeypatch):
    deliver = AsyncMock()
    monkeypatch.setattr("backend.services.webhook_service.WebhookService.deliver", deliver)
    return deliver


async def seed(world, device_ids):
    request = BatchExecutionRequest(
        script_id=world.script.id, device_ids=device_ids, wave_delay_ms=0,
        jitter_ms=0, stagger_by_workstation=False, webhook_url="https://audit.invalid/hook",
    )
    async with world.sessions() as db:
        batch = TaskBatch(org_id=world.org_a.id, script_id=world.script.id,
                          total=len(device_ids), status=TaskBatchStatus.RUNNING)
        db.add(batch)
        await db.commit()
    return batch, request


async def run_waves(world, batch, request, sessions=None):
    async with world.sessions() as unused_request_session:
        await BatchService(unused_request_session, sessions or world.sessions)._execute_waves(
            batch.id, [request.device_ids], request, world.org_a.id,
        )


async def finish(world, task, success):
    async with world.sessions() as db:
        assert await TaskService(db, AsyncMock(), publisher=AsyncMock()).handle_task_result(
            str(task.id), str(task.device_id), {"success": success}, str(world.org_a.id),
        )
        await db.commit()


@pytest.mark.parametrize("success", [True, False])
async def test_queued_wave_remains_running_until_device_result(world, webhook, success):
    batch, request = await seed(world, [world.dev_a.id])
    await run_waves(world, batch, request)
    async with world.sessions() as db:
        task = await db.scalar(select(Task).where(Task.batch_id == batch.id))
        stored = await db.get(TaskBatch, batch.id)
        assert task.status == TaskStatus.QUEUED
        assert (stored.status, stored.succeeded, stored.failed) == (TaskBatchStatus.RUNNING, 0, 0)
    webhook.assert_not_awaited()
    await finish(world, task, success)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.status == (TaskBatchStatus.COMPLETED if success else TaskBatchStatus.FAILED)
        assert (stored.succeeded, stored.failed) == (int(success), int(not success))


async def test_wave_admission_does_not_send_false_completion_webhook(world, webhook):
    batch, request = await seed(world, [world.dev_a.id])
    await run_waves(world, batch, request)
    webhook.assert_not_awaited()


@pytest.mark.parametrize("results", [[False], [True, False], [True]])
async def test_producer_cannot_overwrite_results_committed_after_wave_insert(world, webhook, results):
    devices = [world.dev_a.id, world.dev_a2.id][:len(results)]
    batch, request = await seed(world, devices)
    completed = False

    @asynccontextmanager
    async def sessions():
        nonlocal completed
        async with world.sessions() as db:
            commit = db.commit

            async def commit_then_deliver_results():
                nonlocal completed
                await commit()
                if completed:
                    return
                completed = True
                async with world.sessions() as observer:
                    tasks = list(await observer.scalars(select(Task).where(Task.batch_id == batch.id)))
                assert len(tasks) == len(results)
                for task, success in zip(tasks, results, strict=True):
                    await finish(world, task, success)

            db.commit = commit_then_deliver_results
            yield db

    await run_waves(world, batch, request, sessions)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        expected = (TaskBatchStatus.COMPLETED if all(results) else
                    TaskBatchStatus.PARTIAL if any(results) else TaskBatchStatus.FAILED)
        assert stored.status == expected
        assert (stored.succeeded, stored.failed) == (sum(results), len(results) - sum(results))


@pytest.mark.parametrize("success", [True, False])
async def test_rejected_device_is_accounted_with_later_real_result(world, webhook, success):
    batch, request = await seed(world, [uuid.uuid4(), world.dev_a.id])
    await run_waves(world, batch, request)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        tasks = list(await db.scalars(select(Task).where(Task.batch_id == batch.id)))
        assert len(tasks) == 1
        assert (stored.status, stored.succeeded, stored.failed) == (TaskBatchStatus.RUNNING, 0, 1)
    await finish(world, tasks[0], success)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert stored.status == (TaskBatchStatus.PARTIAL if success else TaskBatchStatus.FAILED)
        assert (stored.succeeded, stored.failed) == (int(success), 1 + int(not success))


async def test_all_rejected_devices_finish_as_failed(world, webhook):
    batch, request = await seed(world, [uuid.uuid4(), world.dev_b.id])
    await run_waves(world, batch, request)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert (stored.status, stored.succeeded, stored.failed) == (TaskBatchStatus.FAILED, 0, 2)
        assert await db.scalar(select(Task.id).where(Task.batch_id == batch.id)) is None


async def test_batch_can_still_be_cancelled_after_last_wave_is_enqueued(world, webhook, monkeypatch):
    queue = AsyncMock()
    monkeypatch.setattr("backend.services.task_queue.TaskQueue", lambda *args: queue)
    batch, request = await seed(world, [world.dev_a.id])
    await run_waves(world, batch, request)
    async with world.sessions() as db:
        await BatchService(db, world.sessions).cancel_batch(batch.id, world.org_a.id)
        await db.commit()
    async with world.sessions() as db:
        assert (await db.get(TaskBatch, batch.id)).status == TaskBatchStatus.CANCELLED
        assert (await db.scalar(select(Task).where(Task.batch_id == batch.id))).status == TaskStatus.CANCELLED
    queue.cancel_task.assert_awaited_once()


async def test_database_fault_aborts_current_wave_without_false_success(world, webhook, monkeypatch):
    batch, request = await seed(world, [world.dev_a.id, world.dev_a2.id])
    create = TaskService.create_task

    async def create_with_database_fault(service, **kwargs):
        if kwargs["device_id"] == world.dev_a2.id:
            # Real server-side statement error, not a mocked commit outcome.
            await service.db.execute(text("SELECT 1 / 0"))
        return await create(service, **kwargs)

    monkeypatch.setattr(TaskService, "create_task", create_with_database_fault)
    async with world.sessions() as db:
        with pytest.raises(DBAPIError):
            await BatchService(db, world.sessions)._execute_waves(
                batch.id, [[world.dev_a.id], [world.dev_a2.id]], request, world.org_a.id,
            )
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        tasks = list(await db.scalars(select(Task).where(Task.batch_id == batch.id)))
        assert [task.device_id for task in tasks] == [world.dev_a.id]
        assert (stored.status, stored.succeeded, stored.failed) == (TaskBatchStatus.RUNNING, 0, 0)
    webhook.assert_not_awaited()


@pytest.mark.parametrize("success", [True, False])
async def test_admission_failure_serializes_with_previous_wave_result(world, webhook, success):
    missing = uuid.uuid4()
    batch, request = await seed(world, [world.dev_a.id, missing])
    async with world.sessions() as db:
        task = Task(org_id=world.org_a.id, script_id=world.script.id,
                    script_version_id=world.version.id, device_id=world.dev_a.id,
                    batch_id=batch.id, status=TaskStatus.RUNNING)
        db.add(task)
        await db.commit()

    producer_pid = None
    @asynccontextmanager
    async def sessions():
        nonlocal producer_pid
        async with world.sessions() as db:
            producer_pid = await db.scalar(text("SELECT pg_backend_pid()"))
            yield db

    async with world.sessions() as result_owner, world.sessions() as request_session:
        await TaskService(result_owner, AsyncMock(), publisher=AsyncMock()).handle_task_result(
            str(task.id), str(task.device_id), {"success": success}, str(world.org_a.id),
        )
        await result_owner.flush()
        pending = asyncio.create_task(BatchService(request_session, sessions)._execute_waves(
            batch.id, [[missing]], request, world.org_a.id,
        ))
        try:
            async def observe():
                while True:
                    async with world.sessions() as observer:
                        wait = await observer.scalar(text(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"
                        ), {"pid": producer_pid})
                    if wait == "Lock":
                        return
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(observe(), 3)
            await result_owner.commit()
            await asyncio.wait_for(pending, 3)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with world.sessions() as db:
        stored = await db.get(TaskBatch, batch.id)
        assert (stored.succeeded, stored.failed) == (int(success), 1 + int(not success))
        assert stored.status == (TaskBatchStatus.PARTIAL if success else TaskBatchStatus.FAILED)
