"""Pipeline recovery uses persisted step identity, never blind action replay."""

import asyncio
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.task import Task, TaskStatus
from backend.services.orchestrator.pipeline_executor import PipelineExecutor
from backend.services.orchestrator.pipeline_service import PipelineService
from backend.services.orchestrator.step_handlers import StepHandlerRegistry, StepResult
from tests.production.test_pipeline_admission import cleanup, isolated_sessions, wait_until


async def seed(world, *, kind="delay", params=None, status=PipelineRunStatus.RUNNING):
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name="recovery-fixture")
        db.add(pipeline)
        await db.flush()
        run = PipelineRun(
            org_id=world.org_a.id, pipeline_id=pipeline.id, device_id=world.dev_a.id,
            status=status, started_at=datetime.now(timezone.utc),
            steps_snapshot=[{"id": "first", "type": kind, "params": params or {"delay_ms": 100},
                             "timeout_ms": 10000}],
        )
        db.add(run)
        await db.commit()
    return run


async def test_resume_cannot_admit_another_executor_while_paused_step_is_still_running(world, monkeypatch):
    run = await seed(world)
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(**kwargs):
        entered.set()
        await release.wait()
        return StepResult()

    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    monkeypatch.setattr(StepHandlerRegistry, "execute", handler)
    worker = asyncio.create_task(PipelineExecutor()._execute_run(run.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with world.sessions() as db:
            await PipelineService(db).pause_run(run.id, world.org_a.id)
            await db.commit()
            with pytest.raises(HTTPException) as error:
                await PipelineService(db).resume_run(run.id, world.org_a.id)
            assert error.value.status_code == 409
    finally:
        release.set()
        await asyncio.gather(worker, return_exceptions=True)


async def test_pause_during_last_step_does_not_leave_completed_action_replayable(world, monkeypatch):
    run = await seed(world)
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(**kwargs):
        entered.set()
        await release.wait()
        return StepResult()

    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    monkeypatch.setattr(StepHandlerRegistry, "execute", handler)
    worker = asyncio.create_task(PipelineExecutor()._execute_run(run.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with world.sessions() as db:
            await PipelineService(db).pause_run(run.id, world.org_a.id)
            await db.commit()
        release.set()
        await asyncio.wait_for(worker, 3)
        async with world.sessions() as db:
            stored = await db.get(PipelineRun, run.id)
            assert stored.status == PipelineRunStatus.COMPLETED
            assert stored.current_step_id is None
            assert len(stored.step_logs) == 1
    finally:
        release.set()
        await asyncio.gather(worker, return_exceptions=True)


async def test_child_identity_survives_loss_after_receipt_before_step_checkpoint(world, monkeypatch):
    run = await seed(world, kind="execute_script", params={"script_id": str(world.script.id)})
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    execute = StepHandlerRegistry.execute

    async def lose_after_receipt(**kwargs):
        result = await execute(**kwargs)
        assert result.status == "success"
        raise asyncio.CancelledError()

    monkeypatch.setattr(StepHandlerRegistry, "execute", lose_after_receipt)
    worker = asyncio.create_task(PipelineExecutor()._execute_run(run.id))
    child = None
    try:
        async def complete_child():
            nonlocal child
            while child is None:
                async with world.sessions() as db:
                    child = await db.scalar(select(Task).where(Task.org_id == world.org_a.id))
                    if child:
                        child.status = TaskStatus.COMPLETED
                        child.result = {"receipt": "isolated"}
                        await db.commit()
                await asyncio.sleep(0.01)
        await asyncio.wait_for(complete_child(), 3)
        await asyncio.gather(worker, return_exceptions=True)
        async with world.sessions() as db:
            stored = await db.get(PipelineRun, run.id)
            assert stored.current_task_id == child.id
            assert stored.step_logs == []
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_claim_preserves_original_global_timeout_origin(world, monkeypatch):
    run = await seed(world, status=PipelineRunStatus.QUEUED)
    origin = datetime.now(timezone.utc) - timedelta(hours=25)
    async with world.sessions() as db:
        stored = await db.get(PipelineRun, run.id)
        stored.started_at = origin
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    executor = PipelineExecutor()
    async def hold(run_id):
        await asyncio.Event().wait()
    monkeypatch.setattr(executor, "_execute_run", hold)
    try:
        await executor._poll_and_dispatch(org_id=world.org_a.id)
        async with world.sessions() as db:
            assert (await db.get(PipelineRun, run.id)).started_at == origin
    finally:
        await cleanup(executor)


async def test_fresh_executor_does_not_leave_unowned_running_work_forever(world, monkeypatch):
    run = await seed(world)
    async with world.sessions() as db:
        stored = await db.get(PipelineRun, run.id)
        stored.started_at = datetime.now(timezone.utc) - timedelta(hours=25)
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    fresh = PipelineExecutor()
    try:
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        async with world.sessions() as db:
            stored = await db.get(PipelineRun, run.id)
            assert stored.status != PipelineRunStatus.RUNNING or fresh._tasks
    finally:
        await cleanup(fresh)


async def expire(world, run_id):
    async with world.sessions() as db:
        run = await db.get(PipelineRun, run_id, with_for_update=True)
        run.execution_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()


async def finish_child(world, run_id):
    while True:
        async with world.sessions() as db:
            run = await db.get(PipelineRun, run_id)
            if run.current_task_id:
                child = await db.get(Task, run.current_task_id)
                child.status = TaskStatus.COMPLETED
                child.result = {"receipt": "isolated"}
                await db.commit()
                return child.id
        await asyncio.sleep(0.01)


async def wait_for_completion(world, run_id):
    while True:
        async with world.sessions() as db:
            run = await db.get(PipelineRun, run_id)
            if run.status in (PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED, PipelineRunStatus.PAUSED):
                return run
        await asyncio.sleep(0.01)


async def wait_for_child(world, run_id):
    while True:
        async with world.sessions() as db:
            current = await db.get(PipelineRun, run_id)
            if current.current_task_id:
                return current.current_task_id
        await asyncio.sleep(0.01)


async def test_hard_killed_worker_recovers_same_persisted_task_without_redis_or_android(world, monkeypatch, tmp_path):
    run = await seed(world, status=PipelineRunStatus.QUEUED, kind="execute_script",
                     params={"script_id": str(world.script.id)})
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.steps_snapshot = [{**current.steps_snapshot[0], "timeout_ms": 60000}]
        await db.commit()
    with (tmp_path / "worker.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "tests.production.pipeline_worker_probe", str(world.org_a.id)],
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        fresh = PipelineExecutor()
        try:
            # Receipt is deliberately written by the fixture; this checks backend
            # process recovery, not device execution or an Android ACK.
            child_id = await asyncio.wait_for(wait_for_child(world, run.id), 15)
            process.kill()
            await asyncio.to_thread(process.wait, 5)
            assert process.returncode is not None
            assert await finish_child(world, run.id) == child_id
            await expire(world, run.id)  # Deterministic expiry after confirmed OS death.
            monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
            await fresh._poll_and_dispatch(org_id=world.org_a.id)
            result = await asyncio.wait_for(wait_for_completion(world, run.id), 5)
            assert result.status == PipelineRunStatus.COMPLETED
            assert result.context["last_task_id"] == str(child_id)
            async with world.sessions() as db:
                assert list(await db.scalars(select(Task.id).where(Task.org_id == world.org_a.id))) == [child_id]
            assert any(entry.get("event") == "lease_recovered" for entry in result.step_logs)
        finally:
            if process.poll() is None:
                process.kill()
                await asyncio.to_thread(process.wait, 5)
            await cleanup(fresh)


@pytest.mark.parametrize("kind", ["action", "n8n_workflow", "loop", "wait_for_event"])
async def test_unknown_external_effect_is_paused_for_review_not_replayed(world, monkeypatch, kind):
    run = await seed(world, kind=kind)
    async with world.sessions() as db:
        stored = await db.get(PipelineRun, run.id)
        stored.execution_owner = uuid.uuid4()
        stored.execution_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        stored.execution_phase = "in_flight"
        stored.current_step_id = "first"
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    async def unexpected(**kwargs):
        pytest.fail("Unconfirmed external effect must never be replayed")
    monkeypatch.setattr(StepHandlerRegistry, "execute", unexpected)
    fresh = PipelineExecutor()
    try:
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        async with world.sessions() as db:
            stored = await db.get(PipelineRun, run.id)
            assert stored.status == PipelineRunStatus.PAUSED and stored.execution_phase == "unknown"
            assert stored.context["_recovery"]["required"] is True
            with pytest.raises(HTTPException) as error:
                await PipelineService(db).resume_run(run.id, world.org_a.id)
            assert error.value.status_code == 409
        assert not fresh._tasks
    finally:
        await cleanup(fresh)


async def test_stale_generation_cannot_adopt_new_claim_from_same_executor(world, monkeypatch):
    run = await seed(world)
    executor = PipelineExecutor()
    async with world.sessions() as db:
        stored = await db.get(PipelineRun, run.id)
        stored.execution_owner = executor._owner
        stored.execution_generation = 2
        stored.execution_lease_until = datetime.now(timezone.utc) + timedelta(seconds=30)
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    calls = []
    async def handler(**kwargs):
        calls.append(kwargs["step"]["id"])
        return StepResult()
    monkeypatch.setattr(StepHandlerRegistry, "execute", handler)
    await executor._execute_run_safe(run.id, 1)
    assert calls == []
    await executor._execute_run_safe(run.id, 2)
    assert calls == ["first"]


async def test_late_old_result_cannot_overwrite_recovered_generation(world, monkeypatch):
    run = await seed(world, kind="condition")
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def handler(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
            return StepResult(context_updates={"owner_result": "stale"})
        return StepResult(context_updates={"owner_result": "current"})
    monkeypatch.setattr(StepHandlerRegistry, "execute", handler)
    old, fresh = PipelineExecutor(), PipelineExecutor()
    worker = asyncio.create_task(old._execute_run(run.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await expire(world, run.id)
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        result = await asyncio.wait_for(wait_for_completion(world, run.id), 3)
        assert result.context["owner_result"] == "current"
        release.set()
        await asyncio.wait_for(worker, 3)
        async with world.sessions() as db:
            result = await db.get(PipelineRun, run.id)
            assert result.context["owner_result"] == "current"
            assert len([entry for entry in result.step_logs if entry.get("status") == "success"]) == 1
    finally:
        release.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await cleanup(fresh)


async def test_checkpoint_survives_loss_after_commit_before_next_step(world, monkeypatch):
    run = await seed(world, kind="action")
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.steps_snapshot = [{**current.steps_snapshot[0], "on_success": "second"},
                                  {"id": "second", "type": "action", "timeout_ms": 10000}]
        await db.commit()
    calls = []
    async def handler(**kwargs):
        calls.append(kwargs["step"]["id"])
        return StepResult()
    monkeypatch.setattr(StepHandlerRegistry, "execute", handler)
    injected = False
    @asynccontextmanager
    async def sessions():
        nonlocal injected
        async with world.sessions() as db:
            commit = db.commit
            async def commit_then_die():
                nonlocal injected
                checkpoint = any(isinstance(obj, PipelineRun) and obj.id == run.id
                                 and obj.current_step_id == "second" and obj.execution_phase == "ready"
                                 for obj in db.identity_map.values())
                await commit()
                if checkpoint and not injected:
                    injected = True
                    raise asyncio.CancelledError()
            db.commit = commit_then_die
            yield db
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", sessions)
    await asyncio.gather(asyncio.create_task(PipelineExecutor()._execute_run(run.id)), return_exceptions=True)
    assert injected and calls == ["first"]
    fresh = PipelineExecutor()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    try:
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        result = await asyncio.wait_for(wait_for_completion(world, run.id), 3)
        assert result.status == PipelineRunStatus.COMPLETED
        assert calls == ["first", "second"]
    finally:
        await cleanup(fresh)


async def test_two_recovery_workers_do_not_execute_one_expired_run_twice(world, monkeypatch):
    run = await seed(world)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    entered, release = [], asyncio.Event()
    async def handler(**kwargs):
        entered.append(kwargs["run"].id)
        await release.wait()
        return StepResult()
    monkeypatch.setattr(StepHandlerRegistry, "execute", handler)
    workers = [PipelineExecutor(), PipelineExecutor()]
    try:
        await asyncio.gather(*(worker._poll_and_dispatch(org_id=world.org_a.id) for worker in workers))
        await wait_until(lambda: bool(entered))
        assert entered == [run.id]
        assert sum(len(worker._tasks) for worker in workers) == 1
    finally:
        release.set()
        await cleanup(*workers)


async def test_pending_child_timeout_never_releases_identity_or_launches_retry(world, monkeypatch):
    run = await seed(world, kind="execute_script", params={"script_id": str(world.script.id)})
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.steps_snapshot = [{**current.steps_snapshot[0], "timeout_ms": 100, "retries": 3}]
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    await PipelineExecutor()._execute_run(run.id)
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        children = list(await db.scalars(select(Task).where(Task.org_id == world.org_a.id)))
        assert len(children) == 1 and current.current_task_id == children[0].id
        assert current.status == PipelineRunStatus.PAUSED and current.execution_phase == "unknown"
        assert children[0].status == TaskStatus.QUEUED


async def test_heartbeat_renews_live_owner_and_cannot_renew_expired_generation(world, monkeypatch):
    from backend.services.orchestrator.pipeline_ownership import Ownership
    from backend.services.orchestrator.pipeline_recovery import renew_lease
    run = await seed(world)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    monkeypatch.setattr("backend.services.orchestrator.pipeline_recovery.HEARTBEAT_SECONDS", 0.05)
    entered, release = asyncio.Event(), asyncio.Event()
    async def handler(**kwargs):
        entered.set()
        await release.wait()
        return StepResult()
    monkeypatch.setattr(StepHandlerRegistry, "execute", handler)
    owner, other = PipelineExecutor(), PipelineExecutor()
    worker = asyncio.create_task(owner._execute_run(run.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with world.sessions() as db:
            initial = await db.get(PipelineRun, run.id)
        await asyncio.sleep(0.16)
        await other._poll_and_dispatch(org_id=world.org_a.id)
        async with world.sessions() as db:
            current = await db.get(PipelineRun, run.id)
            assert current.execution_lease_until > initial.execution_lease_until
        assert not other._tasks
        release.set()
        await asyncio.wait_for(worker, 3)
        assert not await renew_lease(world.sessions, Ownership(run.id, initial.execution_owner, initial.execution_generation))
    finally:
        release.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await cleanup(other)


async def test_recovery_reuses_persisted_nested_run(world, monkeypatch):
    child = await seed(world, status=PipelineRunStatus.QUEUED)
    parent = await seed(world, kind="sub_pipeline", params={"pipeline_id": str(child.pipeline_id)})
    async with world.sessions() as db:
        current = await db.get(PipelineRun, parent.id)
        current.current_step_id = "first"
        current.current_child_run_id = child.id
        current.execution_phase = "in_flight"
        current.step_started_at = datetime.now(timezone.utc)
        current.execution_owner = uuid.uuid4()
        current.execution_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        nested = await db.get(PipelineRun, child.id)
        nested.context = {"parent_run_id": str(parent.id), "native_result": "retained"}
        nested.status = PipelineRunStatus.COMPLETED
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    fresh = PipelineExecutor()
    try:
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        result = await asyncio.wait_for(wait_for_completion(world, parent.id), 4)
        assert result.status == PipelineRunStatus.COMPLETED
        assert result.context["sub_pipeline_result"]["native_result"] == "retained"
        async with world.sessions() as db:
            children = list(await db.scalars(select(PipelineRun.id).where(
                PipelineRun.org_id == world.org_a.id,
                PipelineRun.context["parent_run_id"].astext == str(parent.id),
            )))
            assert children == [child.id]
    finally:
        await cleanup(fresh)


async def test_elapsed_delay_is_not_restarted_after_worker_loss(world, monkeypatch):
    run = await seed(world, params={"delay_ms": 3000})
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.current_step_id = "first"
        current.execution_phase = "in_flight"
        current.step_started_at = datetime.now(timezone.utc) - timedelta(seconds=4)
        current.execution_owner = uuid.uuid4()
        current.execution_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    async def unexpected(**kwargs):
        pytest.fail("The persisted delay is already elapsed")
    monkeypatch.setattr(StepHandlerRegistry, "execute", unexpected)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    fresh = PipelineExecutor()
    try:
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        result = await asyncio.wait_for(wait_for_completion(world, run.id), 3)
        assert result.status == PipelineRunStatus.COMPLETED
    finally:
        await cleanup(fresh)


@pytest.mark.parametrize("foreign", [False, True])
async def test_recovered_task_link_never_creates_replacement_for_wrong_device_or_tenant(world, monkeypatch, foreign):
    run = await seed(world, kind="execute_script", params={"script_id": str(world.script.id)})
    async with world.sessions() as db:
        task = Task(org_id=world.org_b.id if foreign else world.org_a.id,
                    device_id=world.dev_b.id if foreign else world.dev_a2.id,
                    script_id=world.script.id, script_version_id=world.version.id, status=TaskStatus.COMPLETED)
        db.add(task)
        await db.flush()
        current = await db.get(PipelineRun, run.id)
        current.current_task_id = task.id
        current.current_step_id = "first"
        current.execution_phase = "in_flight"
        current.execution_owner = uuid.uuid4()
        current.execution_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    fresh = PipelineExecutor()
    try:
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        result = await asyncio.wait_for(wait_for_completion(world, run.id), 3)
        assert result.status == PipelineRunStatus.PAUSED and result.execution_phase == "unknown"
        assert result.current_task_id == task.id
        async with world.sessions() as db:
            assert list(await db.scalars(select(Task.id).where(Task.org_id.in_([world.org_a.id, world.org_b.id])))) == [task.id]
    finally:
        await cleanup(fresh)


async def test_shutdown_drains_then_releases_coroutines_without_losing_native_child(world, monkeypatch):
    run = await seed(world, status=PipelineRunStatus.QUEUED, kind="execute_script",
                     params={"script_id": str(world.script.id)})
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor._DRAIN_SECONDS", 0.01)
    owner, fresh = PipelineExecutor(), PipelineExecutor()
    try:
        await owner._poll_and_dispatch(org_id=world.org_a.id)
        async def admitted():
            while True:
                async with world.sessions() as db:
                    current = await db.get(PipelineRun, run.id)
                    if current.current_task_id:
                        return current.current_task_id
                await asyncio.sleep(0.01)
        child_id = await asyncio.wait_for(admitted(), 3)
        await asyncio.wait_for(owner.stop(), 3)
        assert not owner._tasks
        async with world.sessions() as db:
            current = await db.get(PipelineRun, run.id)
            assert current.status == PipelineRunStatus.RUNNING and current.current_task_id == child_id
            assert current.execution_phase == "in_flight"
            assert (await db.get(Task, child_id)).status == TaskStatus.QUEUED
        await expire(world, run.id)
        await finish_child(world, run.id)
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        result = await asyncio.wait_for(wait_for_completion(world, run.id), 4)
        assert result.status == PipelineRunStatus.COMPLETED
        assert result.context["last_task_id"] == str(child_id)
    finally:
        await cleanup(owner, fresh)


@pytest.mark.parametrize("database_error", [False, True, "timeout"])
async def test_failed_heartbeat_stops_owner_without_fabricating_failed_outcome(world, monkeypatch, database_error):
    run = await seed(world, kind="action")
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    monkeypatch.setattr("backend.services.orchestrator.pipeline_recovery.HEARTBEAT_SECONDS", 0.02)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_recovery.HEARTBEAT_TIMEOUT_SECONDS", 1)
    entered = asyncio.Event()
    async def handler(**kwargs):
        entered.set()
        await asyncio.Event().wait()
    async def cannot_renew(*args):
        await entered.wait()  # Inject failure after the effect entered, not during initial SQL setup.
        if database_error == "timeout":
            await asyncio.Event().wait()
        if database_error:
            raise ConnectionError("isolated lease renewal failure")
        return False
    monkeypatch.setattr(StepHandlerRegistry, "execute", handler)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_recovery.renew_lease", cannot_renew)
    worker = asyncio.create_task(PipelineExecutor()._execute_run(run.id))
    fresh = PipelineExecutor()
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await asyncio.wait_for(asyncio.gather(worker, return_exceptions=True), 3)
        assert worker.cancelled()
        async with world.sessions() as db:
            current = await db.get(PipelineRun, run.id)
            assert current.status == PipelineRunStatus.RUNNING
            assert current.execution_phase == "in_flight" and current.finished_at is None
        await expire(world, run.id)
        await fresh._poll_and_dispatch(org_id=world.org_a.id)
        result = await wait_for_completion(world, run.id)
        assert result.status == PipelineRunStatus.PAUSED and result.execution_phase == "unknown"
        assert not fresh._tasks
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await cleanup(fresh)


@pytest.mark.parametrize("kind", ["action", "n8n_workflow", "parallel", "loop"])
async def test_partially_failed_external_step_is_not_retried(world, monkeypatch, kind):
    run = await seed(world, kind=kind)
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.steps_snapshot = [{**current.steps_snapshot[0], "retries": 3}]
        await db.commit()
    calls = []
    async def partially_failed(**kwargs):
        calls.append(kind)
        return StepResult(status="failure", error="Effect sent before response failed")
    monkeypatch.setattr(StepHandlerRegistry, "execute", partially_failed)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    await PipelineExecutor()._execute_run(run.id)
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        assert current.status == PipelineRunStatus.PAUSED and current.execution_phase == "unknown"
    assert calls == [kind]


async def test_expired_lease_is_fenced_after_waiting_for_sql_row_lock(world):
    from sqlalchemy import text

    from backend.services.orchestrator.pipeline_ownership import (
        Ownership,
        PipelineLeaseLost,
        current_ownership,
        fence_write,
    )
    run = await seed(world)
    owner = uuid.uuid4()
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.execution_owner = owner
        current.execution_generation = 1
        current.execution_lease_until = datetime.now(timezone.utc) + timedelta(seconds=1)
        await db.commit()
    token = current_ownership.set(Ownership(run.id, owner, 1))
    try:
        async with world.sessions() as stale:
            cached = await stale.get(PipelineRun, run.id)  # Start an old transaction.
            async with world.sessions() as blocker:
                await blocker.get(PipelineRun, run.id, with_for_update=True)
                fence = asyncio.create_task(fence_write(stale, cached))
                # Simulates a lock held past the lease, without touching pilot SQL.
                await blocker.execute(text("SELECT pg_sleep(1.1)"))
                await blocker.commit()
            with pytest.raises(PipelineLeaseLost):
                await fence
    finally:
        current_ownership.reset(token)


async def test_parallel_delay_children_share_fenced_session_without_concurrent_sql(world, monkeypatch):
    run = await seed(world, kind="parallel", params={"sub_steps": ["left", "right"]})
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.steps_snapshot = [current.steps_snapshot[0],
                                  {"id": "left", "type": "delay", "params": {"delay_ms": 100}},
                                  {"id": "right", "type": "delay", "params": {"delay_ms": 100}}]
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    await PipelineExecutor()._execute_run(run.id)
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        assert current.status == PipelineRunStatus.COMPLETED
        assert current.step_logs[-1]["output"]["successes"] == 2


async def test_heartbeat_blocked_past_expiry_cannot_resurrect_lease(world):
    from sqlalchemy import text

    from backend.services.orchestrator.pipeline_ownership import Ownership
    from backend.services.orchestrator.pipeline_recovery import renew_lease
    run = await seed(world)
    owner = uuid.uuid4()
    async with world.sessions() as db:
        current = await db.get(PipelineRun, run.id)
        current.execution_owner = owner
        current.execution_generation = 1
        current.execution_lease_until = datetime.now(timezone.utc) + timedelta(seconds=1)
        await db.commit()
    async with world.sessions() as blocker:
        await blocker.get(PipelineRun, run.id, with_for_update=True)
        renewal = asyncio.create_task(renew_lease(world.sessions, Ownership(run.id, owner, 1)))
        await blocker.execute(text("SELECT pg_sleep(1.1)"))
        await blocker.commit()
    assert await renewal is False
