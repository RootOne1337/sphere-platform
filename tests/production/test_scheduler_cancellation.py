"""Scheduler cancellation must wait for task/pipeline outcome transactions."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.schedule import Schedule, ScheduleExecution, ScheduleTargetType
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.services.scheduler.scheduler_engine import SchedulerEngine
from backend.services.task_service import TaskService


@pytest.fixture
def ports(monkeypatch, world):
    queue, publisher = AsyncMock(), AsyncMock()
    monkeypatch.setattr("backend.services.task_queue.TaskQueue", lambda *args, **kwargs: queue)
    monkeypatch.setattr("backend.websocket.pubsub_router.get_pubsub_publisher", lambda: publisher)
    monkeypatch.setattr("backend.database.redis_client.redis_binary", world.redis)
    return queue, publisher


async def seed(world, task_status=None, pipeline_status=None):
    now = datetime.now(timezone.utc)
    async with world.sessions() as db:
        if pipeline_status is None:
            batch = TaskBatch(org_id=world.org_a.id, script_id=world.script.id,
                              status=TaskBatchStatus.RUNNING, total=1)
            db.add(batch)
            await db.flush()
            record = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                          script_id=world.script.id, script_version_id=world.version.id,
                          status=task_status, batch_id=batch.id)
            schedule = Schedule(org_id=world.org_a.id, name="isolated task schedule",
                                interval_seconds=60, target_type=ScheduleTargetType.SCRIPT,
                                script_id=world.script.id)
            execution_ids = {"batch_id": batch.id}
        else:
            pipeline = Pipeline(org_id=world.org_a.id, name="isolated pipeline")
            db.add(pipeline)
            await db.flush()
            batch_id = uuid.uuid4()
            record = PipelineRun(org_id=world.org_a.id, pipeline_id=pipeline.id,
                                 device_id=world.dev_a.id, status=pipeline_status,
                                 context={"batch_id": str(batch_id)}, steps_snapshot=[])
            schedule = Schedule(org_id=world.org_a.id, name="isolated pipeline schedule",
                                interval_seconds=60, target_type=ScheduleTargetType.PIPELINE,
                                pipeline_id=pipeline.id)
            execution_ids = {"pipeline_batch_id": batch_id}
        db.add_all([record, schedule])
        await db.flush()
        db.add(ScheduleExecution(schedule_id=schedule.id, org_id=world.org_a.id,
                                 fire_time=now, actual_time=now, **execution_ids))
        await db.commit()
        return schedule, record


async def cancel(db, schedule):
    count = await SchedulerEngine()._cancel_previous_tasks(schedule, db)
    await db.commit()
    return count


async def wait_for_lock_or_effect(world, pid, effect):
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


@pytest.mark.parametrize("initial", [TaskStatus.ASSIGNED, TaskStatus.RUNNING])
@pytest.mark.parametrize("success", [True, False])
async def test_scheduler_cannot_stop_or_overwrite_a_task_result_owner(world, ports, initial, success):
    queue, publisher = ports
    schedule, task = await seed(world, task_status=initial)
    effect = asyncio.Event()
    queue.cancel_task.side_effect = lambda *args: effect.set()
    publisher.send_command_live.side_effect = lambda *args: effect.set() or True
    async with world.sessions() as completion, world.sessions() as cancellation:
        pid = await cancellation.scalar(text("SELECT pg_backend_pid()"))
        cached = await cancellation.get(Task, task.id)
        await TaskService(completion, AsyncMock(), publisher=AsyncMock()).handle_task_result(
            str(task.id), str(task.device_id), {"success": success, "proof": "committed result"},
            str(world.org_a.id),
        )
        await completion.flush()
        pending = asyncio.create_task(cancel(cancellation, schedule))
        try:
            await wait_for_lock_or_effect(world, pid, effect)
            early_effects = queue.cancel_task.await_count + publisher.send_command_live.await_count
            await completion.commit()
            count = await asyncio.wait_for(pending, 3)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        assert cached is not None
    async with world.sessions() as db:
        stored = await db.get(Task, task.id)
        assert stored.status == (TaskStatus.COMPLETED if success else TaskStatus.FAILED)
        assert stored.result == {"success": success, "proof": "committed result"}
    assert count == 0
    assert early_effects == 0
    queue.cancel_task.assert_not_awaited()
    queue.mark_completed.assert_not_awaited()
    publisher.send_command_live.assert_not_awaited()


@pytest.mark.parametrize("initial", [TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING])
async def test_scheduler_still_cancels_eligible_tasks_with_scoped_control(world, ports, initial):
    queue, publisher = ports
    schedule, task = await seed(world, task_status=initial)
    async with world.sessions() as db:
        assert await cancel(db, schedule) == 1
    async with world.sessions() as db:
        stored = await db.get(Task, task.id)
        assert stored.status == TaskStatus.CANCELLED
        assert stored.finished_at is not None
    queue.mark_completed.assert_awaited_once_with(str(task.id), str(task.device_id))
    if initial == TaskStatus.RUNNING:
        queue.cancel_task.assert_not_awaited()
        publisher.send_command_live.assert_awaited_once()
        device, message = publisher.send_command_live.call_args.args
        assert device == str(task.device_id)
        assert message["command_id"] == f"sched_cancel_{task.id}"
        assert message["payload"] == {"task_id": str(task.id)}
    else:
        queue.cancel_task.assert_awaited_once_with(str(task.id), str(world.org_a.id), str(task.device_id))
        publisher.send_command_live.assert_not_awaited()


@pytest.mark.parametrize("terminal", [PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED,
                                     PipelineRunStatus.TIMED_OUT])
async def test_scheduler_cannot_overwrite_committing_pipeline_outcome(world, ports, terminal):
    schedule, run = await seed(world, pipeline_status=PipelineRunStatus.RUNNING)
    async with world.sessions() as completion, world.sessions() as cancellation:
        pid = await cancellation.scalar(text("SELECT pg_backend_pid()"))
        cached = await cancellation.get(PipelineRun, run.id)
        owner = await completion.get(PipelineRun, run.id)
        owner.status = terminal
        owner.finished_at = datetime.now(timezone.utc)
        owner.context = {**owner.context, "proof": "committed pipeline outcome"}
        await completion.flush()
        finished_at = owner.finished_at
        pending = asyncio.create_task(cancel(cancellation, schedule))
        try:
            await wait_for_lock_or_effect(world, pid, asyncio.Event())
            await completion.commit()
            count = await asyncio.wait_for(pending, 3)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        assert cached is not None
    async with world.sessions() as db:
        stored = await db.get(PipelineRun, run.id)
        assert stored.status == terminal
        assert stored.finished_at == finished_at
        assert stored.context["proof"] == "committed pipeline outcome"
    assert count == 0
    for port in ports:
        assert not port.mock_calls


@pytest.mark.parametrize("initial", [PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING,
                                    PipelineRunStatus.WAITING])
async def test_scheduler_still_cancels_eligible_pipeline_runs(world, ports, initial):
    schedule, run = await seed(world, pipeline_status=initial)
    async with world.sessions() as db:
        assert await cancel(db, schedule) == 1
    async with world.sessions() as db:
        stored = await db.get(PipelineRun, run.id)
        assert stored.status == PipelineRunStatus.CANCELLED
        assert stored.finished_at is not None
    for port in ports:
        assert not port.mock_calls


@pytest.mark.parametrize("pipeline", [False, True])
async def test_scheduler_does_not_follow_cross_tenant_legacy_batch_links(world, ports, pipeline):
    schedule, record = await seed(world, task_status=TaskStatus.RUNNING,
                                  pipeline_status=PipelineRunStatus.RUNNING if pipeline else None)
    model = PipelineRun if pipeline else Task
    # Seed a mismatched legacy link explicitly. This validates the query boundary;
    # it does not claim a public API can create the malformed relationship.
    async with world.sessions() as db:
        foreign = await db.get(model, record.id)
        foreign.org_id = world.org_b.id
        foreign.device_id = world.dev_b.id
        await db.commit()
    async with world.sessions() as db:
        assert await cancel(db, schedule) == 0
    async with world.sessions() as db:
        stored = await db.get(model, record.id)
        assert stored.status == (PipelineRunStatus.RUNNING if pipeline else TaskStatus.RUNNING)
    for port in ports:
        assert not port.mock_calls


async def test_scheduler_stamps_stop_after_waiting_for_task_owner(world, ports, monkeypatch):
    queue, publisher = ports
    schedule, task = await seed(world, task_status=TaskStatus.RUNNING)
    clock_time = datetime.now(timezone.utc)

    class Clock:
        @staticmethod
        def now(tz):
            return clock_time

    monkeypatch.setattr("backend.services.scheduler.scheduler_engine.datetime", Clock)
    effect = asyncio.Event()
    publisher.send_command_live.side_effect = lambda *args: effect.set() or True
    async with world.sessions() as owner, world.sessions() as cancellation:
        pid = await cancellation.scalar(text("SELECT pg_backend_pid()"))
        held = await owner.get(Task, task.id)
        held.result = {"proof": "row owner remains running"}
        await owner.flush()
        pending = asyncio.create_task(cancel(cancellation, schedule))
        try:
            await wait_for_lock_or_effect(world, pid, effect)
            clock_time += timedelta(seconds=120) # Simulate a wait longer than control TTL.
            await owner.commit()
            assert await asyncio.wait_for(pending, 3) == 1
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    publisher.send_command_live.assert_awaited_once()
    message = publisher.send_command_live.call_args.args[1]
    assert message["signed_at"] == int(clock_time.timestamp())
    assert message["ttl_seconds"] == 30
    queue.mark_completed.assert_awaited_once()
