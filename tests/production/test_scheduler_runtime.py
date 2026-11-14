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

from backend.database.engine import get_db
from backend.database.tenant import bind_tenant_context
from backend.main import app
from backend.models.device import Device
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.schedule import (
    Schedule,
    ScheduleExecution,
    ScheduleFireRequest,
    ScheduleTargetType,
)
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
                      next_fire_at=now - timedelta(seconds=5))
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
    assert len(executions) == 1 and executions[0].status == "skipped"
    assert executions[0].fire_time == schedule.next_fire_at
    assert executions[0].skip_reason == "Лимит запусков расписания исчерпан"


@pytest.mark.parametrize("target", ["script", "pipeline"])
async def test_tick_creates_children_and_execution_under_actual_rls(scheduler_runtime, target):
    r = scheduler_runtime
    schedule = await seed(r, target=target, next_fire_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    await SchedulerEngine()._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and row.next_fire_at > datetime.now(timezone.utc)
    assert row.updated_at > schedule.updated_at
    assert len(executions) == 1 and executions[0].tasks_created == 1
    assert executions[0].fire_time == schedule.next_fire_at < executions[0].actual_time
    async with r.r.world.sessions() as db:
        model = Task if target == "script" else PipelineRun
        assert await db.scalar(select(func.count()).select_from(model).where(model.org_id == schedule.org_id)) == 1


@pytest.mark.parametrize("mode", ["interval", "cron"])
async def test_backlog_creates_at_most_one_launch_and_one_coalesced_receipt_under_rls(scheduler_runtime, mode):
    r = scheduler_runtime
    oldest = (datetime.now(timezone.utc) - timedelta(hours=4)).replace(second=0, microsecond=0)
    timing = {"interval_seconds": 60} if mode == "interval" else {"interval_seconds": None, "cron_expression": "* * * * *"}
    schedule = await seed(r, next_fire_at=oldest, **timing)
    first, second = SchedulerEngine(), SchedulerEngine()
    await asyncio.gather(first._tick(), second._tick())
    row, executions = await stored(r, schedule)
    launched, missed = sorted(executions, key=lambda execution: execution.fire_time)
    assert launched.fire_time == oldest and launched.status == "triggered" and launched.tasks_created == 1
    assert missed.fire_time == oldest + timedelta(minutes=1)
    assert missed.status == "skipped" and missed.tasks_created == 0 and missed.finished_at is not None
    assert missed.skip_reason == "Просроченные слоты объединены, повторный запуск не создан"
    assert row.total_runs == 1 and row.next_fire_at > missed.actual_time


@pytest.mark.parametrize("edge", ["before", "recovered_after_start", "expired", "impossible_one_shot"])
async def test_out_of_window_due_slot_has_history_and_no_work_under_rls(scheduler_runtime, edge):
    r = scheduler_runtime
    now = datetime.now(timezone.utc)
    due = now - timedelta(seconds=5)
    if edge == "expired":
        window = {"active_until": now - timedelta(seconds=1)}
    elif edge == "recovered_after_start":
        window = {"active_from": now - timedelta(seconds=1)}
    else:
        window = {"active_from": now + timedelta(hours=1)}
        if edge == "impossible_one_shot":
            window.update(interval_seconds=None, one_shot_at=due)
    schedule = await seed(r, next_fire_at=due, **window)
    engine = SchedulerEngine()
    await engine._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 0
    assert len(executions) == 1
    skipped = executions[0]
    assert skipped.status == "skipped" and skipped.fire_time == due and skipped.tasks_created == 0
    if edge in ("before", "recovered_after_start"):
        assert row.is_active and row.next_fire_at >= schedule.active_from
        assert skipped.skip_reason == "Слот наступил до начала окна активности"
    else:
        assert not row.is_active and row.next_fire_at is None
        assert skipped.skip_reason == (
            "Окно активности расписания завершилось" if edge == "expired" else "Слот наступил до начала окна активности"
        )


@pytest.mark.parametrize("target", ["script", "pipeline"])
async def test_unavailable_target_skips_once_and_does_not_consume_quota(scheduler_runtime, target):
    r = scheduler_runtime
    one_shot = datetime.now(timezone.utc) - timedelta(minutes=1)
    schedule = await seed(r, target=target, interval_seconds=None, one_shot_at=one_shot, next_fire_at=one_shot)
    async with r.r.world.sessions() as db:
        if target == "script":
            (await db.get(Script, schedule.script_id)).is_archived = True
        else:
            (await db.get(Pipeline, schedule.pipeline_id)).is_active = False
        await db.commit()

    engine = SchedulerEngine()
    await engine._tick()
    await engine._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 0 and not row.is_active and row.next_fire_at is None
    assert len(executions) == 1 and executions[0].status == "skipped"
    assert executions[0].fire_time == one_shot and executions[0].tasks_created == 0


@pytest.mark.parametrize("target", ["script", "pipeline"])
async def test_schedule_history_projects_outcomes_from_exact_children(scheduler_runtime, target):
    r = scheduler_runtime
    world = r.r.world
    schedule = await seed(r, target=target, device_ids=[str(world.dev_a.id), str(world.dev_a2.id)])
    await SchedulerEngine()._tick()
    url = f"/api/v1/schedules/{schedule.id}/executions"
    auth = world.auth(world.users["org_admin"])
    active = await world.client.get(url, headers=auth)
    assert active.status_code == 200 and active.json()["items"][0]["status"] == "triggered"
    async with world.sessions() as db:
        model = Task if target == "script" else PipelineRun
        first, second = list(await db.scalars(select(model).where(model.org_id == schedule.org_id)))
        first.status = "completed"
        second.status = "cancelled"
        finished = datetime.now(timezone.utc)
        first.finished_at = second.finished_at = finished
        await db.commit()

    response = await world.client.get(url, headers=auth)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert (item["status"], item["tasks_created"], item["tasks_succeeded"], item["tasks_failed"]) == ("partial", 2, 1, 1)
    assert datetime.fromisoformat(item["finished_at"]) == finished
    _, receipts = await stored(r, schedule)
    assert receipts[0].status == "triggered"


async def test_schedule_api_preserves_disabled_state_and_rejects_misleading_fire_now(world):
    headers = world.auth(world.users["org_admin"])
    base = "/api/v1/schedules"
    fields = {
        "name": "schedule API regression", "target_type": "script", "script_id": str(world.script.id),
        "device_ids": [str(world.dev_a.id)], "one_shot_at": "2099-01-01T12:00",
    }
    created = await world.client.post(base, headers=headers, json=fields)
    assert created.status_code == 201, created.text
    item = created.json()
    assert datetime.fromisoformat(item["one_shot_at"]).utcoffset() == timedelta(0)
    url = f"{base}/{item['id']}"
    edited = await world.client.patch(url, headers=headers, json={"name": "edited", "is_active": False})
    assert edited.status_code == 200 and edited.json()["next_fire_at"] is None
    stopped = await world.client.post(url + "/fire-now", headers=headers)
    assert stopped.status_code == 409
    for invalid in ({"timezone": "Not/AZone"}, {"cron_expression": "invalid"}, {"one_shot_at": None}, {"name": None}):
        assert (await world.client.patch(url, headers=headers, json=invalid)).status_code == 422
    reread = await world.client.get(url, headers=headers)
    assert reread.json()["next_fire_at"] is None and reread.json()["name"] == "edited"


async def test_same_timing_patch_keeps_a_natural_due_slot_and_its_backlog_under_rls(scheduler_runtime):
    from backend.services.scheduler.schedule_service import ScheduleService

    r = scheduler_runtime
    oldest = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(second=0, microsecond=0)
    schedule = await seed(r, next_fire_at=oldest, timezone="UTC")
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(schedule.org_id))
        edited = await ScheduleService(db).update(
            schedule.id, schedule.org_id, expected_updated_at=schedule.updated_at,
            interval_seconds=60, timezone="UTC", is_active=True, name="Metadata only",
        )
        revision = edited.updated_at
        assert revision > schedule.updated_at and edited.next_fire_at == oldest
        await db.commit()
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(schedule.org_id))
        no_op = await ScheduleService(db).update(
            schedule.id, schedule.org_id, expected_updated_at=revision,
            interval_seconds=60, timezone="UTC", is_active=True,
        )
        assert no_op.updated_at == revision and no_op.next_fire_at == oldest
        await db.commit()
    await SchedulerEngine()._tick()
    _, executions = await stored(r, schedule)
    assert {(row.status, row.fire_time) for row in executions} == {
        ("triggered", oldest), ("skipped", oldest + timedelta(minutes=1)),
    }


async def test_competing_api_edits_and_launches_require_the_reviewed_revision_under_rls(scheduler_runtime):
    r = scheduler_runtime
    world = r.r.world
    future = datetime.now(timezone.utc) + timedelta(days=1)
    schedule = await seed(r, interval_seconds=None, one_shot_at=future, next_fire_at=future)
    url = f"/api/v1/schedules/{schedule.id}"
    headers = world.auth(world.users["org_admin"])
    baseline = schedule.updated_at.isoformat()
    stale = {"detail": "schedule_revision_conflict"}

    async def runtime_session():
        async with r.r.sessions() as db:
            yield db

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = runtime_session
    try:
        edit, disable = await asyncio.gather(
            world.client.patch(url, headers=headers, json={"name": "New configuration", "expected_updated_at": baseline}),
            world.client.post(
                url + "/toggle", headers=headers, params={"active": "false", "expected_updated_at": baseline},
            ),
        )
        assert sorted([edit.status_code, disable.status_code]) == [200, 409]
        rejected = edit if edit.status_code == 409 else disable
        assert rejected.json() == stale
        latest = (await world.client.get(url, headers=headers)).json()
        assert latest["is_active"] == (edit.status_code == 200)
        assert (latest["name"] == "New configuration") == (edit.status_code == 200)
        assert latest["updated_at"] != baseline

        rejected_delete = await world.client.delete(url, headers=headers, params={"expected_updated_at": baseline})
        assert rejected_delete.status_code == 409 and rejected_delete.json() == stale
        if not latest["is_active"]:
            enabled = await world.client.post(
                url + "/toggle", headers=headers,
                params={"active": "true", "expected_updated_at": latest["updated_at"]},
            )
            assert enabled.status_code == 200
            latest = enabled.json()
        key_headers = {**headers, "Idempotency-Key": str(uuid.uuid4())}
        rejected_fire = await world.client.post(
            url + "/fire-now", headers=key_headers, params={"expected_updated_at": baseline},
        )
        assert rejected_fire.status_code == 409 and rejected_fire.json() == stale
        async with world.sessions() as db:
            assert await db.get(ScheduleFireRequest, (schedule.org_id, schedule.id, uuid.UUID(key_headers["Idempotency-Key"]))) is None

        accepted = await world.client.post(
            url + "/fire-now", headers=key_headers, params={"expected_updated_at": latest["updated_at"]},
        )
        assert accepted.status_code == 200 and not accepted.json()["request_replayed"]
        await SchedulerEngine()._tick()
        replay = await world.client.post(
            url + "/fire-now", headers=key_headers, params={"expected_updated_at": latest["updated_at"]},
        )
        assert replay.status_code == 200 and replay.json()["request_replayed"]
        assert replay.json()["requested_fire_at"] == accepted.json()["requested_fire_at"]
        row, executions = await stored(r, schedule)
        assert not row.is_active and row.total_runs == len(executions) == 1

        invalid = await world.client.post(
            url + "/toggle", headers=headers, params={"active": "true", "expected_updated_at": "2099-01-01T12:00"},
        )
        assert invalid.status_code == 422
    finally:
        app.dependency_overrides[get_db] = original


async def test_keyed_fire_replays_after_one_shot_finishes_under_rls(scheduler_runtime):
    r = scheduler_runtime
    world = r.r.world
    future = datetime.now(timezone.utc) + timedelta(days=1)
    schedule = await seed(r, interval_seconds=None, one_shot_at=future, next_fire_at=future)
    url = f"/api/v1/schedules/{schedule.id}/fire-now"
    key = uuid.uuid4()
    headers = {**world.auth(world.users["org_admin"]), "Idempotency-Key": str(key)}

    async def runtime_session():
        async with r.r.sessions() as db:
            yield db

    async with r.r.sessions() as db:
        assert await db.scalar(text("SELECT row_security_active('schedule_fire_requests')")) is True
    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = runtime_session
    try:
        first, second = await asyncio.gather(
            world.client.post(url, headers=headers), world.client.post(url, headers=headers),
        )
        assert first.status_code == second.status_code == 200
        initial, duplicate = sorted((first.json(), second.json()), key=lambda item: item["request_replayed"])
        assert initial["request_replayed"] is False and duplicate["request_replayed"] is True
        assert initial["requested_fire_at"] == duplicate["requested_fire_at"]
        await SchedulerEngine()._tick()
        replay = await world.client.post(url, headers=headers)
        assert replay.status_code == 200
        assert replay.json()["request_replayed"] is True and not replay.json()["is_active"]
        assert replay.json()["requested_fire_at"] == initial["requested_fire_at"]
        another_key = await world.client.post(url, headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
        assert another_key.status_code == 409
        async with r.r.sessions() as db:
            await bind_tenant_context(db, str(world.org_b.id))
            assert await db.scalar(select(ScheduleFireRequest).where(ScheduleFireRequest.request_key == key)) is None
        row, executions = await stored(r, schedule)
        assert row.total_runs == 1 and len(executions) == 1 and executions[0].tasks_created == 1
    finally:
        app.dependency_overrides[get_db] = original


async def test_schedule_fire_receipt_rollback_and_expiry_are_atomic(scheduler_runtime):
    from backend.services.scheduler.schedule_service import ScheduleService

    r = scheduler_runtime
    world = r.r.world
    future = datetime.now(timezone.utc) + timedelta(days=1)
    schedule = await seed(r, next_fire_at=future)
    key = uuid.uuid4()
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(schedule.org_id))
        _, initial_slot, replayed = await ScheduleService(db).request_fire(schedule.id, schedule.org_id, key)
        assert not replayed and initial_slot < future
        await db.rollback()
    async with world.sessions() as db:
        assert await db.get(ScheduleFireRequest, (schedule.org_id, schedule.id, key)) is None
        assert (await db.get(Schedule, schedule.id)).next_fire_at == future
        db.add(ScheduleFireRequest(
            org_id=schedule.org_id, schedule_id=schedule.id, request_key=key,
            fire_at=initial_slot, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
        await db.commit()
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(schedule.org_id))
        _, new_slot, replayed = await ScheduleService(db).request_fire(schedule.id, schedule.org_id, key)
        assert not replayed and new_slot > initial_slot
        await db.commit()
    async with world.sessions() as db:
        stored_request = await db.get(ScheduleFireRequest, (schedule.org_id, schedule.id, key))
        assert stored_request.fire_at == new_slot and stored_request.expires_at > new_slot


@pytest.mark.parametrize("mutation", ["timing_edit", "patch_disable", "toggle_disable", "delete"])
async def test_manual_slot_gets_one_skip_when_superseded_under_rls(scheduler_runtime, mutation):
    r = scheduler_runtime
    world = r.r.world
    future = datetime.now(timezone.utc) + timedelta(days=1)
    schedule = await seed(r, next_fire_at=future)
    url = f"/api/v1/schedules/{schedule.id}"
    auth = world.auth(world.users["org_admin"])
    headers = [{**auth, "Idempotency-Key": str(uuid.uuid4())} for _ in range(2)]

    async def runtime_session():
        async with r.r.sessions() as db:
            yield db

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = runtime_session
    try:
        for header in headers:
            response = await world.client.post(url + "/fire-now", headers=header)
            assert response.status_code == 200
            if header is headers[0]:
                slot = response.json()["requested_fire_at"]
            else:
                assert response.json()["requested_fire_at"] == slot
        no_op = await world.client.patch(url, headers=auth, json={"interval_seconds": schedule.interval_seconds})
        renamed = await world.client.patch(url, headers=auth, json={"name": "unchanged timer"})
        assert no_op.status_code == renamed.status_code == 200
        assert no_op.json()["next_fire_at"] == renamed.json()["next_fire_at"] == slot
        assert not (await stored(r, schedule))[1]

        if mutation == "timing_edit":
            method, path, body, code = "PATCH", url, {"interval_seconds": 120}, 200
        elif mutation == "patch_disable":
            method, path, body, code = "PATCH", url, {"is_active": False}, 200
        elif mutation == "toggle_disable":
            method, path, body, code = "POST", url + "/toggle?active=false", None, 200
        else:
            method, path, body, code = "DELETE", url, None, 204
        for _ in range(2):
            changed = await world.client.request(method, path, headers=auth, json=body)
            assert changed.status_code == code, changed.text

        for header in headers:
            replay = await world.client.post(url + "/fire-now", headers=header)
            assert replay.status_code == 200 and replay.json()["request_replayed"] is True
            assert replay.json()["requested_fire_at"] == slot
        await SchedulerEngine()._tick()
        row, executions = await stored(r, schedule)
        assert row.total_runs == 0 and len(executions) == 1
        [execution] = executions
        assert execution.status == "skipped" and execution.tasks_created == 0
        assert execution.fire_time == datetime.fromisoformat(slot)
        assert execution.finished_at == execution.actual_time
        if mutation == "timing_edit":
            assert execution.skip_reason == "Настройки расписания изменились до запуска"
            assert row.is_active and row.next_fire_at > datetime.now(timezone.utc)
        else:
            assert execution.skip_reason == "Расписание выключено до запуска"
            assert not row.is_active and row.next_fire_at is None
    finally:
        app.dependency_overrides[get_db] = original


async def test_superseded_manual_slot_rollback_preserves_pending_firing_under_rls(scheduler_runtime):
    from backend.services.scheduler.schedule_service import ScheduleService

    r = scheduler_runtime
    future = datetime.now(timezone.utc) + timedelta(days=1)
    schedule = await seed(r, next_fire_at=future)
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(schedule.org_id))
        service = ScheduleService(db)
        _, slot, _ = await service.request_fire(schedule.id, schedule.org_id, uuid.uuid4())
        await db.commit()
        await service.toggle(schedule.id, schedule.org_id, False)
        await db.rollback()
    row, executions = await stored(r, schedule)
    assert row.is_active and row.next_fire_at == slot and not executions
    await SchedulerEngine()._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and len(executions) == 1 and executions[0].fire_time == slot
    assert executions[0].status == "triggered"


@pytest.mark.parametrize("target", ["script", "pipeline"])
async def test_binding_lock_defers_entire_scheduled_firing(scheduler_runtime, target):
    r = scheduler_runtime
    world = r.r.world
    schedule = await seed(r, target=target, device_ids=[str(world.dev_a.id), str(world.dev_a2.id)])
    engine = SchedulerEngine()
    async with world.sessions() as lock:
        await lock.scalar(select(Device).where(Device.id == world.dev_a.id).with_for_update())
        await engine._tick()
        row, executions = await stored(r, schedule)
        assert row.next_fire_at == schedule.next_fire_at
        assert not executions
        model = Task if target == "script" else PipelineRun
        assert await lock.scalar(select(func.count()).select_from(model).where(model.org_id == schedule.org_id)) == 0
    await engine._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and len(executions) == 1
    assert executions[0].tasks_created == 2


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
    assert len(executions) == 3
    assert sum(execution.status == "triggered" for execution in executions) == 1
    assert any(execution.skip_reason == "Просроченные слоты объединены, повторный запуск не создан" for execution in executions)
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
                # Wait for termination; a signal acknowledgement alone is not a disconnect barrier.
                assert await control.scalar(text("SELECT pg_terminate_backend(:pid, 2000)"), {"pid": backend_pid})
            killed = True
    monkeypatch.setattr(engine, "_process_schedule", disconnect)
    await engine._tick()
    assert killed and not (await stored(r, schedule))[1]
    await engine._tick()
    row, executions = await stored(r, schedule)
    assert row.total_runs == 1 and len(executions) == 1
    async with r.r.world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.org_id == schedule.org_id)) == 1
