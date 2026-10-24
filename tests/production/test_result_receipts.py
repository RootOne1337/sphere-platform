"""A device may discard its outbox result only after a durable server receipt."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from backend.api.ws.android.router import handle_agent_message
from backend.models.task import Task, TaskStatus


@pytest.fixture(autouse=True)
def isolated_handler_dependencies(world):
    with (patch("backend.database.engine.AsyncSessionLocal", world.sessions),
          patch("backend.database.redis_client.redis", world.redis)):
        yield


async def test_result_ack_is_sent_after_postgres_commit_even_if_redis_fails(world):
    w = world
    async with w.sessions() as db:
        task = Task(org_id=w.org_a.id, device_id=w.dev_a.id,
                    script_id=w.script.id, status=TaskStatus.RUNNING)
        db.add(task)
        await db.commit()
    manager = AsyncMock()

    async def confirm_persisted(device_id, message):
        assert device_id == str(w.dev_a.id)
        assert message == {"type": "result_ack", "command_id": str(task.id)}
        async with w.sessions() as db:
            persisted = await db.scalar(select(Task).where(Task.id == task.id))
            assert persisted.status == TaskStatus.FAILED
            assert persisted.result["success"] is False
        return True

    manager.send_to_device.side_effect = confirm_persisted
    message = {"type": "command_result", "command_id": str(task.id),
               "status": "failed", "result": {"success": False}}
    with (patch.object(w.redis, "publish", AsyncMock(side_effect=ConnectionError("isolated Redis outage"))),
          patch.object(w.redis, "get", AsyncMock(side_effect=ConnectionError("isolated Redis outage"))),
          patch.object(w.redis, "eval", AsyncMock(side_effect=ConnectionError("isolated Redis outage")))):
        await handle_agent_message(str(w.dev_a.id), str(w.org_a.id), message, manager, AsyncMock())
        await handle_agent_message(str(w.dev_a.id), str(w.org_a.id), message, manager, AsyncMock())
    assert manager.send_to_device.await_count == 2


async def test_foreign_task_result_gets_no_durable_receipt(world):
    w = world
    async with w.sessions() as db:
        task = Task(org_id=w.org_b.id, device_id=w.dev_b.id,
                    script_id=w.script.id, status=TaskStatus.RUNNING)
        db.add(task)
        await db.commit()
    manager = AsyncMock()
    await handle_agent_message(str(w.dev_a.id), str(w.org_a.id),
        {"type": "command_result", "command_id": str(task.id), "status": "completed"},
        manager, AsyncMock())
    manager.send_to_device.assert_not_awaited()


async def test_failed_postgres_commit_gets_no_durable_receipt(world):
    w = world
    async with w.sessions() as db:
        task = Task(org_id=w.org_a.id, device_id=w.dev_a.id,
                    script_id=w.script.id, status=TaskStatus.RUNNING)
        db.add(task)
        await db.commit()

    @asynccontextmanager
    async def failing_commit_session():
        async with w.sessions() as db:
            with patch.object(db, "commit", AsyncMock(side_effect=ConnectionError("isolated commit failure"))):
                yield db

    manager = AsyncMock()
    with patch("backend.database.engine.AsyncSessionLocal", failing_commit_session):
        await handle_agent_message(str(w.dev_a.id), str(w.org_a.id),
            {"type": "command_result", "command_id": str(task.id), "status": "completed"},
            manager, AsyncMock())
    manager.send_to_device.assert_not_awaited()
    async with w.sessions() as db:
        persisted = await db.get(Task, task.id)
        assert persisted.status == TaskStatus.RUNNING
