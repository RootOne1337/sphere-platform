# tests/test_scripts/test_task_queue.py
# SPLIT-3 критерии готовности: очередь задач, приоритеты, атомарность.
from __future__ import annotations

import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from backend.services.task_queue import TaskQueue


@pytest_asyncio.fixture
async def task_queue(mock_redis: FakeRedis) -> TaskQueue:
    return TaskQueue(mock_redis)


class TestTaskQueuePriority:
    async def test_high_priority_dequeues_first(self, task_queue: TaskQueue):
        """priority=1 (высокий) выполняется раньше priority=10 (низкий)."""
        await task_queue.enqueue("low_task", "device-1", "org-1", priority=10)
        # Небольшая пауза чтобы timestamp различался (score determinism)
        import asyncio
        await asyncio.sleep(0.01)
        await task_queue.enqueue("high_task", "device-2", "org-1", priority=1)

        # Dequeue через разные устройства (нет blocking per device)
        result1 = await task_queue.dequeue_for_device("device-2", "org-1")
        result2 = await task_queue.dequeue_for_device("device-1", "org-1")

        assert result1 == "high_task"
        assert result2 == "low_task"


class TestTaskQueueConcurrencyLimit:
    async def test_single_device_one_task_at_a_time(self, task_queue: TaskQueue):
        """Одно устройство: не более 1 задачи одновременно."""
        await task_queue.enqueue("task-1", "device-A", "org-1", priority=5)
        await task_queue.enqueue("task-2", "device-A", "org-1", priority=5)

        first = await task_queue.dequeue_for_device("device-A", "org-1")
        assert first is not None

        # Второй dequeue для того же устройства — None (занято)
        second = await task_queue.dequeue_for_device("device-A", "org-1")
        assert second is None

    async def test_two_devices_process_in_parallel(self, task_queue: TaskQueue):
        """Два устройства обрабатывают задачи параллельно."""
        await task_queue.enqueue("task-A", "device-1", "org-1")
        await task_queue.enqueue("task-B", "device-2", "org-1")

        result_a = await task_queue.dequeue_for_device("device-1", "org-1")
        result_b = await task_queue.dequeue_for_device("device-2", "org-1")

        assert result_a == "task-A"
        assert result_b == "task-B"


class TestTaskQueueCancel:
    async def test_cancel_pending_task_removes_from_queue(self, task_queue: TaskQueue):
        """Cancel до начала выполнения удаляет задачу из очереди."""
        await task_queue.enqueue("cancel-me", "device-1", "org-1")
        removed = await task_queue.cancel_task("cancel-me", "org-1")
        assert removed is True

        # Теперь очередь пуста
        result = await task_queue.dequeue_for_device("device-1", "org-1")
        assert result is None

    async def test_cancel_nonexistent_task_returns_false(self, task_queue: TaskQueue):
        removed = await task_queue.cancel_task("ghost-task", "org-1")
        assert removed is False


class TestTaskQueueMarkCompleted:
    async def test_mark_completed_releases_device(self, task_queue: TaskQueue):
        """После mark_completed устройство свободно для новой задачи."""
        await task_queue.enqueue("task-1", "device-X", "org-1")
        dequeued = await task_queue.dequeue_for_device("device-X", "org-1")
        assert dequeued == "task-1"

        # Устройство занято
        assert await task_queue.is_device_busy("device-X") is True

        # Освободить
        await task_queue.mark_completed("task-1", "device-X")

        # Теперь свободно
        assert await task_queue.is_device_busy("device-X") is False

    async def test_queue_depth(self, task_queue: TaskQueue):
        """get_queue_depth возвращает корректное количество задач."""
        assert await task_queue.get_queue_depth("org-test") == 0
        await task_queue.enqueue("t1", "d1", "org-test")
        await task_queue.enqueue("t2", "d2", "org-test")
        assert await task_queue.get_queue_depth("org-test") == 2
