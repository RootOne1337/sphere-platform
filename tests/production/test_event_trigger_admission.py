"""Real RLS trigger budgets, replay, and simulation."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database.engine import get_db
from backend.database.tenant import bind_tenant_context
from backend.main import app
from backend.models.device_event import DeviceEvent, EventSeverity
from backend.models.event_trigger import EventTrigger
from backend.models.pipeline import Pipeline, PipelineRun
from backend.models.task import Task, TaskStatus
from backend.services.application_automation_service import lock_admission_devices
from backend.services.event_reactor import EventReactor
from backend.services.orchestrator import step_handlers
from backend.services.task_service import TaskService


async def create_trigger(world, *, limit=1, cooldown=0, pattern="audit.trigger.*"):
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name="Trigger admission fixture", steps=[])
        db.add(pipeline)
        await db.flush()
        trigger = EventTrigger(
            org_id=world.org_a.id, pipeline_id=pipeline.id, name="Trigger admission fixture",
            event_type_pattern=pattern, cooldown_seconds=cooldown, max_triggers_per_hour=limit,
        )
        db.add(trigger)
        await db.commit()
        return trigger


async def persist_event(db, device):
    event = DeviceEvent(
        org_id=device.org_id, device_id=device.id, event_type="audit.trigger.sample", severity=EventSeverity.info,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    return event


async def fire(db, device, *, commit=True):
    event = await EventReactor(db).process_event(device.org_id, device.id, "audit.trigger.sample")
    if commit:
        await db.commit()
    return event


async def admitted_runs(world, trigger):
    async with world.sessions() as db:
        return list(await db.scalars(select(PipelineRun).where(
            PipelineRun.org_id == trigger.org_id, PipelineRun.event_trigger_id == trigger.id,
        )))


async def test_trigger_hourly_cap_concurrent_event_ingestion_under_rls(runtime_db):
    world = runtime_db.world
    trigger = await create_trigger(world)
    engine = create_async_engine(runtime_db.engine.url, pool_size=2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as first, sessions() as second:
            await bind_tenant_context(first, str(world.org_a.id))
            await bind_tenant_context(second, str(world.org_a.id))
            first_event = await persist_event(first, world.dev_a)
            second_event = await persist_event(second, world.dev_a)
            # Both events already hold PostgreSQL FK KEY SHARE on this device.
            assert await lock_admission_devices(first, world.org_a.id, [world.dev_a.id]) == [world.dev_a.id]
            await EventReactor(first)._check_event_triggers(
                first_event.org_id, first_event.device_id, first_event.event_type, first_event,
            )
            async def check(db, event):
                await EventReactor(db)._check_event_triggers(
                    event.org_id, event.device_id, event.event_type, event,
                )
                await db.commit()
            pending = asyncio.create_task(check(second, second_event))
            try:
                async with asyncio.timeout(5), world.sessions() as observer:
                    # Confirm overlap, rather than merely issuing two serial calls.
                    while not await observer.scalar(text("""
                        SELECT EXISTS(
                            SELECT 1 FROM pg_stat_activity
                            WHERE usename = :role AND wait_event_type = 'Lock'
                        )
                    """), {"role": runtime_db.role}):
                        await asyncio.sleep(0.01)
                await first.commit()
                await asyncio.wait_for(pending, timeout=10)
            finally:
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
    finally:
        await engine.dispose()
    [run] = await admitted_runs(world, trigger)
    assert run.trigger_event_id in {first_event.id, second_event.id}
    assert run.trigger_accepted_at is not None
    async with world.sessions() as db:
        assert (await db.get(EventTrigger, trigger.id)).total_triggers == 1


async def test_trigger_rollback_replay_and_rolling_window(runtime_db):
    world = runtime_db.world
    trigger = await create_trigger(world, limit=0)
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        aborted = await fire(db, world.dev_a, commit=False)
        aborted_id = aborted.id
        await db.rollback()
    assert not await admitted_runs(world, trigger)
    async with world.sessions() as db:
        assert await db.get(DeviceEvent, aborted_id) is None
        assert (await db.get(EventTrigger, trigger.id)).total_triggers == 0

    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        event = await fire(db, world.dev_a)
        await bind_tenant_context(db, str(world.org_a.id))
        await EventReactor(db)._check_event_triggers(event.org_id, event.device_id, event.event_type, event)
        await db.commit()
    [first_run] = await admitted_runs(world, trigger)

    async with world.sessions() as db:
        (await db.get(EventTrigger, trigger.id)).max_triggers_per_hour = 1
        (await db.get(PipelineRun, first_run.id)).trigger_accepted_at -= timedelta(hours=2)
        await db.commit()
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        await fire(db, world.dev_a)
        await bind_tenant_context(db, str(world.org_a.id))
        await fire(db, world.dev_a)
    assert len(await admitted_runs(world, trigger)) == 2


async def test_trigger_cooldown_shared_by_runtime_and_simulation(runtime_db):
    world = runtime_db.world
    trigger = await create_trigger(world, limit=0, cooldown=300)
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        await fire(db, world.dev_a)
        await bind_tenant_context(db, str(world.org_a.id))
        await fire(db, world.dev_a2)
    assert len(await admitted_runs(world, trigger)) == 1
    response = await world.client.get(
        f"/api/v1/event-triggers/{trigger.id}/simulate", headers=world.auth(world.users["viewer"]),
        params={"event_type": "audit.trigger.sample"},
    )
    assert response.status_code == 200 and response.json()["reason"] == "cooldown"
    assert response.json()["recent_runs"] == 1 and response.json()["max_triggers_per_hour"] == 0


async def test_busy_trigger_target_preserves_event_and_other_trigger(runtime_db):
    world = runtime_db.world
    busy = await create_trigger(world)
    available = await create_trigger(world)
    async with world.sessions() as locker, runtime_db.sessions() as db:
        await locker.scalar(select(Pipeline.id).where(Pipeline.id == busy.pipeline_id).with_for_update())
        await bind_tenant_context(db, str(world.org_a.id))
        event = await asyncio.wait_for(fire(db, world.dev_a), timeout=5)
        assert event.processed
    assert not await admitted_runs(world, busy)
    [run] = await admitted_runs(world, available)
    assert run.trigger_event_id == event.id


async def test_trigger_simulation_is_readonly_and_tenant_scoped(runtime_db):
    world = runtime_db.world
    trigger = await create_trigger(world)
    url = f"/api/v1/event-triggers/{trigger.id}/simulate"
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        await fire(db, world.dev_a)

    async def restricted_db():
        async with runtime_db.sessions() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = restricted_db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://audit.local",
        ) as client:
            headers = world.auth(world.users["viewer"])
            response = await client.get(url, headers=headers, params={"event_type": "audit.trigger.sample"})
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            body = response.json()
            assert body["matches"] and not body["would_admit"] and body["reason"] == "hour_limit"
            assert body["event_id"] is body["event_origin"] is body["cause_depth"] is body["root_runs"] is None
            assert body["recent_runs"] == 1 and body["max_triggers_per_hour"] == 1
            assert datetime.fromisoformat(body["retry_at"]) > datetime.fromisoformat(body["observed_at"])
            mismatch = await client.get(url, headers=headers, params={"event_type": "AUDIT.trigger.sample"})
            assert mismatch.json()["reason"] == "pattern_mismatch" and mismatch.json()["retry_at"] is None
            foreign = await client.get(url, headers=world.auth(world.users["foreign"]), params={"event_type": "audit.trigger.sample"})
            assert foreign.status_code == 404
    finally:
        app.dependency_overrides[get_db] = previous
    assert len(await admitted_runs(world, trigger)) == 1
    async with world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DeviceEvent).where(DeviceEvent.org_id == world.org_a.id)) == 1


async def complete_pipeline_child(runtime_db, run, success):
    world = runtime_db.world
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        stored = await db.get(PipelineRun, run.id)
        step = {"id": "task", "params": {"script_id": str(world.script.id)}}
        await step_handlers.handle_execute_script(step, stored, db)
        task_id = stored.current_task_id
        await bind_tenant_context(db, str(world.org_a.id))
        task = await db.get(Task, task_id)
        assert task.pipeline_run_id == run.id
        task.status = TaskStatus.RUNNING
        await db.commit()

    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        service = TaskService(db, AsyncMock(), publisher=AsyncMock())
        assert await service.handle_task_result(str(task_id), str(run.device_id), {"success": success}, str(run.org_id))
        await db.commit()
        await bind_tenant_context(db, str(world.org_a.id))
        assert await service.handle_task_result(str(task_id), str(run.device_id), {"success": success}, str(run.org_id))
        await db.commit()
    async with world.sessions() as db:
        return (await db.scalars(select(DeviceEvent).where(DeviceEvent.task_id == task_id))).one()


async def test_pipeline_task_receipts_preserve_cause_and_stop_a_b_a(runtime_db, monkeypatch):
    world = runtime_db.world
    first = await create_trigger(world, limit=0, pattern="task.completed")
    second = await create_trigger(world, limit=0, pattern="task.failed")
    monkeypatch.setattr(step_handlers, "_wait_for_task", AsyncMock(return_value=step_handlers.StepResult()))
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        root = await EventReactor(db).process_event(world.org_a.id, world.dev_a.id, "task.completed")
        await db.commit()
    [run_a] = await admitted_runs(world, first)
    event_a = await complete_pipeline_child(runtime_db, run_a, False)
    [run_b] = await admitted_runs(world, second)
    event_b = await complete_pipeline_child(runtime_db, run_b, True)
    assert len(await admitted_runs(world, first)) == 1
    assert event_a.pipeline_run_id == run_a.id
    assert event_b.pipeline_run_id == run_b.id
    assert event_a.trigger_root_event_id == event_b.trigger_root_event_id == root.id
    assert event_a.trigger_path == [str(first.id)]
    assert event_b.trigger_path == [str(first.id), str(second.id)]

    headers = world.auth(world.users["viewer"])
    url = f"/api/v1/event-triggers/{first.id}/simulate"
    simulated = await world.client.get(url, headers=headers, params={"event_id": str(event_b.id)})
    assert simulated.status_code == 200, simulated.text
    body = simulated.json()
    assert body["reason"] == "causal_cycle" and not body["would_admit"]
    assert body["event_id"] == str(event_b.id) and body["event_origin"] == "pipeline"
    assert body["root_event_id"] == str(root.id) and body["cause_depth"] == body["root_runs"] == 2
    assert "data" not in body and "message" not in body
    assert (await world.client.get(url, headers=headers, params={"event_id": str(root.id)})).json()["reason"] == "duplicate_event"
    assert (await world.client.get(url, headers=headers, params={"event_id": str(uuid.uuid4())})).status_code == 404
    assert (await world.client.get(url, headers=headers)).status_code == 422
    assert (await world.client.get(url, headers=headers, params={
        "event_id": str(root.id), "event_type": "task.failed",
    })).status_code == 422


async def test_ws_transport_replay_uses_owned_event_identity_once(runtime_db, monkeypatch):
    from backend.api.ws.android.router import handle_device_event

    world = runtime_db.world
    trigger = await create_trigger(world, limit=0)
    engine = create_async_engine(runtime_db.engine.url, pool_size=2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    publisher = AsyncMock()
    monkeypatch.setattr("backend.api.ws.android.router.AsyncSessionLocal", sessions)
    monkeypatch.setattr("backend.websocket.event_publisher.get_event_publisher", lambda: publisher)
    source_event_id = uuid.uuid4()
    message = {
        "type": "event", "event_type": "audit.trigger.sample", "event_id": str(source_event_id),
        "pipeline_run_id": str(uuid.uuid4()), "data": {"trigger_path": ["untrusted"], "trigger_root_event_id": "fake"},
    }
    try:
        await asyncio.gather(*[
            handle_device_event(str(world.dev_a.id), str(world.org_a.id), message)
            for _ in range(2)
        ])
        assert publisher.emit.await_count == 1
        [run] = await admitted_runs(world, trigger)
        await handle_device_event(str(world.dev_a2.id), str(world.org_a.id), message)
        await handle_device_event(str(world.dev_b.id), str(world.org_b.id), message)
        await handle_device_event(str(world.dev_a.id), str(world.org_a.id), {**message, "event_id": "bad"})
    finally:
        await engine.dispose()
    assert publisher.emit.await_count == 3
    assert len(await admitted_runs(world, trigger)) == 2
    async with world.sessions() as db:
        events = list(await db.scalars(select(DeviceEvent).where(DeviceEvent.source_event_id == source_event_id)))
        assert len(events) == 3
        [first] = [event for event in events if event.id == run.trigger_event_id]
        assert first.pipeline_run_id is first.trigger_root_event_id is first.trigger_path is None


@pytest.mark.parametrize(("depth", "reason"), [(8, "depth_limit"), (1, "root_limit")])
async def test_causal_budget_blocks_event_without_losing_it(runtime_db, depth, reason, monkeypatch):
    world = runtime_db.world
    trigger = await create_trigger(world, limit=0)
    monkeypatch.setattr("backend.services.event_trigger_admission.MAX_ROOT_RUNS", 1)
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        root = await fire(db, world.dev_a)
    [run] = await admitted_runs(world, trigger)
    next_trigger = await create_trigger(world, limit=0)
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        derived = await persist_event(db, world.dev_a)
        derived.pipeline_run_id = run.id
        derived.trigger_root_event_id = root.id
        derived.trigger_path = [str(uuid.uuid4()) for _ in range(depth)]
        await db.flush()
        await EventReactor(db)._check_event_triggers(derived.org_id, derived.device_id, derived.event_type, derived)
        await db.commit()
    response = await world.client.get(
        f"/api/v1/event-triggers/{next_trigger.id}/simulate",
        headers=world.auth(world.users["viewer"]), params={"event_id": str(derived.id)},
    )
    assert response.status_code == 200 and response.json()["reason"] == reason
    assert response.json()["retry_at"] is None
    assert not await admitted_runs(world, next_trigger)
    assert len(await admitted_runs(world, trigger)) == 1
    async with world.sessions() as db:
        assert await db.get(DeviceEvent, derived.id) is not None


async def test_distinct_rules_contend_for_the_same_root_budget(runtime_db, monkeypatch):
    world = runtime_db.world
    first = await create_trigger(world, limit=0, pattern="audit.branch.one")
    second = await create_trigger(world, limit=0, pattern="audit.branch.two")
    monkeypatch.setattr("backend.services.event_trigger_admission.MAX_ROOT_RUNS", 1)
    engine = create_async_engine(runtime_db.engine.url, pool_size=2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db_a, sessions() as db_b:
            await bind_tenant_context(db_a, str(world.org_a.id))
            root = await persist_event(db_a, world.dev_a)
            await db_a.commit()
            await bind_tenant_context(db_a, str(world.org_a.id))
            await bind_tenant_context(db_b, str(world.org_a.id))
            event_a = await persist_event(db_a, world.dev_a)
            event_b = await persist_event(db_b, world.dev_a)
            for event, kind in ((event_a, "audit.branch.one"), (event_b, "audit.branch.two")):
                event.event_type = kind
                event.trigger_root_event_id = root.id
                event.trigger_path = []
            await EventReactor(db_a)._check_event_triggers(event_a.org_id, event_a.device_id, event_a.event_type, event_a)

            async def attempt_second():
                await EventReactor(db_b)._check_event_triggers(
                    event_b.org_id, event_b.device_id, event_b.event_type, event_b,
                )
                await db_b.commit()

            pending = asyncio.create_task(attempt_second())
            try:
                async with asyncio.timeout(5), world.sessions() as observer:
                    while not await observer.scalar(text("""
                        SELECT EXISTS(
                            SELECT 1 FROM pg_stat_activity
                            WHERE usename = :role AND wait_event_type = 'Lock'
                        )
                    """), {"role": runtime_db.role}):
                        await asyncio.sleep(0.01)
                await db_a.commit()
                await asyncio.wait_for(pending, timeout=10)
            finally:
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
    finally:
        await engine.dispose()
    assert len(await admitted_runs(world, first)) == 1
    assert not await admitted_runs(world, second)
