"""Real PostgreSQL admission tests; no device commands or pilot services."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.models.device import Device
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.services.orchestrator.pipeline_executor import PipelineExecutor


async def seed_runs(world, count):
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name="bounded-admission-fixture")
        db.add(pipeline)
        devices = [Device(org_id=world.org_a.id, name=f"admission-{i}") for i in range(count)]
        db.add_all(devices)
        await db.flush()
        runs = [PipelineRun(
            org_id=world.org_a.id, pipeline_id=pipeline.id, device_id=device.id,
            status=PipelineRunStatus.QUEUED, steps_snapshot=[],
        ) for device in devices]
        db.add_all(runs)
        await db.commit()
    return runs


def isolated_sessions(world, *, before_claim=None, before_commit=None, after_commit=None):
    """Scope worker queries to this disposable tenant, retaining real SQL locks."""
    @asynccontextmanager
    async def factory():
        async with world.sessions() as db:
            execute, commit = db.execute, db.commit
            claiming = False

            async def scoped(statement, *args, **kwargs):
                nonlocal claiming
                if any(d.get("entity") is PipelineRun
                       for d in getattr(statement, "column_descriptions", [])):
                    statement = statement.where(PipelineRun.org_id == world.org_a.id)
                    claiming = (statement._for_update_arg is not None
                                and PipelineRunStatus.QUEUED in statement.compile().params.values())
                    if before_claim and claiming:
                        await before_claim()
                return await execute(statement, *args, **kwargs)

            async def checked_commit():
                if before_commit and claiming:
                    await before_commit()
                await commit()
                if after_commit and claiming:
                    await after_commit()

            db.execute, db.commit = scoped, checked_commit
            yield db
    return factory


async def counts(world):
    async with world.sessions() as db:
        return dict((await db.execute(
            select(PipelineRun.status, func.count()).where(PipelineRun.org_id == world.org_a.id)
            .group_by(PipelineRun.status)
        )).all())


def held_executor(monkeypatch):
    executor = PipelineExecutor()
    entered = set()
    releases = {}

    async def hold(run_id):
        entered.add(run_id)
        releases[run_id] = asyncio.Event()
        await releases[run_id].wait()

    monkeypatch.setattr(executor, "_execute_run", hold)
    return executor, entered, releases


async def wait_until(predicate):
    async def check():
        while not predicate():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(check(), 5)


async def cleanup(*executors):
    tasks = [task for executor in executors for task in executor._tasks]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("total", [32, 1000])
async def test_repeated_polls_leave_excess_work_durable_and_queued(world, monkeypatch, total):
    await seed_runs(world, total)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    executor, entered, _ = held_executor(monkeypatch)
    try:
        for _ in range(5):
            await executor._poll_and_dispatch()
        await wait_until(lambda: len(entered) == 10)
        assert await counts(world) == {PipelineRunStatus.RUNNING: 10, PipelineRunStatus.QUEUED: total - 10}
        assert len(executor._tasks) == 10
    finally:
        await cleanup(executor)


async def test_concurrent_polls_share_one_capacity_reservation(world, monkeypatch):
    await seed_runs(world, 32)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    executor, entered, _ = held_executor(monkeypatch)
    try:
        await asyncio.gather(*(executor._poll_and_dispatch() for _ in range(4)))
        await wait_until(lambda: len(entered) == 10)
        assert await counts(world) == {PipelineRunStatus.RUNNING: 10, PipelineRunStatus.QUEUED: 22}
        assert len(executor._tasks) == 10
    finally:
        await cleanup(executor)


async def test_four_workers_claim_disjoint_bounded_sets(world, monkeypatch):
    await seed_runs(world, 100)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    workers = [held_executor(monkeypatch) for _ in range(4)]
    executors = [worker[0] for worker in workers]
    try:
        for _ in range(3):
            await asyncio.gather(*(executor._poll_and_dispatch() for executor in executors))
        await wait_until(lambda: all(len(entered) == 10 for _, entered, _ in workers))
        all_ids = [run_id for _, entered, _ in workers for run_id in entered]
        assert len(set(all_ids)) == 40
        assert await counts(world) == {PipelineRunStatus.RUNNING: 40, PipelineRunStatus.QUEUED: 60}
        assert all(len(executor._tasks) == 10 for executor in executors)
    finally:
        await cleanup(*executors)


async def test_only_released_slots_admit_new_runs(world, monkeypatch):
    await seed_runs(world, 32)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    executor = PipelineExecutor()
    releases = {}

    async def finish_after_release(run_id):
        releases[run_id] = asyncio.Event()
        await releases[run_id].wait()
        async with world.sessions() as db:
            run = await db.get(PipelineRun, run_id)
            run.status = PipelineRunStatus.COMPLETED
            await db.commit()

    monkeypatch.setattr(executor, "_execute_run", finish_after_release)
    try:
        await executor._poll_and_dispatch()
        await wait_until(lambda: len(releases) == 10)
        for release in list(releases.values())[:3]:
            release.set()
        await wait_until(lambda: len(executor._tasks) == 7)
        await executor._poll_and_dispatch()
        await wait_until(lambda: len(releases) == 13)
        assert await counts(world) == {
            PipelineRunStatus.RUNNING: 10, PipelineRunStatus.QUEUED: 19, PipelineRunStatus.COMPLETED: 3,
        }
        assert len(executor._tasks) == 10
    finally:
        await cleanup(executor)


async def test_failed_claim_commit_starts_no_work_and_does_not_leak_slots(world, monkeypatch):
    await seed_runs(world, 12)
    fail = True

    async def reject_commit():
        if fail:
            raise ConnectionError("isolated failure before commit")

    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal",
                        isolated_sessions(world, before_commit=reject_commit))
    executor, entered, _ = held_executor(monkeypatch)
    try:
        with pytest.raises(ConnectionError):
            await executor._poll_and_dispatch()
        assert not entered and not executor._tasks
        assert await counts(world) == {PipelineRunStatus.QUEUED: 12}
        fail = False
        await executor._poll_and_dispatch()
        await wait_until(lambda: len(entered) == 10)
        assert await counts(world) == {PipelineRunStatus.RUNNING: 10, PipelineRunStatus.QUEUED: 2}
    finally:
        await cleanup(executor)


async def test_full_executor_still_reconciles_cancellation(world, monkeypatch):
    await seed_runs(world, 12)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    executor, _, _ = held_executor(monkeypatch)
    try:
        await executor._poll_and_dispatch()
        reconcile = AsyncMock()
        monkeypatch.setattr(executor, "_reconcile_cancellations", reconcile)
        await executor._poll_and_dispatch()
        reconcile.assert_awaited_once()
        assert await counts(world) == {PipelineRunStatus.RUNNING: 10, PipelineRunStatus.QUEUED: 2}
    finally:
        await cleanup(executor)


async def test_stopped_executor_does_not_claim_any_runs(world, monkeypatch):
    await seed_runs(world, 2)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", isolated_sessions(world))
    executor, entered, _ = held_executor(monkeypatch)
    try:
        await executor.stop()
        await executor._poll_and_dispatch()
        assert not executor._tasks and not entered
        assert await counts(world) == {PipelineRunStatus.QUEUED: 2}
    finally:
        await cleanup(executor)


async def test_stop_during_claim_rolls_back_uncommitted_admission(world, monkeypatch):
    await seed_runs(world, 2)
    selecting, release = asyncio.Event(), asyncio.Event()

    async def blocked_select():
        selecting.set()
        await release.wait()

    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal",
                        isolated_sessions(world, before_claim=blocked_select))
    executor, entered, _ = held_executor(monkeypatch)
    poll = asyncio.create_task(executor._poll_and_dispatch())
    stop = None
    try:
        await asyncio.wait_for(selecting.wait(), 5)
        stop = asyncio.create_task(executor.stop())
        await asyncio.sleep(0)  # Let stop set its admission fence before SELECT returns.
        release.set()
        await asyncio.wait_for(asyncio.gather(poll, stop), 5)
        assert not executor._tasks and not entered
        assert await counts(world) == {PipelineRunStatus.QUEUED: 2}
    finally:
        release.set()
        for task in [poll, stop]:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in [poll, stop] if task is not None), return_exceptions=True)
        await cleanup(executor)


async def test_stop_waits_for_work_already_committed_by_inflight_poll(world, monkeypatch):
    await seed_runs(world, 2)
    committed, return_commit, entered, finish = (asyncio.Event() for _ in range(4))

    async def blocked_commit_response():
        committed.set()
        await return_commit.wait()

    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal",
                        isolated_sessions(world, after_commit=blocked_commit_response))
    executor = PipelineExecutor()

    async def execute(run_id):
        entered.set()
        await finish.wait()

    monkeypatch.setattr(executor, "_execute_run", execute)
    poll = asyncio.create_task(executor._poll_and_dispatch())
    stop = None
    try:
        await asyncio.wait_for(committed.wait(), 5)
        stop = asyncio.create_task(executor.stop())
        await asyncio.sleep(0)
        return_commit.set()
        await asyncio.wait_for(entered.wait(), 5)
        assert not stop.done(), "Shutdown must observe tasks committed by the in-flight claim"
        finish.set()
        await asyncio.wait_for(asyncio.gather(poll, stop), 5)
        assert not executor._tasks
    finally:
        return_commit.set()
        finish.set()
        for task in [poll, stop]:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in [poll, stop] if task is not None), return_exceptions=True)
        await cleanup(executor)
