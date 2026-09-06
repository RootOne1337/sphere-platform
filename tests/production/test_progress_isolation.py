"""Live task data must obey the same ownership rules as durable task results."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.ws.android.router import handle_task_progress
from backend.database.redis_client import get_redis
from backend.main import app
from backend.models.task import Task, TaskStatus


@pytest.fixture
def progress_dependencies(world):
    publisher = AsyncMock()

    async def redis_dependency():
        return world.redis

    app.dependency_overrides[get_redis] = redis_dependency
    with (
        patch("backend.api.ws.android.router.AsyncSessionLocal", world.sessions),
        patch("backend.database.redis_client.redis", world.redis),
        patch("backend.websocket.event_publisher.get_event_publisher", return_value=publisher),
    ):
        yield publisher


async def task_for(world, status=TaskStatus.RUNNING):
    async with world.sessions() as db:
        task = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
            script_id=world.script.id, status=status)
        db.add(task)
        await db.commit()
    return task


@pytest.mark.parametrize("endpoint", ["progress", "live-logs"])
async def test_live_data_cannot_be_read_by_another_tenant(world, progress_dependencies, endpoint):
    w = world
    task = await task_for(w)
    await w.redis.hset(f"task_progress:{task.id}", mapping={"current_node": "private-node"})
    await w.redis.rpush(f"task_progress_log:{task.id}", json.dumps({"node_id": "private-node"}))
    response = await w.client.get(f"/api/v1/tasks/{task.id}/{endpoint}", headers=w.auth(w.users["foreign"]))
    assert response.status_code == 404, response.text
    assert "private-node" not in response.text
    own = await w.client.get(f"/api/v1/tasks/{task.id}/{endpoint}", headers=w.auth(w.users["viewer"]))
    assert own.status_code == 200, own.text
    assert "private-node" in own.text


@pytest.mark.parametrize("source", ["other_device", "other_org", "unknown_task", "terminal_task"])
async def test_progress_cannot_poison_unowned_or_terminal_task(world, progress_dependencies, source):
    w = world
    task = await task_for(w, TaskStatus.COMPLETED if source == "terminal_task" else TaskStatus.RUNNING)
    task_id = str(uuid.uuid4()) if source == "unknown_task" else str(task.id)
    device = w.dev_a2 if source == "other_device" else w.dev_a
    org = w.org_b if source == "other_org" else w.org_a
    await handle_task_progress(str(device.id), str(org.id), {
        "task_id": task_id, "nodes_done": 1, "total_nodes": 2, "current_node": "forged",
    })
    assert not await w.redis.exists(f"task_progress:{task_id}")
    assert not await w.redis.exists(f"task_progress_log:{task_id}")
    progress_dependencies.task_progress.assert_not_awaited()


@pytest.mark.parametrize("invalid", [
    {"task_id": "not-a-uuid"}, {"nodes_done": "one"}, {"nodes_done": -1},
    {"nodes_done": True}, {"total_nodes": 0}, {"current_node": {"bad": "type"}},
])
async def test_malformed_progress_does_not_disconnect_agent(world, progress_dependencies, invalid):
    w = world
    task = await task_for(w)
    msg = {"task_id": str(task.id), "nodes_done": 1, "total_nodes": 2, "current_node": "node"} | invalid
    await handle_task_progress(str(w.dev_a.id), str(w.org_a.id), msg)
    assert not await w.redis.exists(f"task_progress:{task.id}")
    progress_dependencies.task_progress.assert_not_awaited()


async def test_owned_progress_is_cached_and_published(world, progress_dependencies):
    w = world
    task = await task_for(w)
    await handle_task_progress(str(w.dev_a.id), str(w.org_a.id), {
        "task_id": str(task.id), "nodes_done": 3, "total_nodes": 2, "current_node": "node",
    })
    cached = await w.redis.hgetall(f"task_progress:{task.id}")
    assert cached["progress"] == "100"
    assert cached["cycles"] == "1"
    assert await w.redis.llen(f"task_progress_log:{task.id}") == 1
    assert 0 < await w.redis.ttl(f"task_progress:{task.id}") <= 600
    progress_dependencies.task_progress.assert_awaited_once_with(
        device_id=str(w.dev_a.id), org_id=str(w.org_a.id), task_id=str(task.id), progress=100,
    )
