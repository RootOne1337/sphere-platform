"""Nested waiting releases execution capacity but retains durable identity."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.services.orchestrator.pipeline_executor import PipelineExecutor
from backend.services.orchestrator.pipeline_service import PipelineService
from backend.services.orchestrator.pipeline_tenants import discover_work
from tests.production.test_pipeline_admission import cleanup


async def nested(world, count=1, *, timeout_ms=60000):
    async with world.sessions() as db:
        child = Pipeline(org_id=world.org_a.id, name="nested-empty-child", steps=[])
        parent = Pipeline(org_id=world.org_a.id, name="nested-parent")
        db.add_all([child, parent])
        await db.flush()
        parents = [PipelineRun(
            org_id=world.org_a.id, pipeline_id=parent.id, device_id=world.dev_a.id,
            status=PipelineRunStatus.QUEUED, steps_snapshot=[{
                "id": "nested", "type": "sub_pipeline", "timeout_ms": timeout_ms,
                "params": {"pipeline_id": str(child.id)},
            }],
        ) for _ in range(count)]
        db.add_all(parents)
        await db.commit()
    return parents, child


async def stored(world, run_id):
    async with world.sessions() as db:
        return await db.get(PipelineRun, run_id)


async def poll(world, executor):
    await executor._poll_and_dispatch(org_id=world.org_a.id)
    await asyncio.sleep(0.02)


async def until(world, executor, predicate):
    async def loop():
        while not await predicate():
            await poll(world, executor)
    await asyncio.wait_for(loop(), 12)


async def test_saturated_parents_release_slots_for_empty_children(runtime_db, monkeypatch):
    r = runtime_db
    parents, child = await nested(r.world, 10)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    async def complete():
        async with r.world.sessions() as db:
            count = await db.scalar(select(func.count()).select_from(PipelineRun).where(
                PipelineRun.id.in_([p.id for p in parents]), PipelineRun.status == PipelineRunStatus.COMPLETED,
            ))
            return count == 10
    try:
        await until(r.world, executor, complete)
        async with r.world.sessions() as db:
            children = list(await db.scalars(select(PipelineRun).where(
                PipelineRun.org_id == r.world.org_a.id, PipelineRun.pipeline_id == child.id,
            )))
            assert len(children) == 10 and all(c.status == PipelineRunStatus.COMPLETED for c in children)
        assert len(executor._tasks) <= 10
    finally:
        await cleanup(executor)


async def test_parked_parent_retains_deadline_and_identity_across_worker_restart(runtime_db, monkeypatch):
    r = runtime_db
    parents, child = await nested(r.world)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    first, second = PipelineExecutor(), PipelineExecutor()
    try:
        await first._poll_and_dispatch(org_id=r.world.org_a.id)
        await asyncio.wait_for(asyncio.gather(*first._tasks), 3)
        waiting = await stored(r.world, parents[0].id)
        assert waiting.status == PipelineRunStatus.WAITING
        assert waiting.execution_owner is None and waiting.execution_lease_until is None
        assert waiting.wait_deadline_at is not None and waiting.current_child_run_id is not None
        identity, deadline = waiting.current_child_run_id, waiting.wait_deadline_at
        async def completed():
            return (await stored(r.world, waiting.id)).status == PipelineRunStatus.COMPLETED
        await until(r.world, second, completed)
        async with r.world.sessions() as db:
            assert list(await db.scalars(select(PipelineRun.id).where(
                PipelineRun.pipeline_id == child.id, PipelineRun.org_id == r.world.org_a.id,
            ))) == [identity]
        final = await stored(r.world, waiting.id)
        assert final.wait_deadline_at is None
        assert final.finished_at <= deadline
    finally:
        await cleanup(first, second)


async def test_waiting_pause_resume_does_not_recreate_child_or_extend_deadline(runtime_db, monkeypatch):
    r = runtime_db
    parents, _ = await nested(r.world)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch(org_id=r.world.org_a.id)
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 3)
        waiting = await stored(r.world, parents[0].id)
        async with r.world.sessions() as db:
            await PipelineService(db).pause_run(waiting.id, r.world.org_a.id)
            (await db.get(PipelineRun, waiting.current_child_run_id)).status = PipelineRunStatus.COMPLETED
            await db.commit()
        await poll(r.world, executor)
        assert (await stored(r.world, waiting.id)).status == PipelineRunStatus.PAUSED
        async with r.world.sessions() as db:
            resumed = await PipelineService(db).resume_run(waiting.id, r.world.org_a.id)
            assert resumed.wait_deadline_at == waiting.wait_deadline_at
            assert resumed.current_child_run_id == waiting.current_child_run_id
            await db.commit()
        async def complete():
            return (await stored(r.world, waiting.id)).status == PipelineRunStatus.COMPLETED
        await until(r.world, executor, complete)
    finally:
        await cleanup(executor)


async def test_waiting_cancel_reconciles_child_without_replay(runtime_db, monkeypatch):
    r = runtime_db
    parents, _ = await nested(r.world)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch(org_id=r.world.org_a.id)
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 3)
        waiting = await stored(r.world, parents[0].id)
        async with r.world.sessions() as db:
            await PipelineService(db).cancel_run(waiting.id, r.world.org_a.id)
            await db.commit()
        await poll(r.world, executor)
        assert (await stored(r.world, waiting.id)).status == PipelineRunStatus.CANCELLED
        assert (await stored(r.world, waiting.current_child_run_id)).status == PipelineRunStatus.CANCELLED
        assert not executor._tasks
    finally:
        await cleanup(executor)


async def test_waiting_deadline_reviews_unfinished_child_without_renewing_wait(runtime_db, monkeypatch):
    r = runtime_db
    parents, _ = await nested(r.world)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch(org_id=r.world.org_a.id)
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 3)
        waiting = await stored(r.world, parents[0].id)
        async with r.world.sessions() as db:
            row = await db.get(PipelineRun, waiting.id)
            # Persisted absolute deadline remains authoritative even when the
            # source pipeline's global timeout has subsequently been extended.
            (await db.get(Pipeline, row.pipeline_id)).global_timeout_ms = 172800000
            row.wait_deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            child = await db.get(PipelineRun, row.current_child_run_id)
            child.status, child.execution_owner = PipelineRunStatus.RUNNING, uuid.uuid4()
            child.execution_lease_until = datetime.now(timezone.utc) + timedelta(minutes=5)
            await db.commit()
        async def paused():
            return (await stored(r.world, waiting.id)).status == PipelineRunStatus.PAUSED
        await until(r.world, executor, paused)
        reviewed = await stored(r.world, waiting.id)
        assert reviewed.execution_phase == "unknown"
        assert reviewed.current_child_run_id == waiting.current_child_run_id
        assert (await stored(r.world, waiting.current_child_run_id)).status == PipelineRunStatus.RUNNING
    finally:
        await cleanup(executor)


async def test_waiting_discovery_skips_active_child_until_terminal_or_deadline(runtime_db, monkeypatch):
    r = runtime_db
    parents, _ = await nested(r.world)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    async with r.world.sessions() as db:
        await db.execute(text(f'GRANT EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) TO "{r.role}"'))
        await db.commit()
    try:
        await executor._poll_and_dispatch(org_id=r.world.org_a.id)
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 3)
        waiting = await stored(r.world, parents[0].id)
        async with r.world.sessions() as db:
            row = await db.get(PipelineRun, waiting.id)
            row.updated_at = datetime(1880, 1, 1, tzinfo=timezone.utc)
            await db.commit()
        for scope in ({}, {"org_id": r.world.org_a.id}):
            assert waiting.id not in {row[0] for row in await discover_work(r.sessions, "recovery", **scope)}
        async with r.world.sessions() as db:
            (await db.get(PipelineRun, waiting.current_child_run_id)).status = PipelineRunStatus.COMPLETED
            await db.commit()
        for scope in ({}, {"org_id": r.world.org_a.id}):
            assert waiting.id in {row[0] for row in await discover_work(r.sessions, "recovery", **scope)}
    finally:
        await cleanup(executor)
        async with r.world.sessions() as db:
            await db.execute(text(f'REVOKE EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) FROM "{r.role}"'))
            await db.commit()


@pytest.mark.parametrize("lost_ack", [False, True])
async def test_wait_checkpoint_rollback_or_lost_ack_never_duplicates_child(runtime_db, monkeypatch, lost_ack):
    r = runtime_db
    parents, child = await nested(r.world)
    triggered = False

    @asynccontextmanager
    async def sessions():
        async with r.sessions() as db:
            commit = db.commit
            async def fault():
                nonlocal triggered
                parking = any(isinstance(row, PipelineRun) and row.id == parents[0].id
                              and row.status == PipelineRunStatus.WAITING for row in db.identity_map.values())
                if parking and not triggered:
                    triggered = True
                    if lost_ack:
                        await commit()
                    raise ConnectionError("isolated nested waiting commit boundary")
                await commit()
            db.commit = fault
            yield db
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", sessions)
    first, second = PipelineExecutor(), PipelineExecutor()
    try:
        await first._poll_and_dispatch(org_id=r.world.org_a.id)
        await asyncio.wait_for(asyncio.gather(*first._tasks), 3)
        assert triggered
        row = await stored(r.world, parents[0].id)
        async with r.world.sessions() as db:
            children = list(await db.scalars(select(PipelineRun.id).where(PipelineRun.pipeline_id == child.id)))
        if not lost_ack:
            assert children == [] and row.current_child_run_id is None
            assert row.status == PipelineRunStatus.PAUSED and row.execution_phase == "unknown"
        else:
            assert children == [row.current_child_run_id] and row.status == PipelineRunStatus.WAITING
            async def complete():
                return (await stored(r.world, row.id)).status == PipelineRunStatus.COMPLETED
            await until(r.world, second, complete)
            async with r.world.sessions() as db:
                assert list(await db.scalars(select(PipelineRun.id).where(PipelineRun.pipeline_id == child.id))) == children
    finally:
        await cleanup(first, second)


async def test_nested_three_levels_progress_with_single_executor_slot(runtime_db, monkeypatch):
    r = runtime_db
    parents, child = await nested(r.world)
    async with r.world.sessions() as db:
        leaf = Pipeline(org_id=r.world.org_a.id, name="nested-leaf", steps=[])
        db.add(leaf)
        await db.flush()
        (await db.get(Pipeline, child.id)).steps = [{"id": "grandchild", "type": "sub_pipeline",
            "timeout_ms": 60000, "params": {"pipeline_id": str(leaf.id)}}]
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor._MAX_CONCURRENT_RUNS", 1)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    async def complete():
        assert len(executor._tasks) <= 1
        return (await stored(r.world, parents[0].id)).status == PipelineRunStatus.COMPLETED
    try:
        await until(r.world, executor, complete)
        async with r.world.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(PipelineRun).where(
                PipelineRun.org_id == r.world.org_a.id, PipelineRun.status == PipelineRunStatus.COMPLETED,
            )) == 3
    finally:
        await cleanup(executor)


async def test_timed_out_sql_handler_rolls_back_before_reloading_generation(world, monkeypatch):
    from backend.services.orchestrator.step_handlers import StepHandlerRegistry
    from tests.production.test_pipeline_recovery import seed
    run = await seed(world, kind="sub_pipeline")
    async with world.sessions() as db:
        row = await db.get(PipelineRun, run.id)
        row.steps_snapshot = [{**row.steps_snapshot[0], "timeout_ms": 500}]
        await db.commit()
    entered = False
    async def slow_sql(step, run, db):
        nonlocal entered
        entered = True
        await db.execute(text("SELECT pg_sleep(5)"))
    monkeypatch.setitem(StepHandlerRegistry._handlers, "sub_pipeline", slow_sql)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    await PipelineExecutor()._execute_run(run.id)
    assert entered
    result = await stored(world, run.id)
    assert result.status == PipelineRunStatus.PAUSED and result.execution_phase == "unknown"


async def test_waiting_with_lost_child_reference_requires_review_not_another_child(runtime_db, monkeypatch):
    r = runtime_db
    parents, child = await nested(r.world)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch(org_id=r.world.org_a.id)
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 3)
        waiting = await stored(r.world, parents[0].id)
        async with r.world.sessions() as db:
            (await db.get(PipelineRun, waiting.id)).current_child_run_id = None
            await db.commit()
        await poll(r.world, executor)
        reviewed = await stored(r.world, waiting.id)
        assert reviewed.status == PipelineRunStatus.PAUSED and reviewed.execution_phase == "unknown"
        assert reviewed.context["_recovery"]["reason"] == "waiting_child_identity_missing"
        async with r.world.sessions() as db:
            assert list(await db.scalars(select(PipelineRun.id).where(PipelineRun.pipeline_id == child.id))) == [waiting.current_child_run_id]
    finally:
        await cleanup(executor)
