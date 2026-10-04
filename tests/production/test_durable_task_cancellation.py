"""Cancellation is persisted intent; only a terminal device receipt ends execution."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from backend.models.task import Task, TaskStatus
from backend.services.task_service import TaskService


async def seed(world, status=TaskStatus.RUNNING):
    async with world.sessions() as db:
        task = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                    script_id=world.script.id, script_version_id=world.version.id, status=status)
        db.add(task)
        await db.commit()
    return task


@pytest.mark.parametrize("status", [TaskStatus.RUNNING, TaskStatus.ASSIGNED])
async def test_stop_commits_intent_without_publishing_or_releasing_execution(world, status):
    task = await seed(world, status)
    queue, publisher = AsyncMock(), AsyncMock()
    publisher.send_command_live.return_value = True
    async with world.sessions() as db:
        await TaskService(db, queue, publisher=publisher).force_stop_task(task.id, world.org_a.id)
        await db.commit()
    async with world.sessions() as db:
        stored = await db.get(Task, task.id)
        assert stored.status == status, "Publication/SQL request is not a physical stop receipt"
        assert getattr(stored, "cancel_requested_at", None) is not None
        assert stored.finished_at is None
    queue.mark_completed.assert_not_awaited()
    queue.cancel_task.assert_not_awaited()
    publisher.send_command_live.assert_not_awaited()


async def test_offline_stop_is_durable_and_repeated_requests_keep_identity(world):
    task = await seed(world)
    async with world.sessions() as db:
        service = TaskService(db)
        first = await service.force_stop_task(task.id, world.org_a.id)
        requested = getattr(first, "cancel_requested_at", None)
        await db.commit()
        second = await service.force_stop_task(task.id, world.org_a.id)
        await db.commit()
        assert requested is not None and second.cancel_requested_at == requested
        assert second.status == TaskStatus.RUNNING


async def test_rollback_never_publishes_cancellation(world):
    task = await seed(world)
    publisher = AsyncMock()
    publisher.send_command_live.return_value = True
    async with world.sessions() as db:
        await TaskService(db, AsyncMock(), publisher=publisher).force_stop_task(task.id, world.org_a.id)
        await db.rollback()
    publisher.send_command_live.assert_not_awaited()
    async with world.sessions() as db:
        stored = await db.get(Task, task.id)
        assert getattr(stored, "cancel_requested_at", None) is None
        assert stored.status == TaskStatus.RUNNING


async def test_cancellation_receipt_finishes_with_cancelled_not_failed(world):
    task = await seed(world)
    async with world.sessions() as db:
        accepted = await TaskService(db, AsyncMock()).handle_task_result(
            str(task.id), str(task.device_id),
            {"success": False, "cancelled": True, "error": "cancelled_by_user"}, str(world.org_a.id),
        )
        await db.commit()
        assert accepted
        assert (await db.get(Task, task.id)).status == TaskStatus.CANCELLED


async def test_fresh_worker_retries_committed_intent_with_same_target_after_failed_delivery(world):
    task = await seed(world)
    publisher = AsyncMock()
    publisher.send_command_live.return_value = False
    async with world.sessions() as db:
        await TaskService(db).force_stop_task(task.id, world.org_a.id)
        await db.commit()
    for attempt in range(2):
        async with world.sessions() as db:
            # Real restart boundary: a new service and session, only persisted state.
            await TaskService(db, publisher=publisher).dispatch_pending_cancellations(org_id=world.org_a.id)
            current = await db.get(Task, task.id)
            assert current.status == TaskStatus.RUNNING
            assert current.cancel_last_sent_at is not None
            current.cancel_last_sent_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            await db.commit()
    relevant = [c.args[1] for c in publisher.send_command_live.await_args_list if c.args[0] == str(task.device_id)]
    assert len(relevant) == 2
    assert {c["command_id"] for c in relevant} == {f"user_cancel_{task.id}"}
    assert all(c["payload"] == {"task_id": str(task.id), "durable": True} for c in relevant)


@pytest.mark.parametrize("error", ["execution_outcome_unknown_after_restart",
                                  "execution_interrupted_outcome_unknown",
                                  "Root command delivery outcome is unknown"])
async def test_pending_cancel_does_not_turn_unknown_device_outcome_into_stop_confirmation(world, error):
    task = await seed(world)
    queue = AsyncMock()
    async with world.sessions() as db:
        service = TaskService(db, queue)
        await service.force_stop_task(task.id, world.org_a.id)
        await db.commit()
        accepted = await service.handle_task_result(str(task.id), str(task.device_id),
            {"success": False, "error": error}, str(world.org_a.id))
        await db.commit()
        current = await db.get(Task, task.id)
        assert not accepted, "Retain the unacknowledged APK receipt for reconciliation"
        assert current.status == TaskStatus.RUNNING
        assert current.finished_at is None
        assert current.result["error"] == error
    queue.mark_completed.assert_not_awaited()


async def test_successful_task_result_can_win_the_cancellation_race(world):
    task = await seed(world)
    async with world.sessions() as db:
        service = TaskService(db, AsyncMock())
        await service.force_stop_task(task.id, world.org_a.id)
        await db.commit()
        await service.handle_task_result(str(task.id), str(task.device_id),
                                        {"success": True, "output": "outcome_unknown is ordinary script output"}, str(world.org_a.id))
        await db.commit()
        assert (await db.get(Task, task.id)).status == TaskStatus.COMPLETED


@pytest.mark.parametrize("status", [TaskStatus.ASSIGNED, TaskStatus.RUNNING])
async def test_pending_cancel_blocks_later_work_and_watchdog_timeout(world, status):
    from types import SimpleNamespace

    from backend.tasks.task_heartbeat_watchdog import _process_stale_tasks

    task = await seed(world, status)
    later = await seed(world, TaskStatus.QUEUED)
    publisher, cache = AsyncMock(), AsyncMock()
    cache.bulk_get_status.side_effect = lambda ids: {
        value: SimpleNamespace(status="online") for value in ids if value == str(task.device_id)
    }
    async with world.sessions() as db:
        await TaskService(db).force_stop_task(task.id, world.org_a.id)
        current = await db.get(Task, task.id)
        current.started_at = current.created_at = current.updated_at = datetime.now(timezone.utc) - timedelta(days=2)
        await db.commit()
        await TaskService(db, AsyncMock(), cache, publisher).dispatch_pending_tasks(org_id=world.org_a.id)
        assert (await db.get(Task, later.id)).status == TaskStatus.QUEUED
        assert not any(c.args[1]["type"] == "EXECUTE_DAG" for c in publisher.send_command_live.await_args_list)
        running, queued = await _process_stale_tasks(db, stale_buffer_seconds=0, queued_stale_minutes=60)
        assert not any(row[0] == str(task.id) for row in running + queued)
        assert (await db.get(Task, task.id)).status == status
        await db.rollback()  # Watchdog can observe other isolated fixture tenants.
