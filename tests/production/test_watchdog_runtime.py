"""Exercise watchdog deadlines and transaction outcomes on PostgreSQL itself."""

import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.database.tenant import bind_tenant_context
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.tasks.task_heartbeat_watchdog import _expire_stale_tasks, _process_stale_tasks


@pytest.fixture(autouse=True)
def non_utc_process_timezone(monkeypatch):
    # Exercise the production failure on UTC CI hosts too. Windows has no tzset;
    # its local reproduction was captured on an Asia/Yekaterinburg (+05) host.
    if not hasattr(time, "tzset"):
        yield
        return
    try:
        with monkeypatch.context() as context:
            context.setenv("TZ", "Etc/GMT-5")
            time.tzset()
            yield
    finally:
        time.tzset()


async def test_watchdog_expires_only_due_tasks_and_accounts_once(world):
    w = world
    now = datetime.now(timezone.utc)
    async with w.sessions() as db:
        await bind_tenant_context(db, str(w.org_a.id))
        batch = TaskBatch(org_id=w.org_a.id, script_id=w.script.id, total=3)
        db.add(batch)
        await db.flush()
        tasks = [
            Task(org_id=w.org_a.id, device_id=w.dev_a.id, script_id=w.script.id,
                batch_id=batch.id, status=status, timeout_seconds=60, created_at=created,
                started_at=started)
            for status, created, started in [
                (TaskStatus.RUNNING, now - timedelta(hours=2), now - timedelta(minutes=10)),
                (TaskStatus.QUEUED, now - timedelta(hours=2), None),
                (TaskStatus.RUNNING, now, now),
            ]
        ]
        db.add_all(tasks)
        await db.commit()
        expired, queued = await _process_stale_tasks(db, stale_buffer_seconds=300, queued_stale_minutes=60, org_id=w.org_a.id)
        assert (str(tasks[0].id), str(w.dev_a.id)) in expired
        assert (str(tasks[1].id), str(w.dev_a.id), str(w.org_a.id)) in queued
        await db.commit()
        assert tasks[0].status == TaskStatus.RUNNING and tasks[0].cancel_requested_at is not None
        assert tasks[0].timeout_requested_at is not None and tasks[0].finished_at is None
        assert tasks[1].status == TaskStatus.TIMEOUT
        assert tasks[2].status == TaskStatus.RUNNING
        assert batch.failed == 1
        assert batch.status != TaskBatchStatus.FAILED
        await _process_stale_tasks(db, stale_buffer_seconds=300, queued_stale_minutes=60, org_id=w.org_a.id)
        await db.commit()
        assert batch.failed == 1


async def test_watchdog_rollback_preserves_task_for_retry(world):
    w = world
    async with w.sessions() as db:
        await bind_tenant_context(db, str(w.org_a.id))
        task = Task(org_id=w.org_a.id, device_id=w.dev_a.id, script_id=w.script.id,
            status=TaskStatus.ASSIGNED, created_at=datetime.now(timezone.utc) - timedelta(hours=2))
        db.add(task)
        await db.commit()
        task_id = task.id
        await _process_stale_tasks(db, stale_buffer_seconds=300, queued_stale_minutes=60, org_id=w.org_a.id)
        await db.rollback()
        task = await db.get(Task, task_id)
        assert task.status == TaskStatus.ASSIGNED
        assert task.finished_at is None
        await _process_stale_tasks(db, stale_buffer_seconds=300, queued_stale_minutes=60, org_id=w.org_a.id)
        await db.commit()
        assert task.status == TaskStatus.ASSIGNED and task.timeout_requested_at is not None
        assert task.cancel_requested_at is not None and task.finished_at is None


@pytest.mark.parametrize("failure", ["postgres_commit", "redis_unavailable"])
async def test_watchdog_stop_intent_commits_without_redis_effects(world, failure):
    w = world
    async with w.sessions() as db:
        task = Task(org_id=w.org_a.id, device_id=w.dev_a.id, script_id=w.script.id,
            status=TaskStatus.RUNNING, timeout_seconds=60,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10))
        db.add(task)
        await db.commit()

    @asynccontextmanager
    async def commit_failure():
        async with w.sessions() as db:
            with patch.object(db, "commit", AsyncMock(side_effect=ConnectionError("isolated commit failure"))):
                yield db

    queue, publisher = AsyncMock(), AsyncMock()
    with (
        patch("backend.tasks.task_heartbeat_watchdog.AsyncSessionLocal",
            commit_failure if failure == "postgres_commit" else w.sessions),
        patch("backend.tasks.task_heartbeat_watchdog._discover_stale_tasks", AsyncMock(return_value=[(task.id, task.org_id)])),
        patch("backend.database.redis_client.redis_binary", None),
        patch("backend.services.task_queue.TaskQueue", return_value=queue),
        patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher),
    ):
        await _expire_stale_tasks()
    async with w.sessions() as db:
        persisted = await db.get(Task, task.id)
        if failure == "postgres_commit":
            assert persisted.status == TaskStatus.RUNNING
            assert persisted.finished_at is None
            queue.mark_completed.assert_not_awaited()
            queue.cancel_task.assert_not_awaited()
            publisher.send_command_live.assert_not_awaited()
        else:
            assert persisted.status == TaskStatus.RUNNING and persisted.finished_at is None
            assert persisted.cancel_requested_at is not None and persisted.timeout_requested_at is not None
        queue.mark_completed.assert_not_awaited()
        queue.cancel_task.assert_not_awaited()
        publisher.send_command_live.assert_not_awaited()
