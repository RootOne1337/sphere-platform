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


@pytest.mark.parametrize("failure", ["redis_release", "sql_commit"])
async def test_stop_ack_cannot_complete_a_task_after_cancellation_rollback(world, failure):
    task = await seed_running_task(world)
    queue, publisher, manager = AsyncMock(), AsyncMock(), AsyncMock()
    if failure == "redis_release":
        queue.mark_completed.side_effect = ConnectionError("isolated Redis failure")
    async with world.sessions() as db:
        with pytest.raises(ConnectionError):
            await TaskService(db, queue, publisher=publisher).force_stop_task(task.id, world.org_a.id)
            with patch.object(db, "commit", AsyncMock(side_effect=ConnectionError("isolated SQL failure"))):
                await db.commit()
        await db.rollback()
    command = publisher.send_command_live.await_args.args[1]
    assert command["payload"]["task_id"] == str(task.id)
    # The APK acknowledged the control command, not execution of the DAG.
    ack = {"type": "command_ack", "command_id": command["command_id"], "status": "completed"}
    with patch("backend.database.engine.AsyncSessionLocal", world.sessions):
        await handle_command_result(str(task.device_id), str(world.org_a.id), ack, manager)
    async with world.sessions() as verify:
        stored = await verify.get(Task, task.id)
        assert stored.status == TaskStatus.RUNNING, "Stop ACK forged a successful DAG outcome after rollback"
        assert stored.result is None
    manager.send_to_device.assert_not_awaited()  # Must not acknowledge the DAG journal either.
    assert command["command_id"] != str(task.id)


async def test_watchdog_stop_names_the_expired_task_after_timeout_commit(world):
    task = await seed_running_task(world)
    queue, publisher = AsyncMock(), AsyncMock()
    with (
        patch("backend.tasks.task_heartbeat_watchdog.AsyncSessionLocal", world.sessions),
        patch("backend.database.redis_client.redis_binary", object()),
        patch("backend.services.task_queue.TaskQueue", return_value=queue),
        patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher),
    ):
        await _expire_stale_tasks()
    async with world.sessions() as verify:
        assert (await verify.get(Task, task.id)).status == TaskStatus.TIMEOUT
    sent = [call.args[1] for call in publisher.send_command_live.await_args_list
            if call.args[0] == str(task.device_id)]
    assert len(sent) == 1
    assert sent[0].get("payload") == {"task_id": str(task.id)}, "Watchdog emits an untargeted device stop"
    assert sent[0]["command_id"] != str(task.id)
