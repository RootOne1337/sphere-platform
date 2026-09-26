"""An unavailable stop transport must not release a still-running task."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends

from backend.api.v1.tasks.router import get_task_service
from backend.database.engine import get_db
from backend.main import app
from backend.models.task import Task, TaskStatus
from backend.services.task_queue import TaskQueue
from backend.services.task_service import TaskService
from backend.websocket.pubsub_router import PubSubPublisher


async def seed(world):
    async with world.sessions() as db:
        task = Task(
            org_id=world.org_a.id, device_id=world.dev_a.id,
            script_id=world.script.id, script_version_id=world.version.id,
            status=TaskStatus.RUNNING,
        )
        db.add(task)
        await db.commit()
    key = TaskQueue.RUNNING_KEY.format(device_id=task.device_id)
    await world.redis.set(key, str(task.id), ex=60)
    return task, key


async def assert_preserved(world, task, key):
    async with world.sessions() as db:
        stored = await db.get(Task, task.id)
        assert stored.status == TaskStatus.RUNNING
        assert stored.finished_at is None
        assert stored.error_message is None
        assert stored.result is None
    assert await world.redis.get(key) == str(task.id)


async def test_stop_api_retains_durable_intent_with_real_redis_zero_subscribers(world):
    task, key = await seed(world)

    async def service(db=Depends(get_db)):
        return TaskService(db, TaskQueue(world.redis), publisher=PubSubPublisher(world.redis))

    app.dependency_overrides[get_task_service] = service
    try:
        response = await world.client.post(
            f"/api/v1/tasks/{task.id}/stop", headers=world.auth(world.users["org_admin"]),
        )
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "cancelling"
        async with world.sessions() as db:
            assert (await db.get(Task, task.id)).cancel_requested_at is not None
            await TaskService(db, publisher=PubSubPublisher(world.redis)).dispatch_pending_cancellations(org_id=world.org_a.id)
        await assert_preserved(world, task, key)
    finally:
        app.dependency_overrides.pop(get_task_service, None)
        await world.redis.delete(key)


@pytest.mark.parametrize("outcome", [False, None, "true", "missing", "exception", "timeout"])
async def test_unconfirmed_stop_retains_sql_and_device_lock(world, outcome, monkeypatch):
    task, key = await seed(world)
    send = AsyncMock(return_value=outcome)
    publisher = SimpleNamespace(send_command_live=send)
    if outcome == "missing":
        publisher = None
    elif outcome == "exception":
        send.side_effect = ConnectionError("private transport details must not reach HTTP")
    elif outcome == "timeout":
        async def block(*args):
            await asyncio.Event().wait()
        send.side_effect = block
        # Outer wait is also bounded on the unfixed source, where this setting
        # does not exist and the transport wait otherwise never ends.
        monkeypatch.setattr("backend.services.task_service._STOP_PUBLISH_TIMEOUT_SECONDS", .02, raising=False)
    try:
        async with world.sessions() as db:
            service = TaskService(db, TaskQueue(world.redis), publisher=publisher)
            await service.force_stop_task(task.id, world.org_a.id)
            await db.commit()
            await asyncio.wait_for(service.dispatch_pending_cancellations(org_id=world.org_a.id), 1)
        await assert_preserved(world, task, key)
        assert send.await_count == (0 if publisher is None else 1), "No automatic mutation retries"
    finally:
        await world.redis.delete(key)


async def test_genuine_completion_is_still_accepted_after_rejected_stop(world):
    task, key = await seed(world)
    try:
        async with world.sessions() as db:
            service = TaskService(db, TaskQueue(world.redis), publisher=PubSubPublisher(world.redis))
            await service.force_stop_task(task.id, world.org_a.id)
            await db.commit()
            await service.dispatch_pending_cancellations(org_id=world.org_a.id)
        async with world.sessions() as db:
            accepted = await TaskService(db, TaskQueue(world.redis)).handle_task_result(
                str(task.id), str(task.device_id), {"success": True, "result": "finished on device"},
                str(world.org_a.id),
            )
            await db.commit()
            assert accepted
        async with world.sessions() as db:
            stored = await db.get(Task, task.id)
            assert stored.status == TaskStatus.COMPLETED
            assert stored.result["result"] == "finished on device"
        assert await world.redis.get(key) is None
    finally:
        await world.redis.delete(key)


async def test_request_cancellation_does_not_report_success_or_retry_publish(world):
    task, key = await seed(world)
    entered = asyncio.Event()

    async def publish(*args):
        entered.set()
        await asyncio.Event().wait()

    send = AsyncMock(side_effect=publish)
    try:
        async with world.sessions() as db:
            await TaskService(db).force_stop_task(task.id, world.org_a.id)
            await db.commit()
            pending = asyncio.create_task(TaskService(
                db, TaskQueue(world.redis), publisher=SimpleNamespace(send_command_live=send),
            ).dispatch_pending_cancellations(org_id=world.org_a.id))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
                await db.rollback()
            finally:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        await assert_preserved(world, task, key)
        assert send.await_count == 1
    finally:
        await world.redis.delete(key)
