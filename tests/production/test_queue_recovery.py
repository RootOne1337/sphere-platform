"""Runtime invariants on disposable PostgreSQL and Redis (opt-in)."""

import asyncio
from unittest.mock import patch

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from backend.models.task import Task
from backend.services.task_queue import TaskQueue
from backend.services.task_service import TaskService


async def test_single_device_queue_is_atomic(world):
    w = world
    queue = TaskQueue(w.redis)
    device, org = str(w.dev_a.id), str(w.org_a.id)
    await queue.enqueue("one", device, org)
    await queue.enqueue("two", device, org)
    gate = asyncio.Event()
    reads = 0
    real_get = w.redis.get

    async def synchronized_get(key):
        nonlocal reads
        result = await real_get(key)
        reads += 1
        if reads == 2:
            gate.set()
        await gate.wait()
        return result

    with patch.object(w.redis, "get", side_effect=synchronized_get):
        results = await asyncio.wait_for(
            asyncio.gather(
                queue.dequeue_for_device(device, org), queue.dequeue_for_device(device, org)
            ),
            timeout=3,
        )
    assert sum(value is not None for value in results) == 1
    assert await queue.get_queue_depth(org, device) == 1


async def test_old_result_does_not_release_new_lease(world):
    queue = TaskQueue(world.redis)
    device = str(world.dev_a.id)
    await world.redis.set(queue.RUNNING_KEY.format(device_id=device), "new-task")
    await queue.mark_completed("old-task", device)
    assert await world.redis.get(queue.RUNNING_KEY.format(device_id=device)) == "new-task"


@pytest.mark.xfail(strict=True, reason="AUD-09 open: Redis publication occurs before PostgreSQL commit")
async def test_rollback_never_publishes_task(world):
    w = world
    queue = TaskQueue(w.redis)
    async with w.sessions() as db:
        task = await TaskService(db, queue).create_task(w.script.id, w.dev_a.id, w.org_a.id)
        task_id = task.id
        await db.rollback()
    assert await queue.dequeue_for_device(str(w.dev_a.id), str(w.org_a.id)) is None
    async with w.sessions() as db:
        assert await db.get(Task, task_id) is None


async def test_ambiguous_redis_timeout_never_pops_a_second_task(world):
    queue = TaskQueue(world.redis)
    device, org = str(world.dev_a.id), str(world.org_a.id)
    await queue.enqueue("first", device, org)
    await queue.enqueue("second", device, org)
    real_eval = world.redis.eval

    async def executed_but_response_lost(*args):
        await real_eval(*args)
        raise RedisTimeoutError("isolated lost Redis response")

    with patch.object(world.redis, "eval", side_effect=executed_but_response_lost):
        with pytest.raises(RedisTimeoutError):
            await queue.dequeue_for_device(device, org)
    assert await queue.get_queue_depth(org, device) == 1
    assert await world.redis.get(queue.RUNNING_KEY.format(device_id=device)) == "first"
