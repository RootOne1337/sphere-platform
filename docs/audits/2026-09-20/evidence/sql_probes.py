"""Diagnostic reproductions of OPEN findings; intentionally fail until repaired.

Run only via isolated audit fixture configuration; never on pilot services.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select

from backend.models.device import Device
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.task import Task
from backend.models.task_batch import TaskBatch
from backend.schemas.batch import BatchExecutionRequest
from backend.services.batch_service import BatchService, _background_tasks
from backend.services.orchestrator.pipeline_executor import PipelineExecutor


def scoped_sessions(world):
    # Isolate the poller's candidate set from historical disposable fixtures.
    @asynccontextmanager
    async def factory():
        async with world.sessions() as db:
            execute = db.execute

            async def scoped(statement, *args, **kwargs):
                if any(
                    d.get("entity") is PipelineRun
                    for d in getattr(statement, "column_descriptions", [])
                ):
                    statement = statement.where(PipelineRun.org_id == world.org_a.id)
                return await execute(statement, *args, **kwargs)

            db.execute = scoped
            yield db

    return factory


async def make_runs(world, count=1, status=PipelineRunStatus.QUEUED):
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name="readiness32 disposable probe")
        db.add(pipeline)
        await db.flush()
        runs = []
        for i in range(count):
            device = Device(org_id=world.org_a.id, name=f"readiness32-{i}")
            db.add(device)
            await db.flush()
            run = PipelineRun(
                org_id=world.org_a.id,
                pipeline_id=pipeline.id,
                device_id=device.id,
                steps_snapshot=[
                    {
                        "id": "wait",
                        "type": "delay",
                        "params": {"delay_ms": 300000},
                        "timeout_ms": 310000,
                    }
                ],
                status=status,
                started_at=datetime.now(timezone.utc) - timedelta(hours=25)
                if status == PipelineRunStatus.RUNNING
                else None,
            )
            db.add(run)
            runs.append(run)
        await db.commit()
    return pipeline, runs


async def test_pipeline_claim_does_not_exceed_execution_capacity(world, monkeypatch):
    pipeline, runs = await make_runs(world, 32)
    monkeypatch.setattr(
        "backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", scoped_sessions(world)
    )
    engine = PipelineExecutor()
    entered = []
    release = asyncio.Event()

    async def hold(run_id):
        entered.append(run_id)
        await release.wait()

    engine._execute_run = hold
    try:
        for _ in range(4):
            await engine._poll_and_dispatch()
            await asyncio.sleep(0.02)
        async with world.sessions() as db:
            running = await db.scalar(
                select(func.count())
                .select_from(PipelineRun)
                .where(
                    PipelineRun.pipeline_id == pipeline.id,
                    PipelineRun.status == PipelineRunStatus.RUNNING,
                )
            )
        assert len(entered) == 10
        print(
            {
                "executing": len(entered),
                "claimed_running": running,
                "background_tasks": len(engine._tasks),
            }
        )
        assert (
            running <= 10
        ), "Queued behind semaphore must not be claimed as RUNNING without a recoverable lease"
    finally:
        tasks = list(engine._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_restarted_executor_reconciles_old_running_intent(world, monkeypatch):
    pipeline, runs = await make_runs(world, status=PipelineRunStatus.RUNNING)
    monkeypatch.setattr(
        "backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", scoped_sessions(world)
    )
    restarted = PipelineExecutor()
    try:
        await restarted._poll_and_dispatch()
        async with world.sessions() as db:
            run = await db.get(PipelineRun, runs[0].id)
            print(
                {
                    "status_after_restart_poll": run.status,
                    "claimed_tasks": len(restarted._tasks),
                    "age_hours": 25,
                }
            )
            assert (
                run.status != PipelineRunStatus.RUNNING or restarted._tasks
            ), "Orphan RUNNING work remains unreconciled"
    finally:
        tasks = list(restarted._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_delay_step_does_not_hold_idle_sql_transaction(world, monkeypatch):
    _, runs = await make_runs(world, status=PipelineRunStatus.RUNNING)
    async with world.sessions() as db:
        run = await db.get(PipelineRun, runs[0].id)
        run.started_at = datetime.now(timezone.utc)
        await db.commit()
    monkeypatch.setattr(
        "backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions
    )
    import backend.services.orchestrator.step_handlers as handlers

    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_delay(seconds):
        entered.set()
        await release.wait()

    # Replace only the handler's namespace, not global asyncio.sleep.
    monkeypatch.setattr(
        handlers,
        "asyncio",
        SimpleNamespace(
            sleep=hold_delay, wait_for=asyncio.wait_for, TimeoutError=asyncio.TimeoutError
        ),
    )
    engine = PipelineExecutor()
    task = asyncio.create_task(engine._execute_run(runs[0].id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        from sqlalchemy import text

        async with world.engine.connect() as db:
            idle = await db.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction'"
                )
            )
        print({"idle_sql_transactions_during_delay": idle})
        assert idle == 0, "Delay-only step retains a PostgreSQL connection/transaction across sleep"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_interrupted_batch_preserves_unsubmitted_device_plan(world, monkeypatch):
    import backend.services.batch_service as batches

    entered = asyncio.Event()
    release = asyncio.Event()

    async def between_waves(seconds):
        entered.set()
        await release.wait()

    monkeypatch.setattr(
        batches,
        "asyncio",
        SimpleNamespace(sleep=between_waves, create_task=asyncio.create_task, Task=asyncio.Task),
    )
    req = BatchExecutionRequest(
        script_id=world.script.id,
        device_ids=[world.dev_a.id, world.dev_a2.id],
        wave_size=1,
        wave_delay_ms=1000,
        jitter_ms=0,
        stagger_by_workstation=False,
    )
    before = set(_background_tasks)
    async with world.sessions() as db:
        batch = await BatchService(db, world.sessions).start_batch(
            req, world.org_a.id, world.users["org_admin"].id
        )
    await asyncio.wait_for(entered.wait(), 3)
    tasks = list(set(_background_tasks) - before)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    async with world.sessions() as db:
        saved = await db.get(TaskBatch, batch.id)
        admitted = list(await db.scalars(select(Task.device_id).where(Task.batch_id == batch.id)))
        print(
            {
                "requested": saved.total,
                "admitted": len(admitted),
                "batch_status": saved.status,
                "wave_config_keys": sorted(saved.wave_config),
            }
        )
        assert len(admitted) == 1
        # A fresh worker cannot reconstruct the missing target from this record.
        assert str(world.dev_a2.id) in str(
            saved.wave_config
        ), "Remaining target plan was lost with the background coroutine"


async def test_force_stop_does_not_claim_cancelled_when_delivery_failed(world):
    from unittest.mock import AsyncMock

    from backend.models.task import TaskStatus
    from backend.services.task_service import TaskService

    queue = SimpleNamespace(mark_completed=AsyncMock())
    publisher = SimpleNamespace(send_command_live=AsyncMock(return_value=False))
    async with world.sessions() as db:
        task = Task(
            org_id=world.org_a.id,
            script_id=world.script.id,
            script_version_id=world.version.id,
            device_id=world.dev_a.id,
            status=TaskStatus.RUNNING,
        )
        db.add(task)
        await db.commit()
        await TaskService(db, queue=queue, publisher=publisher).force_stop_task(
            task.id, world.org_a.id
        )
        await db.commit()
        print(
            {
                "delivery_accepted": False,
                "persisted_task_status": task.status,
                "device_lock_released": queue.mark_completed.await_count == 1,
            }
        )
        assert (
            task.status != TaskStatus.CANCELLED
        ), "Failed delivery must remain pending/unknown until reconciled"


async def test_pipeline_cancel_reconciles_current_child_task(world):
    from backend.models.task import TaskStatus
    from backend.services.orchestrator.pipeline_service import PipelineService

    _, runs = await make_runs(world, status=PipelineRunStatus.RUNNING)
    async with world.sessions() as db:
        task = Task(
            org_id=world.org_a.id,
            script_id=world.script.id,
            script_version_id=world.version.id,
            device_id=runs[0].device_id,
            status=TaskStatus.RUNNING,
        )
        db.add(task)
        await db.flush()
        run = await db.get(PipelineRun, runs[0].id)
        run.current_task_id = task.id
        await db.commit()
        await PipelineService(db).cancel_run(run.id, world.org_a.id)
        await db.commit()
        await db.refresh(task)
        print(
            {
                "pipeline_status": run.status,
                "child_task_status": task.status,
                "current_task_still_bound": run.current_task_id == task.id,
            }
        )
        assert (
            task.status != TaskStatus.RUNNING
        ), "Pipeline cancellation leaves the child running without a stop intent"


def test_ota_catalog_preserves_concurrent_publications(tmp_path, monkeypatch):
    from backend.api.v1.updates import router as updates

    monkeypatch.setattr(updates, "_UPDATES_PATH", tmp_path / "catalog.json")
    updates._save_releases([])
    first = updates._load_releases()
    second = updates._load_releases()
    first.append({"id": "disposable-a"})
    second.append({"id": "disposable-b"})
    updates._save_releases(first)
    updates._save_releases(second)
    saved = updates._load_releases()
    print({"concurrent_publications": 2, "retained_publications": len(saved)})
    assert len(saved) == 2, "Independent worker read-modify-write loses a committed publication"
