"""Scheduled work is tenant-scoped and each firing commits as one SQL unit."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.database.tenant import bind_tenant_context
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.schedule import Schedule, ScheduleExecution, ScheduleTargetType
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.services.scheduler.scheduler_engine import SchedulerEngine

LOOKUP = "sphere_auth.schedule_work(uuid)"


@pytest_asyncio.fixture
async def scheduler_runtime(runtime_db, monkeypatch):
    r = runtime_db
    ids = set()
    queue = AsyncMock()
    monkeypatch.setattr("backend.services.scheduler.scheduler_engine.AsyncSessionLocal", r.sessions)
    monkeypatch.setattr("backend.services.task_queue.TaskQueue", lambda *_: queue)
    monkeypatch.setattr("backend.database.redis_client.redis_binary", None)
    async with r.world.engine.begin() as db:
        exists = await db.scalar(text("SELECT to_regprocedure(:lookup)"), {"lookup": LOOKUP})
        if exists:
            await db.execute(text(f'GRANT EXECUTE ON FUNCTION {LOOKUP} TO "{r.role}"'))
    # Query the real lookup; effects belong only to this fixture's records.
    if hasattr(SchedulerEngine, "_discover_schedules"):
        original = SchedulerEngine._discover_schedules
        async def discover(engine):
            return [row for row in await original(engine) if row[0] in ids]
        monkeypatch.setattr(SchedulerEngine, "_discover_schedules", discover)
    try:
        yield SimpleNamespace(**locals())
    finally:
        async with r.world.sessions() as db:
            await db.execute(update(Schedule).where(Schedule.id.in_(ids)).values(is_active=False, next_fire_at=None))
            tenants = [r.world.org_a.id, r.world.org_b.id]
            await db.execute(update(Task).where(Task.org_id.in_(tenants)).values(
                status=TaskStatus.COMPLETED, cancel_requested_at=None, cancel_last_sent_at=None,
            ))
            await db.execute(update(PipelineRun).where(PipelineRun.org_id.in_(tenants)).values(
                status=PipelineRunStatus.COMPLETED, cancel_requested_at=None,
            ))
            await db.commit()
        if exists:
            async with r.world.engine.begin() as db:
                await db.execute(text(f'REVOKE EXECUTE ON FUNCTION {LOOKUP} FROM "{r.role}"'))


async def seed(r, *, target="script", **overrides):
    world = r.r.world
    now = datetime.now(timezone.utc)
    async with world.sessions() as db:
        tenant = overrides.get("org_id", world.org_a.id)
        script = world.script
        device = world.dev_a if tenant == world.org_a.id else world.dev_b
        if tenant != script.org_id:
            script = Script(org_id=tenant, name="second-tenant-schedule")
            db.add(script)
            await db.flush()
            version = ScriptVersion(org_id=tenant, script_id=script.id, dag={"nodes": [], "entry_node": "second"})
            db.add(version)
            await db.flush()
            script.current_version_id = version.id
        values = dict(id=uuid.UUID(int=uuid.uuid4().int >> 64), org_id=tenant,
                      name="isolated scheduler runtime", interval_seconds=60,
                      target_type=ScheduleTargetType.SCRIPT, script_id=script.id,
                      device_ids=[str(device.id)], only_online=False,
                      next_fire_at=now - timedelta(minutes=1))
        if target == "pipeline":
            pipeline = Pipeline(org_id=tenant, name="isolated scheduled pipeline", steps=[])
            db.add(pipeline)
            await db.flush()
            values.update(target_type=ScheduleTargetType.PIPELINE, pipeline_id=pipeline.id, script_id=None)
        values.update(overrides)
        schedule = Schedule(**values)
        db.add(schedule)
        await db.commit()
        r.ids.add(schedule.id)
        return schedule


def use_bound_session(r, monkeypatch):
    """Control: expose transaction defects independently of the RLS visibility bug."""
    @asynccontextmanager
    async def sessions():
        async with r.r.sessions() as db:
            await bind_tenant_context(db, str(r.r.world.org_a.id))
            yield db
    monkeypatch.setattr("backend.services.scheduler.scheduler_engine.AsyncSessionLocal", sessions)


async def stored(r, schedule):
    async with r.r.world.sessions() as db:
        row = await db.get(Schedule, schedule.id)
        executions = list(await db.scalars(select(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule.id)))
        return row, executions


async def test_tick_retires_due_exhausted_schedule_under_actual_rls(scheduler_runtime):
    r = scheduler_runtime
    schedule = await seed(r, max_runs=1, total_runs=1)
    await SchedulerEngine()._tick()
    row, executions = await stored(r, schedule)
    assert row.is_active is False and row.next_fire_at is None
    assert not executions


@pytest.mark.parametrize("target", ["script", "pipeline"])
async def test_tick_creates_children_and_execution_under_actual_rls(scheduler_runtime, target):
    r = scheduler_runtime
    schedule = await seed(r, target=target)
    await SchedulerEngine()._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and row.next_fire_at > datetime.now(timezone.utc)
    assert len(executions) == 1 and executions[0].tasks_created == 1
    async with r.r.world.sessions() as db:
        model = Task if target == "script" else PipelineRun
        assert await db.scalar(select(func.count()).select_from(model).where(model.org_id == schedule.org_id)) == 1


async def test_error_after_child_flush_rolls_back_entire_firing(scheduler_runtime, monkeypatch):
    r = scheduler_runtime
    use_bound_session(r, monkeypatch)
    schedule = await seed(r)
    engine = SchedulerEngine()
    original = engine._process_schedule
    async def fail_after_writes(*args, **kwargs):
        await original(*args, **kwargs)
        await args[2].flush()
        raise RuntimeError("isolated failure after child creation")
    monkeypatch.setattr(engine, "_process_schedule", fail_after_writes)
    await engine._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 0 and row.next_fire_at == schedule.next_fire_at
    assert not executions
    async with r.r.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.org_id == schedule.org_id)) == 0
    r.queue.enqueue.assert_not_awaited()


async def test_only_online_defers_when_presence_is_unavailable(scheduler_runtime, monkeypatch):
    r = scheduler_runtime
    use_bound_session(r, monkeypatch)
    schedule = await seed(r, only_online=True)
    await SchedulerEngine()._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 0 and row.next_fire_at == schedule.next_fire_at
    assert not executions


async def test_conflict_skip_advances_past_now_instead_of_refiring_every_poll(scheduler_runtime, monkeypatch):
    r = scheduler_runtime
    use_bound_session(r, monkeypatch)
    schedule = await seed(r, last_fired_at=datetime.now(timezone.utc)-timedelta(minutes=5), total_runs=1)
    async with r.r.world.sessions() as db:
        current = await db.get(Schedule, schedule.id)
        await SchedulerEngine()._process_schedule(current, datetime.now(timezone.utc), db, [])
        await db.commit()
    # The first call above creates the previous active task and advances normally.
    async with r.r.world.sessions() as db:
        current = await db.get(Schedule, schedule.id)
        current.last_fired_at = datetime.now(timezone.utc)-timedelta(minutes=5)
        current.next_fire_at = datetime.now(timezone.utc)-timedelta(minutes=4)
        await db.commit()
    await SchedulerEngine()._tick()
    row, executions = await stored(r, schedule)
    assert len(executions) == 2
    assert row.next_fire_at > datetime.now(timezone.utc)


async def test_skip_advances_interval_without_changing_last_actual_firing(scheduler_runtime, monkeypatch):
    r = scheduler_runtime
    use_bound_session(r, monkeypatch)
    last = datetime.now(timezone.utc)-timedelta(minutes=5)
    schedule = await seed(r, last_fired_at=last, total_runs=1)
    engine = SchedulerEngine()
    monkeypatch.setattr(engine, "_has_running_tasks", AsyncMock(return_value=True))
    await engine._tick()
    row, executions = await stored(r, schedule)
    assert len(executions) == 1 and executions[0].status == "skipped"
    assert row.next_fire_at > datetime.now(timezone.utc)
    assert row.last_fired_at == last and row.total_runs == 1


async def test_two_tenants_share_pool_without_visibility_or_payload_leak(scheduler_runtime):
    r = scheduler_runtime
    schedules = [await seed(r), await seed(r, org_id=r.r.world.org_b.id)]
    await SchedulerEngine()._tick()
    async with r.r.world.sessions() as db:
        for schedule in schedules:
            row, executions = await stored(r, schedule)
            assert row.total_runs == 1 and len(executions) == 1
            tasks = list(await db.scalars(select(Task).where(Task.batch_id == executions[0].batch_id)))
            assert len(tasks) == 1 and tasks[0].org_id == schedule.org_id
            assert tasks[0].script_id == schedule.script_id
            assert str(tasks[0].device_id) == schedule.device_ids[0]
    async with r.r.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Schedule)) == 0
        assert await db.scalar(text("SELECT nullif(current_setting('app.current_org_id',true),'')")) is None


async def test_competing_workers_and_locked_schedule_create_one_firing(scheduler_runtime):
    r = scheduler_runtime
    schedule = await seed(r, interval_seconds=None, one_shot_at=datetime.now(timezone.utc)-timedelta(seconds=1))
    first, second = SchedulerEngine(), SchedulerEngine()
    async with r.r.world.sessions() as lock:
        await lock.scalar(select(Schedule).where(Schedule.id == schedule.id).with_for_update())
        await asyncio.wait_for(asyncio.gather(first._tick(), second._tick()), 3)
        assert not (await stored(r, schedule))[1]
        await lock.rollback()
    await asyncio.gather(first._tick(), second._tick())
    row, executions = await stored(r, schedule)
    assert not row.is_active and row.total_runs == 1 and row.next_fire_at is None
    assert len(executions) == 1


async def test_sql_error_in_one_schedule_rolls_back_it_without_poisoning_other(scheduler_runtime, monkeypatch):
    r = scheduler_runtime
    bad, good = await seed(r), await seed(r)
    engine = SchedulerEngine()
    original = engine._process_schedule
    async def faulty(schedule, now, db, pending):
        await original(schedule, now, db, pending)
        if schedule.id == bad.id:
            await db.flush()
            await db.execute(text("SELECT 1 / 0"))
    monkeypatch.setattr(engine, "_process_schedule", faulty)
    await engine._tick()
    bad_row, bad_exec = await stored(r, bad)
    good_row, good_exec = await stored(r, good)
    assert bad_row.total_runs == 0 and not bad_exec
    assert good_row.total_runs == 1 and len(good_exec) == 1
    async with r.r.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.org_id == bad.org_id)) == 1


@pytest.mark.parametrize("after_commit", [False, True])
async def test_commit_failure_reconciles_persisted_firing_without_duplicate(scheduler_runtime, monkeypatch, after_commit):
    r = scheduler_runtime
    schedule = await seed(r)
    failed = False
    class FailCommit(AsyncSession):
        async def commit(self):
            nonlocal failed
            if not failed:
                failed = True
                if after_commit:
                    await super().commit()
                raise ConnectionError("isolated commit response failure")
            await super().commit()
    monkeypatch.setattr("backend.services.scheduler.scheduler_engine.AsyncSessionLocal", async_sessionmaker(
        r.r.engine, class_=FailCommit, expire_on_commit=False,
    ))
    await SchedulerEngine()._tick()
    row, executions = await stored(r, schedule)
    assert len(executions) == int(after_commit) and row.total_runs == int(after_commit)
    await SchedulerEngine()._tick()
    await SchedulerEngine()._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and len(executions) == 1
    async with r.r.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.org_id == schedule.org_id)) == 1
    r.queue.enqueue.assert_not_awaited()


async def test_grant_failure_then_recovery_uses_same_worker(scheduler_runtime):
    r = scheduler_runtime
    schedule = await seed(r)
    engine = SchedulerEngine()
    async with r.r.world.engine.begin() as db:
        await db.execute(text(f'REVOKE EXECUTE ON FUNCTION {LOOKUP} FROM "{r.r.role}"'))
    try:
        with pytest.raises(DBAPIError):
            await engine._tick()
    finally:
        async with r.r.world.engine.begin() as db:
            await db.execute(text(f'GRANT EXECUTE ON FUNCTION {LOOKUP} TO "{r.r.role}"'))
    await engine._tick()
    assert len((await stored(r, schedule))[1]) == 1


async def test_fifty_deferred_schedules_do_not_hide_next_due_schedule(scheduler_runtime):
    r = scheduler_runtime
    base = uuid.uuid4().int >> 80
    for offset in range(50):
        await seed(r, id=uuid.UUID(int=base+offset), active_from=datetime.now(timezone.utc)+timedelta(days=1))
    final = await seed(r, id=uuid.UUID(int=base+50))
    engine = SchedulerEngine()
    await engine._tick()
    assert not (await stored(r, final))[1]
    await engine._tick()
    assert len((await stored(r, final))[1]) == 1


@pytest.mark.parametrize("failure", ["connection", "timeout"])
async def test_presence_failure_defers_then_bulk_presence_recovers(scheduler_runtime, monkeypatch, failure):
    r = scheduler_runtime
    schedule = await seed(r, only_online=True, device_ids=[str(r.r.world.dev_a.id), str(r.r.world.dev_a2.id)])
    cache = AsyncMock()
    async def unavailable(*_):
        if failure == "connection":
            raise ConnectionError("isolated presence outage")
        await asyncio.Event().wait()
    cache.bulk_get_status.side_effect = unavailable
    monkeypatch.setattr("backend.database.redis_client.redis_binary", object())
    monkeypatch.setattr("backend.services.device_status_cache.DeviceStatusCache", lambda _: cache)
    engine = SchedulerEngine()
    await asyncio.wait_for(engine._tick(), 4)
    assert not (await stored(r, schedule))[1]
    cache.bulk_get_status.side_effect = None
    cache.bulk_get_status.return_value = {str(r.r.world.dev_a.id): SimpleNamespace(status="online"),
                                        str(r.r.world.dev_a2.id): SimpleNamespace(status="offline")}
    await engine._tick()
    _, executions = await stored(r, schedule)
    assert len(executions) == 1 and executions[0].tasks_created == 1
    assert cache.bulk_get_status.await_count == 2
    cache.get_status.assert_not_awaited()
    r.queue.enqueue.assert_not_awaited()


@pytest.mark.parametrize("stage", ["discovery", "firing"])
async def test_real_sql_timeout_recovers_worker_and_pool(scheduler_runtime, monkeypatch, stage):
    r = scheduler_runtime
    schedule = await seed(r)
    engine = SchedulerEngine()
    stalled = False
    if stage == "discovery":
        class SlowDiscovery(AsyncSession):
            async def execute(self, statement, *args, **kwargs):
                nonlocal stalled
                if "sphere_auth.schedule_work" in str(statement) and not stalled:
                    stalled = True
                    await super().execute(text("SELECT pg_sleep(5)"))
                return await super().execute(statement, *args, **kwargs)
        monkeypatch.setattr("backend.services.scheduler.scheduler_engine.AsyncSessionLocal", async_sessionmaker(
            r.r.engine, class_=SlowDiscovery, expire_on_commit=False,
        ))
        monkeypatch.setattr("backend.services.scheduler.scheduler_engine._DISCOVERY_TIMEOUT_SECONDS", 0.2)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(engine._tick(), 2)
        monkeypatch.setattr("backend.services.scheduler.scheduler_engine._DISCOVERY_TIMEOUT_SECONDS", 5)
    else:
        original = engine._process_schedule
        async def slow(schedule, now, db, pending):
            nonlocal stalled
            await original(schedule, now, db, pending)
            if not stalled:
                stalled = True
                await db.flush()
                await db.execute(text("SELECT pg_sleep(5)"))
        monkeypatch.setattr(engine, "_process_schedule", slow)
        monkeypatch.setattr("backend.services.scheduler.scheduler_engine._FIRING_TIMEOUT_SECONDS", 0.2)
        await asyncio.wait_for(engine._tick(), 2)
        monkeypatch.setattr("backend.services.scheduler.scheduler_engine._FIRING_TIMEOUT_SECONDS", 15)
    assert not (await stored(r, schedule))[1]
    await engine._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and len(executions) == 1


async def test_presence_failure_rolls_back_cancel_previous_intent(scheduler_runtime, monkeypatch):
    r = scheduler_runtime
    schedule = await seed(r)
    engine = SchedulerEngine()
    await engine._tick()
    async with r.r.world.sessions() as db:
        task = await db.scalar(select(Task).where(Task.org_id == schedule.org_id))
        task.status = TaskStatus.RUNNING
        current = await db.get(Schedule, schedule.id)
        current.only_online = True
        current.conflict_policy = "cancel"
        current.next_fire_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        await db.commit()
        task_id = task.id
    await engine._tick()
    async with r.r.world.sessions() as db:
        task = await db.get(Task, task_id)
        assert task.status == TaskStatus.RUNNING and task.cancel_requested_at is None
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and len(executions) == 1


async def test_committed_scheduler_task_delivers_without_redis_enqueue(scheduler_runtime):
    from backend.services.task_service import TaskService

    r = scheduler_runtime
    schedule = await seed(r)
    await SchedulerEngine()._tick()
    cache, publisher = AsyncMock(), AsyncMock()
    cache.bulk_get_status.return_value = {str(r.r.world.dev_a.id): SimpleNamespace(status="online")}
    publisher.send_command_live.return_value = True
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(schedule.org_id))
        await TaskService(db, status_cache=cache, publisher=publisher).dispatch_pending_tasks(org_id=schedule.org_id)
    publisher.send_command_live.assert_awaited_once()
    command = publisher.send_command_live.call_args.args[1]
    async with r.r.world.sessions() as db:
        task = await db.get(Task, uuid.UUID(command["command_id"]))
        assert task.org_id == schedule.org_id and task.status == TaskStatus.ASSIGNED
        assert task.input_params["_schedule_id"] == str(schedule.id)
    r.queue.enqueue.assert_not_awaited()


async def test_terminated_sql_connection_rolls_back_children_and_recovers(scheduler_runtime, monkeypatch):
    r = scheduler_runtime
    schedule = await seed(r)
    engine = SchedulerEngine()
    original = engine._process_schedule
    killed = False
    async def disconnect(schedule, now, db, pending):
        nonlocal killed
        await original(schedule, now, db, pending)
        if not killed:
            await db.flush()
            assert await db.scalar(text("SELECT current_user")) == r.r.role
            backend_pid = await db.scalar(text("SELECT pg_backend_pid()"))
            async with r.r.world.engine.begin() as control:
                assert await control.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": backend_pid})
            killed = True
    monkeypatch.setattr(engine, "_process_schedule", disconnect)
    await engine._tick()
    assert killed and not (await stored(r, schedule))[1]
    await engine._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and len(executions) == 1
    async with r.r.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.org_id == schedule.org_id)) == 1
