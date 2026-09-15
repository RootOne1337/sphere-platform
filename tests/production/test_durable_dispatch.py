"""PostgreSQL owns task intent; network delivery may be retried with the same ID."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.models.task import Task, TaskStatus
from backend.services.task_queue import TaskQueue
from backend.services.task_service import TaskService


def online_cache(world):
    cache = AsyncMock()
    cache.get_all_tracked_device_ids.return_value = [str(world.dev_a.id)]
    cache.get_status.side_effect = lambda device_id: SimpleNamespace(status="online") if device_id == str(world.dev_a.id) else None
    cache.bulk_get_status.side_effect = lambda ids: {
        device_id: SimpleNamespace(status="online") if device_id == str(world.dev_a.id) else None for device_id in ids
    }
    return cache


async def committed_task(world):
    async with world.sessions() as db:
        task = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                    script_id=world.script.id, script_version_id=world.version.id)
        db.add(task)
        await db.commit()
        return task


async def dispatch(world, publisher):
    async with world.sessions() as db:
        await TaskService(db, TaskQueue(world.redis), online_cache(world), publisher).dispatch_pending_tasks()
        await db.commit()


async def test_committed_task_is_deliverable_without_any_redis_queue_entry(world):
    task = await committed_task(world)
    publisher = AsyncMock()
    publisher.send_command_live.return_value = True
    await dispatch(world, publisher)
    publisher.send_command_live.assert_awaited_once()
    assert publisher.send_command_live.call_args.args[1]["command_id"] == str(task.id)


async def test_assignment_is_committed_before_network_delivery(world):
    task = await committed_task(world)
    # Keep the legacy Redis path populated so the old dispatcher reaches send.
    await TaskQueue(world.redis).enqueue(str(task.id), str(world.dev_a.id), str(world.org_a.id))
    observed = []

    async def observe(*_args):
        async with world.sessions() as db:
            observed.append((await db.get(Task, task.id)).status)
        return True

    publisher = AsyncMock()
    publisher.send_command_live.side_effect = observe
    await dispatch(world, publisher)
    assert observed == [TaskStatus.ASSIGNED]


async def test_concurrent_dispatchers_send_one_assignment(world):
    task = await committed_task(world)
    await TaskQueue(world.redis).enqueue(str(task.id), str(world.dev_a.id), str(world.org_a.id))
    publisher = AsyncMock()
    publisher.send_command_live.return_value = True
    await asyncio.gather(dispatch(world, publisher), dispatch(world, publisher))
    publisher.send_command_live.assert_awaited_once()


async def test_lost_delivery_response_retries_same_committed_assignment(world):
    task = await committed_task(world)
    await TaskQueue(world.redis).enqueue(str(task.id), str(world.dev_a.id), str(world.org_a.id))
    publisher = AsyncMock()
    publisher.send_command_live.side_effect = ConnectionError("isolated lost transport response")
    await dispatch(world, publisher)
    async with world.sessions() as db:
        persisted = await db.get(Task, task.id)
        persisted.updated_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    publisher.send_command_live.side_effect = None
    publisher.send_command_live.return_value = True
    await dispatch(world, publisher)
    assert publisher.send_command_live.await_count == 2
    assert {call.args[1]["command_id"] for call in publisher.send_command_live.call_args_list} == {str(task.id)}


async def test_active_db_task_blocks_another_task_even_without_redis_lease(world):
    first = await committed_task(world)
    async with world.sessions() as db:
        persisted = await db.get(Task, first.id)
        persisted.status = TaskStatus.RUNNING
        await db.commit()
    second = await committed_task(world)
    await TaskQueue(world.redis).enqueue(str(second.id), str(world.dev_a.id), str(world.org_a.id))
    publisher = AsyncMock()
    publisher.send_command_live.return_value = True
    await dispatch(world, publisher)
    publisher.send_command_live.assert_not_awaited()


async def test_agent_receipt_starts_task_and_stops_assignment_retries(world):
    from backend.api.ws.android.router import handle_agent_message

    task = await committed_task(world)
    publisher = AsyncMock()
    publisher.send_command_live.return_value = True
    await dispatch(world, publisher)
    with (patch("backend.database.engine.AsyncSessionLocal", world.sessions),
          patch("backend.database.redis_client.redis", world.redis)):
        await handle_agent_message(str(world.dev_a.id), str(world.org_a.id),
            {"type": "command_result", "command_id": str(task.id), "status": "received"},
            AsyncMock(), AsyncMock())
    async with world.sessions() as db:
        persisted = await db.get(Task, task.id)
        assert persisted.status == TaskStatus.RUNNING
        assert persisted.started_at is not None
        persisted.updated_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    await dispatch(world, publisher)
    publisher.send_command_live.assert_awaited_once()


async def test_fast_terminal_result_cannot_be_overwritten_by_dispatcher(world):
    from backend.api.ws.android.router import handle_agent_message

    task = await committed_task(world)
    publisher = AsyncMock()

    async def completed_immediately(device_id, command):
        with (patch("backend.database.engine.AsyncSessionLocal", world.sessions),
              patch("backend.database.redis_client.redis", world.redis)):
            await handle_agent_message(device_id, str(world.org_a.id),
                {"type": "command_result", "command_id": command["command_id"],
                 "status": "completed", "result": {"success": True}}, AsyncMock(), AsyncMock())
        return True

    publisher.send_command_live.side_effect = completed_immediately
    await asyncio.wait_for(dispatch(world, publisher), 3)
    async with world.sessions() as db:
        assert (await db.get(Task, task.id)).status == TaskStatus.COMPLETED
