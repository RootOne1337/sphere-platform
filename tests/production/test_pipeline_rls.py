"""Actual non-owner PostgreSQL role; no device commands or shared pilot writes."""

import asyncio
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.task import Task, TaskStatus
from backend.services.orchestrator.pipeline_executor import PipelineExecutor
from backend.services.orchestrator.pipeline_ownership import Ownership
from backend.services.orchestrator.pipeline_recovery import renew_lease
from backend.services.orchestrator.pipeline_tenants import discover_work, tenant_sessions
from tests.production.test_pipeline_admission import cleanup, held_executor, seed_runs, wait_until
from tests.production.test_pipeline_recovery import seed


@pytest_asyncio.fixture
async def pipeline_worker_role(runtime_db, monkeypatch):
    r = runtime_db
    async with r.world.sessions() as db:
        await db.execute(text(f'GRANT EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) TO "{r.role}"'))
        await db.commit()
    from backend.services.orchestrator.pipeline_tenants import discover_work

    async def isolated_discovery(*args, **kwargs):
        # Execute real global discovery, then prevent changes to other fixtures.
        rows = await discover_work(*args, **kwargs)
        return [row for row in rows if row[1] in {r.world.org_a.id, r.world.org_b.id}]

    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.discover_work", isolated_discovery)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_recovery.discover_work", isolated_discovery)
    try:
        yield r
    finally:
        async with r.world.sessions() as db:
            await db.execute(text(f'REVOKE EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) FROM "{r.role}"'))
            await db.commit()


async def test_unscoped_runtime_worker_does_not_leave_queue_invisible(pipeline_worker_role, monkeypatch):
    r = pipeline_worker_role
    run = await seed(r.world, status=PipelineRunStatus.QUEUED)
    async with r.world.sessions() as db:
        (await db.get(PipelineRun, run.id)).created_at = datetime(1900, 1, 1, tzinfo=timezone.utc)
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch()
        assert executor._tasks, "Actual RLS worker cannot see persisted queued intent"
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 5)
        async with r.world.sessions() as db:
            assert (await db.get(PipelineRun, run.id)).status == PipelineRunStatus.COMPLETED
    finally:
        await cleanup(executor)


async def test_cancel_reconciliation_uses_runtime_tenant_context(runtime_db, monkeypatch):
    r = runtime_db
    run = await seed(r.world, status=PipelineRunStatus.QUEUED)
    async with r.world.sessions() as db:
        (await db.get(PipelineRun, run.id)).cancel_requested_at = datetime.now(timezone.utc)
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    await PipelineExecutor()._reconcile_cancellations(org_id=r.world.org_a.id)
    async with r.world.sessions() as db:
        assert (await db.get(PipelineRun, run.id)).status == PipelineRunStatus.CANCELLED


async def test_runtime_renewal_keeps_owned_lease_visible(runtime_db):
    r = runtime_db
    run = await seed(r.world)
    owner = uuid.uuid4()
    async with r.world.sessions() as db:
        row = await db.get(PipelineRun, run.id)
        row.execution_owner = owner
        row.execution_generation = 1
        row.execution_lease_until = datetime.now(timezone.utc) + timedelta(seconds=20)
        await db.commit()
    ownership = Ownership(run.id, owner, 1, org_id=r.world.org_a.id)
    assert await renew_lease(r.sessions, ownership)


async def prioritize(world, *run_ids):
    async with world.sessions() as db:
        for run_id in run_ids:
            row = await db.get(PipelineRun, run_id)
            row.created_at = row.updated_at = datetime(1890, 1, 1, tzinfo=timezone.utc)
        await db.commit()


async def foreign_run(world, **overrides):
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_b.id, name="other-tenant-fixture")
        db.add(pipeline)
        await db.flush()
        run = PipelineRun(org_id=world.org_b.id, pipeline_id=pipeline.id, device_id=world.dev_b.id,
                          steps_snapshot=[], **overrides)
        db.add(run)
        await db.commit()
    return run


async def test_two_tenants_run_and_release_owner_without_pool_context_leak(pipeline_worker_role, monkeypatch):
    r = pipeline_worker_role
    first = await seed(r.world, status=PipelineRunStatus.QUEUED)
    second = await foreign_run(r.world, status=PipelineRunStatus.QUEUED)
    await prioritize(r.world, first.id, second.id)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch()
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 5)
        async with r.world.sessions() as db:
            for run_id in (first.id, second.id):
                row = await db.get(PipelineRun, run_id)
                assert row.status == PipelineRunStatus.COMPLETED
                assert row.execution_owner is None and row.execution_lease_until is None
        async with r.sessions() as db:
            assert await db.get(PipelineRun, first.id) is None
            assert await db.get(PipelineRun, second.id) is None
            assert not await db.scalar(text("SELECT current_setting('app.current_org_id', true)"))
        async with tenant_sessions(r.sessions, r.world.org_a.id)() as db:
            assert await db.get(PipelineRun, second.id) is None
            await db.commit()
            assert await db.get(PipelineRun, first.id) is not None
            await db.rollback()
            assert await db.get(PipelineRun, second.id) is None
    finally:
        await cleanup(executor)


async def test_expired_owner_recovery_uses_same_task_under_runtime_role(pipeline_worker_role, monkeypatch):
    r = pipeline_worker_role
    run = await seed(r.world, kind="execute_script", params={"script_id": str(r.world.script.id)})
    async with r.world.sessions() as db:
        task = Task(org_id=r.world.org_a.id, device_id=r.world.dev_a.id, script_id=r.world.script.id,
                    script_version_id=r.world.version.id, status=TaskStatus.COMPLETED, result={"receipt": "fixture"})
        db.add(task)
        await db.flush()
        row = await db.get(PipelineRun, run.id)
        row.current_task_id, row.current_step_id = task.id, "first"
        row.execution_phase = "in_flight"
        row.step_started_at = datetime.now(timezone.utc)
        row.execution_owner, row.execution_generation = uuid.uuid4(), 3
        row.execution_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    await prioritize(r.world, run.id)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch()
        assert executor._tasks
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 5)
        async with r.world.sessions() as db:
            row = await db.get(PipelineRun, run.id)
            assert row.status == PipelineRunStatus.COMPLETED
            assert row.execution_generation > 3
            assert list(await db.scalars(select(Task.id).where(Task.org_id == r.world.org_a.id))) == [task.id]
    finally:
        await cleanup(executor)


async def test_heartbeat_and_child_admission_rebind_runtime_context_after_commits(pipeline_worker_role, monkeypatch):
    r = pipeline_worker_role
    run = await seed(r.world, kind="execute_script", params={"script_id": str(r.world.script.id)}, status=PipelineRunStatus.QUEUED)
    await prioritize(r.world, run.id)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_recovery.HEARTBEAT_SECONDS", 0.02)
    renewals = []

    async def record_renew(sessions, ownership):
        result = await renew_lease(sessions, ownership)
        renewals.append(result)
        return result

    monkeypatch.setattr("backend.services.orchestrator.pipeline_recovery.renew_lease", record_renew)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch()
        await wait_until(lambda: len(renewals) >= 2)
        async with r.world.sessions() as db:
            row = await db.get(PipelineRun, run.id)
            child_id = row.current_task_id
            assert child_id is not None
            (await db.get(Task, child_id)).status = TaskStatus.COMPLETED
            await db.commit()
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 5)
        assert all(renewals)
        async with r.world.sessions() as db:
            row = await db.get(PipelineRun, run.id)
            assert row.status == PipelineRunStatus.COMPLETED and row.execution_owner is None
    finally:
        await cleanup(executor)


async def test_nested_cancellation_does_not_touch_other_tenants_parent_reference(pipeline_worker_role, monkeypatch):
    r = pipeline_worker_role
    parent = await seed(r.world)
    child = await seed(r.world, status=PipelineRunStatus.QUEUED)
    foreign = await foreign_run(r.world, status=PipelineRunStatus.QUEUED, context={"parent_run_id": str(parent.id)})
    async with r.world.sessions() as db:
        row = await db.get(PipelineRun, parent.id)
        row.cancel_requested_at = datetime.now(timezone.utc)
        row.current_child_run_id = child.id
        (await db.get(PipelineRun, child.id)).context = {"parent_run_id": str(parent.id)}
        await db.commit()
    await prioritize(r.world, parent.id)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    await PipelineExecutor()._reconcile_cancellations()
    async with r.world.sessions() as db:
        assert (await db.get(PipelineRun, parent.id)).status == PipelineRunStatus.CANCELLED
        assert (await db.get(PipelineRun, child.id)).status == PipelineRunStatus.CANCELLED
        assert (await db.get(PipelineRun, foreign.id)).status == PipelineRunStatus.QUEUED


async def test_discovery_requires_explicit_grant_and_returns_only_bounded_ids(runtime_db):
    r = runtime_db
    async with r.sessions() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("SELECT * FROM sphere_auth.pipeline_work('queued')"))
    async with r.world.sessions() as db:
        await db.execute(text(f'GRANT EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) TO "{r.role}"'))
        await db.commit()
    try:
        for kind in ("queued", "recovery", "cancel"):
            rows = await discover_work(r.sessions, kind)
            assert len(rows) <= 64
            assert all(len(row) == 2 and all(isinstance(value, uuid.UUID) for value in row) for row in rows)
        async with r.sessions() as db:
            assert list(await db.execute(text("SELECT * FROM sphere_auth.pipeline_work('invalid')"))) == []
            assert list(await db.execute(text("SELECT * FROM sphere_auth.pipeline_work(NULL)"))) == []
        with pytest.raises(ValueError):
            await discover_work(r.sessions, "arbitrary")
    finally:
        async with r.world.sessions() as db:
            await db.execute(text(f'REVOKE EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) FROM "{r.role}"'))
            await db.commit()


async def test_scoped_execution_cannot_adopt_another_tenant_even_with_owner_generation(runtime_db, monkeypatch):
    r = runtime_db
    run = await seed(r.world)
    executor = PipelineExecutor()
    async with r.world.sessions() as db:
        row = await db.get(PipelineRun, run.id)
        row.execution_owner, row.execution_generation = executor._owner, 1
        row.execution_lease_until = datetime.now(timezone.utc) + timedelta(seconds=30)
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    await executor._execute_run_safe(run.id, 1, r.world.org_b.id)
    assert not await renew_lease(r.sessions, Ownership(run.id, executor._owner, 1, org_id=r.world.org_b.id))
    async with r.world.sessions() as db:
        row = await db.get(PipelineRun, run.id)
        assert row.status == PipelineRunStatus.RUNNING and row.step_logs == []


async def test_two_runtime_workers_keep_bounded_disjoint_claims(runtime_db, monkeypatch):
    r = runtime_db
    await seed_runs(r.world, 32)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    workers = [held_executor(monkeypatch) for _ in range(2)]
    try:
        await asyncio.gather(*(worker._poll_and_dispatch(org_id=r.world.org_a.id) for worker, _, _ in workers))
        await wait_until(lambda: all(len(entered) == 10 for _, entered, _ in workers))
        assert len(set.union(*(entered for _, entered, _ in workers))) == 20
        async with r.world.sessions() as db:
            queued = list(await db.scalars(select(PipelineRun.id).where(
                PipelineRun.org_id == r.world.org_a.id, PipelineRun.status == PipelineRunStatus.QUEUED,
            )))
            assert len(queued) == 12
    finally:
        await cleanup(*(worker for worker, _, _ in workers))


async def test_committed_tenant_group_starts_even_when_next_group_commit_fails(pipeline_worker_role, monkeypatch):
    r = pipeline_worker_role
    first = await seed(r.world, status=PipelineRunStatus.QUEUED)
    second = await foreign_run(r.world, status=PipelineRunStatus.QUEUED)
    await prioritize(r.world, first.id, second.id)
    async with r.world.sessions() as db:
        (await db.get(PipelineRun, first.id)).created_at = datetime(1880, 1, 1, tzinfo=timezone.utc)
        await db.commit()

    @asynccontextmanager
    async def sessions():
        async with r.sessions() as db:
            commit = db.commit
            async def reject_second():
                if db.sync_session.info.get("sphere.tenant_id") == str(r.world.org_b.id):
                    raise ConnectionError("isolated second tenant commit failure")
                await commit()
            db.commit = reject_second
            yield db

    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", sessions)
    executor, entered, _ = held_executor(monkeypatch)
    try:
        with pytest.raises(ConnectionError):
            await executor._poll_and_dispatch()
        await wait_until(lambda: len(entered) == 1)
        assert entered == {first.id}
        async with r.world.sessions() as db:
            assert (await db.get(PipelineRun, second.id)).status == PipelineRunStatus.QUEUED
    finally:
        await cleanup(executor)


async def test_real_runtime_process_death_recovers_same_child_with_tenant_context(runtime_db, tmp_path):
    r = runtime_db
    run = await seed(r.world, kind="execute_script", params={"script_id": str(r.world.script.id)},
                     status=PipelineRunStatus.QUEUED)
    async with r.world.sessions() as db:
        row = await db.get(PipelineRun, run.id)
        row.steps_snapshot = [{**row.steps_snapshot[0], "timeout_ms": 60000}]
        await db.commit()
    processes = []

    async def inspect_until(predicate):
        async def inspect():
            while True:
                async with r.world.sessions() as db:
                    stored = await db.get(PipelineRun, run.id)
                    if predicate(stored):
                        return stored
                await asyncio.sleep(0.025)
        return await asyncio.wait_for(inspect(), 15)

    with (tmp_path / "runtime-pipeline-worker.log").open("w", encoding="utf-8") as log:
        def launch():
            env = {**os.environ, "POSTGRES_URL": r.engine.url.render_as_string(hide_password=False)}
            process = subprocess.Popen(
                [sys.executable, "-m", "tests.production.pipeline_worker_probe", str(r.world.org_a.id)],
                env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            processes.append(process)
            return process

        try:
            first = launch()
            admitted = await inspect_until(lambda row: row.current_task_id is not None)
            first.kill()
            await asyncio.to_thread(first.wait, 5)
            async with r.world.sessions() as db:
                (await db.get(Task, admitted.current_task_id)).status = TaskStatus.COMPLETED
                (await db.get(PipelineRun, run.id)).execution_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
                await db.commit()
            second = launch()
            recovered = await inspect_until(lambda row: row.status == PipelineRunStatus.COMPLETED)
            assert second.pid != first.pid and recovered.execution_generation > admitted.execution_generation
            async with r.world.sessions() as db:
                assert list(await db.scalars(select(Task.id).where(Task.org_id == r.world.org_a.id))) == [admitted.current_task_id]
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, 5)


async def test_discovery_failure_recovers_next_poll_after_grant(runtime_db, monkeypatch):
    r = runtime_db
    run = await seed(r.world, status=PipelineRunStatus.QUEUED)
    await prioritize(r.world, run.id)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        with pytest.raises(DBAPIError):
            await executor._poll_and_dispatch()
        assert not executor._tasks
        # Restore access; recovery must happen with the existing executor.
        async with r.world.sessions() as db:
            await db.execute(text(f'GRANT EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) TO "{r.role}"'))
            await db.commit()
        async def isolated(sessions, kind, **kwargs):
            return [row for row in await discover_work(sessions, kind, **kwargs) if row[1] == r.world.org_a.id]
        monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.discover_work", isolated)
        monkeypatch.setattr("backend.services.orchestrator.pipeline_recovery.discover_work", isolated)
        await executor._poll_and_dispatch()
        await asyncio.wait_for(asyncio.gather(*executor._tasks), 5)
        async with r.world.sessions() as db:
            assert (await db.get(PipelineRun, run.id)).status == PipelineRunStatus.COMPLETED
    finally:
        await cleanup(executor)
        async with r.world.sessions() as db:
            await db.execute(text(f'REVOKE EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) FROM "{r.role}"'))
            await db.commit()
