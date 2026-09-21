"""A watchdog deadline is not evidence that an APK has stopped its execution."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.database.tenant import bind_tenant_context
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch
from backend.services.task_service import TaskService
from backend.tasks import task_heartbeat_watchdog as watchdog

LOOKUP = "sphere_auth.watchdog_work(integer,integer,uuid)"


@pytest_asyncio.fixture
async def watchdog_runtime(runtime_db, monkeypatch):
    r = runtime_db
    ids = set()
    queue, publisher = AsyncMock(), AsyncMock()
    publisher.send_command_live.return_value = True
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", r.sessions)
    monkeypatch.setattr("backend.database.redis_client.redis_binary", None)
    monkeypatch.setattr("backend.services.task_queue.TaskQueue", lambda *_: queue)
    monkeypatch.setattr("backend.websocket.pubsub_router.get_pubsub_publisher", lambda: publisher)
    monkeypatch.setattr(watchdog, "_STALE_BUFFER_SECONDS", 300)
    monkeypatch.setattr(watchdog, "_QUEUED_STALE_MINUTES", 60)
    if hasattr(watchdog, "_watchdog_cursor"):
        monkeypatch.setattr(watchdog, "_watchdog_cursor", None)
    async with r.world.engine.begin() as db:
        exists = await db.scalar(text("SELECT to_regprocedure(:lookup)"), {"lookup": LOOKUP})
        if exists:
            await db.execute(text(f'GRANT EXECUTE ON FUNCTION {LOOKUP} TO "{r.role}"'))
    if hasattr(watchdog, "_discover_stale_tasks"):
        original = watchdog._discover_stale_tasks
        async def discover(*args, **kwargs):
            return [row for row in await original(*args, **kwargs) if row[0] in ids]
        monkeypatch.setattr(watchdog, "_discover_stale_tasks", discover)
    try:
        yield SimpleNamespace(**locals())
    finally:
        async with r.world.sessions() as db:
            await db.execute(update(Task).where(Task.id.in_(ids)).values(
                status=TaskStatus.COMPLETED, cancel_requested_at=None, cancel_last_sent_at=None,
            ))
            await db.commit()
        if exists:
            async with r.world.engine.begin() as db:
                await db.execute(text(f'REVOKE EXECUTE ON FUNCTION {LOOKUP} FROM "{r.role}"'))


async def seed(r, status=TaskStatus.RUNNING, *, stale=True, started=True, device=None):
    w = r.r.world
    device = device or w.dev_a
    age = datetime.now(timezone.utc)-timedelta(hours=2) if stale else datetime.now(timezone.utc)
    async with w.sessions() as db:
        batch = TaskBatch(org_id=device.org_id, script_id=w.script.id, total=1)
        db.add(batch)
        await db.flush()
        task = Task(id=uuid.UUID(int=uuid.uuid4().int >> 64), org_id=device.org_id, device_id=device.id,
                    script_id=w.script.id, script_version_id=w.version.id, batch_id=batch.id,
                    status=status, timeout_seconds=60, created_at=age, updated_at=age,
                    started_at=age if status == TaskStatus.RUNNING and started else None)
        db.add(task)
        await db.commit()
        r.ids.add(task.id)
        return task


async def process_scoped(r):
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(r.r.world.org_a.id))
        result = await watchdog._process_stale_tasks(db, stale_buffer_seconds=300, queued_stale_minutes=60)
        await db.commit()
        return result


async def stored(r, task):
    async with r.r.world.sessions() as db:
        return await db.get(Task, task.id), await db.get(TaskBatch, task.batch_id)


async def test_runtime_tick_expires_never_dispatched_task_under_rls(watchdog_runtime):
    r = watchdog_runtime
    task = await seed(r, TaskStatus.QUEUED)
    await watchdog._expire_stale_tasks()
    row, batch = await stored(r, task)
    assert row.status == TaskStatus.TIMEOUT and row.finished_at is not None
    assert batch.failed == 1


@pytest.mark.parametrize("status", [TaskStatus.ASSIGNED, TaskStatus.RUNNING])
async def test_deadline_keeps_device_fenced_until_terminal_apk_receipt(watchdog_runtime, status):
    r = watchdog_runtime
    task = await seed(r, status)
    later = await seed(r, TaskStatus.QUEUED, stale=False)
    await process_scoped(r)
    cache = AsyncMock()
    cache.bulk_get_status.return_value = {str(task.device_id): SimpleNamespace(status="online")}
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(task.org_id))
        await TaskService(db, status_cache=cache, publisher=r.publisher).dispatch_pending_tasks(org_id=task.org_id)
    commands = [call.args[1] for call in r.publisher.send_command_live.await_args_list]
    assert not any(c["type"] == "EXECUTE_DAG" for c in commands), "Deadline released device before physical stop"
    assert any(c["type"] == "CANCEL_DAG" and c["payload"]["task_id"] == str(task.id) for c in commands)
    row, batch = await stored(r, task)
    assert row.status == status and row.finished_at is None and row.cancel_requested_at is not None
    assert getattr(row, "timeout_requested_at", None) is not None and batch.failed == 0
    assert (await stored(r, later))[0].status == TaskStatus.QUEUED


async def test_running_without_start_receipt_requests_stop_after_queue_deadline(watchdog_runtime):
    r = watchdog_runtime
    task = await seed(r, started=False)
    await process_scoped(r)
    row, batch = await stored(r, task)
    assert row.cancel_requested_at is not None and row.status == TaskStatus.RUNNING
    assert getattr(row, "timeout_requested_at", None) is not None and batch.failed == 0


async def receipt(r, task, result):
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(task.org_id))
        accepted = await TaskService(db, r.queue).handle_task_result(str(task.id), str(task.device_id), result, str(task.org_id))
        await db.commit()
        return accepted


@pytest.mark.parametrize("status", [TaskStatus.ASSIGNED, TaskStatus.RUNNING])
async def test_failed_stop_delivery_recovers_and_only_terminal_receipt_counts_batch(watchdog_runtime, status):
    r = watchdog_runtime
    task = await seed(r, status)
    await watchdog._expire_stale_tasks()
    r.publisher.send_command_live.assert_not_awaited()
    first, _ = await stored(r, task)
    r.publisher.send_command_live.side_effect = ConnectionError("isolated lost stop response")
    for _ in range(2):
        async with r.r.sessions() as db:
            await bind_tenant_context(db, str(task.org_id))
            await TaskService(db, publisher=r.publisher).dispatch_pending_cancellations(org_id=task.org_id)
        async with r.r.world.sessions() as db:
            (await db.get(Task, task.id)).cancel_last_sent_at = datetime.now(timezone.utc)-timedelta(seconds=10)
            await db.commit()
        r.publisher.send_command_live.side_effect = None
    commands = [call.args[1] for call in r.publisher.send_command_live.await_args_list]
    assert len(commands) == 2 and {c["command_id"] for c in commands} == {f"user_cancel_{task.id}"}
    assert all(c["payload"] == {"task_id": str(task.id), "durable": True} for c in commands)
    await watchdog._expire_stale_tasks()
    row, batch = await stored(r, task)
    assert row.status == status and row.timeout_requested_at == first.timeout_requested_at
    assert batch.failed == 0 and row.finished_at is None
    result = {"success": False, "cancelled": True, "error": "cancelled_by_user"}
    assert await receipt(r, task, result)
    assert await receipt(r, task, result)
    row, batch = await stored(r, task)
    assert row.status == TaskStatus.TIMEOUT and row.finished_at is not None
    assert batch.failed == 1 and batch.succeeded == 0


@pytest.mark.parametrize("error", ["execution_outcome_unknown_after_restart", "execution_interrupted_outcome_unknown",
                                  "Root command delivery outcome is unknown"])
async def test_unknown_apk_outcome_retains_timeout_stop_fence(watchdog_runtime, error):
    r = watchdog_runtime
    task = await seed(r)
    await watchdog._expire_stale_tasks()
    assert not await receipt(r, task, {"success": False, "error": error})
    row, batch = await stored(r, task)
    assert row.status == TaskStatus.RUNNING and row.finished_at is None
    assert row.timeout_requested_at is not None and row.cancel_requested_at is not None
    assert batch.failed == 0
    r.queue.mark_completed.assert_not_awaited()


async def test_successful_physical_outcome_wins_timeout_stop_race(watchdog_runtime):
    r = watchdog_runtime
    task = await seed(r)
    await watchdog._expire_stale_tasks()
    assert await receipt(r, task, {"success": True, "output": "completed before stop"})
    row, batch = await stored(r, task)
    assert row.status == TaskStatus.COMPLETED and row.timeout_requested_at is not None
    assert batch.succeeded == 1 and batch.failed == 0


async def test_existing_user_cancel_remains_cancellation_not_watchdog_timeout(watchdog_runtime):
    r = watchdog_runtime
    task = await seed(r)
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(task.org_id))
        await TaskService(db).force_stop_task(task.id, task.org_id)
        await db.commit()
    await watchdog._expire_stale_tasks()
    assert (await stored(r, task))[0].timeout_requested_at is None
    assert await receipt(r, task, {"success": False, "cancelled": True})
    assert (await stored(r, task))[0].status == TaskStatus.CANCELLED


async def test_two_tenants_and_competing_ticks_do_not_leak_or_double_account(watchdog_runtime):
    r = watchdog_runtime
    tasks = [await seed(r, TaskStatus.QUEUED, device=r.r.world.dev_a),
             await seed(r, device=r.r.world.dev_b)]
    await asyncio.gather(watchdog._expire_stale_tasks(), watchdog._expire_stale_tasks())
    await watchdog._expire_stale_tasks()
    queued, queued_batch = await stored(r, tasks[0])
    running, running_batch = await stored(r, tasks[1])
    assert queued.status == TaskStatus.TIMEOUT and queued_batch.failed == 1
    assert running.status == TaskStatus.RUNNING and running.cancel_requested_at is not None
    assert running_batch.failed == 0
    async with r.r.sessions() as db:
        assert list(await db.scalars(select(Task).where(Task.id.in_(r.ids)))) == []
        assert await db.scalar(text("SELECT nullif(current_setting('app.current_org_id',true),'')")) is None


@pytest.mark.parametrize("after_commit", [False, True])
async def test_lost_commit_response_preserves_one_timeout_intent(watchdog_runtime, monkeypatch, after_commit):
    r = watchdog_runtime
    task = await seed(r, TaskStatus.QUEUED)
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
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", async_sessionmaker(r.r.engine, class_=FailCommit, expire_on_commit=False))
    await watchdog._expire_stale_tasks()
    assert (await stored(r, task))[1].failed == int(after_commit)
    await watchdog._expire_stale_tasks()
    row, batch = await stored(r, task)
    assert row.status == TaskStatus.TIMEOUT and batch.failed == 1
    r.publisher.send_command_live.assert_not_awaited()


async def test_result_owner_lock_prevents_watchdog_overwrite(watchdog_runtime):
    r = watchdog_runtime
    task = await seed(r)
    async with r.r.world.sessions() as db:
        await TaskService(db, r.queue).handle_task_result(str(task.id), str(task.device_id), {"success": True}, str(task.org_id))
        await db.flush()
        await asyncio.wait_for(watchdog._expire_stale_tasks(), 3)
        await db.commit()
    row, batch = await stored(r, task)
    assert row.status == TaskStatus.COMPLETED and row.timeout_requested_at is None
    assert row.cancel_requested_at is None and batch.succeeded == 1 and batch.failed == 0


async def test_pending_stop_does_not_hide_next_discovery_page(watchdog_runtime):
    r = watchdog_runtime
    for _ in range(65):
        await seed(r)
    await watchdog._expire_stale_tasks()
    async with r.r.world.sessions() as db:
        first = list(await db.scalars(select(Task).where(Task.id.in_(r.ids), Task.cancel_requested_at.is_not(None))))
    assert len(first) == 64
    await watchdog._expire_stale_tasks()
    async with r.r.world.sessions() as db:
        all_tasks = list(await db.scalars(select(Task).where(Task.id.in_(r.ids))))
    assert len(all_tasks) == 65 and all(t.cancel_requested_at is not None for t in all_tasks)
    assert all(t.status == TaskStatus.RUNNING and t.finished_at is None for t in all_tasks)


async def test_missing_grant_recovers_without_restarting_watchdog(watchdog_runtime):
    r = watchdog_runtime
    task = await seed(r)
    async with r.r.world.engine.begin() as db:
        await db.execute(text(f'REVOKE EXECUTE ON FUNCTION {LOOKUP} FROM "{r.r.role}"'))
    try:
        with pytest.raises(DBAPIError):
            await watchdog._expire_stale_tasks()
    finally:
        async with r.r.world.engine.begin() as db:
            await db.execute(text(f'GRANT EXECUTE ON FUNCTION {LOOKUP} TO "{r.r.role}"'))
    await watchdog._expire_stale_tasks()
    assert (await stored(r, task))[0].timeout_requested_at is not None


@pytest.mark.parametrize("stage", ["discovery", "intent"])
async def test_sql_timeout_rolls_back_and_recovers(watchdog_runtime, monkeypatch, stage):
    r = watchdog_runtime
    task = await seed(r)
    stalled = False
    if stage == "discovery":
        class SlowDiscovery(AsyncSession):
            async def execute(self, statement, *args, **kwargs):
                nonlocal stalled
                if "sphere_auth.watchdog_work" in str(statement) and not stalled:
                    stalled = True
                    await super().execute(text("SELECT pg_sleep(5)"))
                return await super().execute(statement, *args, **kwargs)
        monkeypatch.setattr(watchdog, "AsyncSessionLocal", async_sessionmaker(r.r.engine, class_=SlowDiscovery, expire_on_commit=False))
        monkeypatch.setattr(watchdog, "_DISCOVERY_TIMEOUT_SECONDS", 0.2)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(watchdog._expire_stale_tasks(), 2)
        monkeypatch.setattr(watchdog, "_DISCOVERY_TIMEOUT_SECONDS", 5)
    else:
        original = watchdog._process_stale_tasks
        async def slow(db, **kwargs):
            nonlocal stalled
            result = await original(db, **kwargs)
            if not stalled:
                stalled = True
                await db.flush()
                await db.execute(text("SELECT pg_sleep(5)"))
            return result
        monkeypatch.setattr(watchdog, "_process_stale_tasks", slow)
        monkeypatch.setattr(watchdog, "_TASK_TIMEOUT_SECONDS", 0.2)
        await asyncio.wait_for(watchdog._expire_stale_tasks(), 2)
        monkeypatch.setattr(watchdog, "_TASK_TIMEOUT_SECONDS", 10)
    assert (await stored(r, task))[0].cancel_requested_at is None
    await watchdog._expire_stale_tasks()
    assert (await stored(r, task))[0].timeout_requested_at is not None


async def test_watchdog_does_not_lock_healthy_running_tasks(watchdog_runtime):
    r = watchdog_runtime
    overdue = await seed(r)
    healthy = await seed(r, stale=False)
    async with r.r.sessions() as db:
        await bind_tenant_context(db, str(overdue.org_id))
        await watchdog._process_stale_tasks(db, stale_buffer_seconds=300, queued_stale_minutes=60, org_id=overdue.org_id)
        # The watchdog still holds its overdue task lock. Healthy work must stay
        # writable by the device receipt handler during the same transaction.
        async with r.r.world.sessions() as observer:
            current = await observer.scalar(select(Task).where(Task.id == healthy.id).with_for_update(nowait=True))
            assert current.status == TaskStatus.RUNNING
        await db.commit()


async def test_task_api_exposes_deadline_intent_without_terminal_status(watchdog_runtime):
    r = watchdog_runtime
    task = await seed(r)
    await watchdog._expire_stale_tasks()
    w = r.r.world
    response = await w.client.get(f"/api/v1/tasks/{task.id}", headers=w.auth(w.users["org_admin"]))
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running" and data["finished_at"] is None
    assert data["timeout_requested_at"] and data["cancel_requested_at"]
