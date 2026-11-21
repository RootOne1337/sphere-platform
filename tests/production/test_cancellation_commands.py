"""Control receipts must never masquerade as task execution results."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.ws.android.router import handle_command_result
from backend.models.task import Task, TaskStatus
from backend.services.task_service import TaskService
from backend.tasks.task_heartbeat_watchdog import _expire_stale_tasks


async def seed_running_task(world):
    async with world.sessions() as db:
        task = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                    script_id=world.script.id, script_version_id=world.version.id,
                    status=TaskStatus.RUNNING, timeout_seconds=60,
                    started_at=datetime.now(timezone.utc) - timedelta(minutes=10))
        db.add(task)
        await db.commit()
    return task


@pytest.mark.parametrize("committed", [True, False])
async def test_stop_ack_cannot_complete_a_task_with_committed_or_rolled_back_intent(world, committed):
    task = await seed_running_task(world)
    queue, publisher, manager = AsyncMock(), AsyncMock(), AsyncMock()
    publisher.send_command_live.return_value = True
    async with world.sessions() as db:
        await TaskService(db, queue, publisher=publisher).force_stop_task(task.id, world.org_a.id)
        if committed:
            await db.commit()
            await TaskService(db, queue, publisher=publisher).dispatch_pending_cancellations(org_id=world.org_a.id)
            command = publisher.send_command_live.await_args.args[1]
            assert command["payload"]["task_id"] == str(task.id)
        else:
            await db.rollback()
            publisher.send_command_live.assert_not_awaited()
            command = {"command_id": f"user_cancel_{task.id}"}
    # The APK acknowledged the control command, not execution of the DAG.
    ack = {"type": "command_ack", "command_id": command["command_id"], "status": "completed"}
    with patch("backend.database.engine.AsyncSessionLocal", world.sessions):
        await handle_command_result(str(task.device_id), str(world.org_a.id), ack, manager)
    async with world.sessions() as verify:
        stored = await verify.get(Task, task.id)
        assert stored.status == TaskStatus.RUNNING, "Stop ACK forged a successful DAG outcome after rollback"
        assert stored.result is None
        assert (stored.cancel_requested_at is not None) == committed
    queue.mark_completed.assert_not_awaited()
    manager.send_to_device.assert_not_awaited()  # Must not acknowledge the DAG journal either.
    assert command["command_id"] != str(task.id)


async def test_watchdog_stop_names_the_overdue_task_after_intent_commit(world):
    task = await seed_running_task(world)
    queue, publisher = AsyncMock(), AsyncMock()
    with (
        patch("backend.tasks.task_heartbeat_watchdog.AsyncSessionLocal", world.sessions),
        patch("backend.tasks.task_heartbeat_watchdog._discover_stale_tasks", AsyncMock(return_value=[(task.id, task.org_id)])),
        patch("backend.database.redis_client.redis_binary", object()),
        patch("backend.services.task_queue.TaskQueue", return_value=queue),
        patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher),
    ):
        await _expire_stale_tasks()
    async with world.sessions() as verify:
        current = await verify.get(Task, task.id)
        assert current.status == TaskStatus.RUNNING and current.timeout_requested_at is not None
        publisher.send_command_live.assert_not_awaited()
        queue.mark_completed.assert_not_awaited()
        await TaskService(verify, publisher=publisher).dispatch_pending_cancellations(org_id=world.org_a.id)
    sent = [call.args[1] for call in publisher.send_command_live.await_args_list
            if call.args[0] == str(task.device_id)]
    assert len(sent) == 1
    assert sent[0].get("payload") == {"task_id": str(task.id), "durable": True}
    assert sent[0]["command_id"] != str(task.id)
