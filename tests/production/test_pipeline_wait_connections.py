"""Waiting pipelines must release real SQL connections, even in a one-slot pool."""

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.task import Task, TaskStatus
from backend.services.orchestrator.pipeline_executor import PipelineExecutor


@pytest.mark.parametrize("kind", ["delay", "execute_script", "sub_pipeline"])
async def test_wait_releases_single_pool_slot_and_survives_sql_idle_timeout(world, monkeypatch, kind):
    application = "audit-pipeline-wait-" + world.suffix
    engine = create_async_engine(
        world.engine.url, pool_size=1, max_overflow=0, pool_timeout=0.4,
        connect_args={"server_settings": {
            "application_name": application,
            "idle_in_transaction_session_timeout": "900ms",
        }},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with world.sessions() as db:
        nested = Pipeline(org_id=world.org_a.id, name="wait-child-fixture", steps=[])
        pipeline = Pipeline(org_id=world.org_a.id, name="wait-pool-fixture")
        db.add_all([pipeline, nested])
        await db.flush()
        params = {
            "delay": {"delay_ms": 1800},
            "execute_script": {"script_id": str(world.script.id)},
            "sub_pipeline": {"pipeline_id": str(nested.id)},
        }[kind]
        run = PipelineRun(
            org_id=world.org_a.id, pipeline_id=pipeline.id, device_id=world.dev_a.id,
            status=PipelineRunStatus.RUNNING, started_at=datetime.now(timezone.utc),
            steps_snapshot=[{"id": "wait", "type": kind, "params": params, "timeout_ms": 7000}],
        )
        db.add(run)
        await db.commit()

    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", sessions)
    entered = asyncio.Event()
    from backend.services.orchestrator.step_handlers import StepHandlerRegistry
    execute = StepHandlerRegistry.execute

    async def observe_entry(**kwargs):
        entered.set()
        return await execute(**kwargs)

    monkeypatch.setattr(StepHandlerRegistry, "execute", observe_entry)
    worker = asyncio.create_task(PipelineExecutor()._execute_run(run.id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        # First snapshot precedes the idle timeout; the second exceeds it and,
        # for child waits, also exercises the refresh -> next sleep boundary.
        for pause in (0.25, 1.05):
            await asyncio.sleep(pause)
            async with world.sessions() as observer:
                idle = await observer.scalar(text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE application_name = :app AND state = 'idle in transaction'"
                ), {"app": application})
                assert idle == 0, "Pipeline holds a transaction while waiting"
            # An independent API-like query uses the *same* one-slot pool.
            async with sessions() as control:
                assert await control.scalar(text("SELECT 1")) == 1
                current = await control.get(PipelineRun, run.id)
                expected = PipelineRunStatus.WAITING if kind == "sub_pipeline" else PipelineRunStatus.RUNNING
                assert current.status == expected

        async with sessions() as control:
            if kind == "execute_script":
                current = await control.get(PipelineRun, run.id)
                child = await control.get(Task, current.current_task_id)
                assert child.status == TaskStatus.QUEUED
                child.status = TaskStatus.COMPLETED
                child.result = {"isolated_receipt": True}
            elif kind == "sub_pipeline":
                child = await control.scalar(select(PipelineRun).where(
                    PipelineRun.org_id == world.org_a.id,
                    PipelineRun.context["parent_run_id"].astext == str(run.id),
                ))
                assert child.status == PipelineRunStatus.QUEUED
                child.status = PipelineRunStatus.COMPLETED
            await control.commit()
        await asyncio.wait_for(worker, 5)
        if kind == "sub_pipeline":
            resumed = PipelineExecutor()
            await resumed._poll_and_dispatch(org_id=world.org_a.id)
            await asyncio.wait_for(asyncio.gather(*resumed._tasks), 5)
        async with sessions() as control:
            final = await control.get(PipelineRun, run.id)
            assert final.status == PipelineRunStatus.COMPLETED
            steps = [entry for entry in final.step_logs if "status" in entry]
            assert len(steps) == 1 and steps[0]["status"] == "success"
            if kind == "sub_pipeline":
                assert steps[0]["duration_ms"] >= 1000
                assert [entry["event"] for entry in final.step_logs if "event" in entry] == ["wait_resumed"]
    finally:
        if not worker.done():
            worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await engine.dispose()
