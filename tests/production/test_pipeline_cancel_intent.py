"""Pipeline cancellation must fence admission and retain its active child's stop intent."""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.task import Task, TaskStatus
from backend.services.orchestrator.pipeline_executor import PipelineExecutor
from backend.services.orchestrator.pipeline_service import PipelineService
from backend.services.orchestrator.step_handlers import handle_execute_script


async def seed(world, child_status=None):
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name="cancel-intent-fixture")
        db.add(pipeline)
        await db.flush()
        child = None
        if child_status:
            child = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                         script_id=world.script.id, script_version_id=world.version.id,
                         status=child_status)
            db.add(child)
            await db.flush()
        run = PipelineRun(org_id=world.org_a.id, pipeline_id=pipeline.id, device_id=world.dev_a.id,
                          status=PipelineRunStatus.RUNNING, started_at=datetime.now(timezone.utc),
                          current_task_id=child.id if child else None,
                          steps_snapshot=[{"id": "wait", "type": "delay", "params": {"delay_ms": 100}}])
        db.add(run)
        await db.commit()
    return run, child


@pytest.mark.parametrize("status", [TaskStatus.ASSIGNED, TaskStatus.RUNNING])
async def test_pipeline_cancel_waits_for_active_child_terminal_receipt(world, status):
    run, child = await seed(world, status)
    async with world.sessions() as db:
        cancelled = await PipelineService(db).cancel_run(run.id, world.org_a.id)
        await db.commit()
        assert cancelled.status == PipelineRunStatus.RUNNING
        assert cancelled.finished_at is None and cancelled.cancel_requested_at is not None
        stored = await db.get(Task, child.id)
        assert stored.status == status and stored.cancel_requested_at is not None


async def test_pipeline_cancels_never_dispatched_child_without_waiting_for_device(world):
    run, child = await seed(world, TaskStatus.QUEUED)
    async with world.sessions() as db:
        cancelled = await PipelineService(db).cancel_run(run.id, world.org_a.id)
        await db.commit()
        assert cancelled.status == PipelineRunStatus.CANCELLED
        assert (await db.get(Task, child.id)).status == TaskStatus.CANCELLED


async def test_fresh_executor_finalizes_cancelled_pipeline_after_child_receipt(world, monkeypatch):
    run, child = await seed(world, TaskStatus.RUNNING)
    async with world.sessions() as db:
        await PipelineService(db).cancel_run(run.id, world.org_a.id)
        await db.commit()
    async with world.sessions() as db:
        task = await db.get(Task, child.id)
        task.status = TaskStatus.CANCELLED
        task.finished_at = datetime.now(timezone.utc)
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    await PipelineExecutor()._reconcile_cancellations(org_id=world.org_a.id)
    async with world.sessions() as db:
        stored = await db.get(PipelineRun, run.id)
        assert stored.status == PipelineRunStatus.CANCELLED and stored.finished_at is not None


async def test_cancelled_pipeline_cannot_admit_a_late_child_from_stale_object(world):
    run, _ = await seed(world)
    async with world.sessions() as stale, world.sessions() as control:
        cached = await stale.get(PipelineRun, run.id)
        await PipelineService(control).cancel_run(run.id, world.org_a.id)
        await control.commit()
        outcome = await handle_execute_script(
            {"params": {"script_id": str(world.script.id)}}, cached, stale,
        )
        assert outcome.status == "failure"
        assert await stale.scalar(select(func.count()).select_from(Task).where(Task.org_id == world.org_a.id)) == 0


async def test_late_step_cannot_overwrite_cancellation_or_run_next_step(world, monkeypatch):
    from backend.services.orchestrator.step_handlers import StepResult

    run, _ = await seed(world)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(*, step, run, db):
        calls.append(step["id"])
        entered.set()
        await release.wait()
        return StepResult(status="success")

    async with world.sessions() as db:
        stored = await db.get(PipelineRun, run.id)
        stored.steps_snapshot = [{"id": "wait", "type": "delay", "on_success": "later"},
                                 {"id": "later", "type": "delay"}]
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.StepHandlerRegistry.execute", handler)
    pending = asyncio.create_task(PipelineExecutor()._execute_run(run.id))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with world.sessions() as db:
            await PipelineService(db).cancel_run(run.id, world.org_a.id)
            await db.commit()
        release.set()
        await asyncio.wait_for(pending, 2)
        assert calls == ["wait"]
        async with world.sessions() as db:
            assert (await db.get(PipelineRun, run.id)).status == PipelineRunStatus.CANCELLED
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def test_pending_cancellation_cannot_be_resumed_or_paused(world):
    run, _ = await seed(world, TaskStatus.RUNNING)
    async with world.sessions() as db:
        service = PipelineService(db)
        await service.cancel_run(run.id, world.org_a.id)
        await db.commit()
        for method in (service.pause_run, service.resume_run):
            with pytest.raises(HTTPException):
                await method(run.id, world.org_a.id)


async def test_nested_pipeline_cancellation_survives_executor_restart(world, monkeypatch):
    parent, _ = await seed(world)
    child, task = await seed(world, TaskStatus.RUNNING)
    async with world.sessions() as db:
        nested = await db.get(PipelineRun, child.id)
        nested.context = {"parent_run_id": str(parent.id)}
        await db.commit()
        requested = await PipelineService(db).cancel_run(parent.id, world.org_a.id)
        await db.commit()
        assert requested.status == PipelineRunStatus.RUNNING
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    await PipelineExecutor()._reconcile_cancellations(org_id=world.org_a.id)
    async with world.sessions() as db:
        assert (await db.get(PipelineRun, parent.id)).status == PipelineRunStatus.RUNNING
        assert (await db.get(PipelineRun, child.id)).cancel_requested_at is not None
        native = await db.get(Task, task.id)
        assert native.status == TaskStatus.RUNNING and native.cancel_requested_at is not None
        native.status = TaskStatus.CANCELLED
        native.finished_at = datetime.now(timezone.utc)
        await db.commit()
    await PipelineExecutor()._reconcile_cancellations(org_id=world.org_a.id)
    async with world.sessions() as db:
        assert (await db.get(PipelineRun, child.id)).status == PipelineRunStatus.CANCELLED
        assert (await db.get(PipelineRun, parent.id)).status == PipelineRunStatus.CANCELLED


async def test_cross_tenant_child_link_cannot_be_declared_stopped(world):
    run, task = await seed(world, TaskStatus.RUNNING)
    async with world.sessions() as db:
        foreign = await db.get(Task, task.id)
        foreign.org_id = world.org_b.id
        foreign.device_id = world.dev_b.id
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await PipelineService(db).cancel_run(run.id, world.org_a.id)
        assert error.value.status_code == 409
        await db.rollback()
        assert (await db.get(PipelineRun, run.id)).cancel_requested_at is None


async def test_parallel_rejects_untrackable_native_children_before_start(world):
    from backend.services.orchestrator.step_handlers import handle_parallel

    run, _ = await seed(world)
    run.steps_snapshot = [
        {"id": "first", "type": "execute_script", "params": {"script_id": str(world.script.id)}},
        {"id": "second", "type": "execute_script", "params": {"script_id": str(world.script.id)}},
    ]
    async with world.sessions() as db:
        result = await handle_parallel({"params": {"sub_steps": ["first", "second"]}}, run, db)
        assert result.status == "failure"
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.org_id == world.org_a.id)) == 0


@pytest.mark.parametrize("method,status", [("pause_run", PipelineRunStatus.RUNNING),
                                           ("resume_run", PipelineRunStatus.PAUSED)])
async def test_stale_pause_resume_cannot_overwrite_new_cancel_intent(world, method, status):
    run, _ = await seed(world, TaskStatus.RUNNING)
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.status = status
        await db.commit()
    async with world.sessions() as stale, world.sessions() as control:
        cached = await stale.get(PipelineRun, run.id)
        assert cached.cancel_requested_at is None
        await PipelineService(control).cancel_run(run.id, world.org_a.id)
        await control.commit()
        with pytest.raises(HTTPException):
            await getattr(PipelineService(stale), method)(run.id, world.org_a.id)
        await stale.rollback()
        stored = await stale.get(PipelineRun, run.id)
        assert stored.status == status and stored.cancel_requested_at is not None
