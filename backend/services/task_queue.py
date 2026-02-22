# backend/services/task_queue.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-3. Приоритетная очередь задач на Redis Sorted Set.
#
# Алгоритм приоритетов:
#   score = priority * 1e12 + timestamp
#   Меньший score → раньше выполняется (ZPOPMIN берёт наименьший).
#   priority=1 (высокий) → score ~1e12  (наименьший → первым)
#   priority=10 (низкий) → score ~10e12 (наибольший → последним)
#
# Atomic dequeue: Lua скрипт гарантирует атомарность ZPOPMIN + SET running lock.
# Одно устройство — максимум 1 задача одновременно (RUNNING_KEY mutex с TTL).
from __future__ import annotations

import time

import structlog

logger = structlog.get_logger()

# Lua-скрипт для атомарной операции: pop из ZSet + установить running-lock
_LUA_DEQUEUE = """
local task_id = redis.call('ZPOPMIN', KEYS[1], 1)
if #task_id == 0 then return nil end
local tid = task_id[1]
redis.call('SET', KEYS[2], tid, 'EX', 3600)
return tid
"""


class TaskQueue:
    """
    Приоритетная очередь задач на Redis Sorted Set.

    Ключи:
        task_queue:{org_id}          — ZSet задач (score = приоритет)
        task_running:{device_id}     — Строка (ID текущей задачи, TTL=3600s)
        task:meta:{task_id}          — Hash метаданных задачи
    """

    QUEUE_KEY = "task_queue:{org_id}"
    RUNNING_KEY = "task_running:{device_id}"
    MAX_CONCURRENT_PER_DEVICE = 1

    def __init__(self, redis) -> None:
        self.redis = redis

    async def enqueue(
        self,
        task_id: str,
        device_id: str,
        org_id: str,
        priority: int = 5,
    ) -> None:
        """
        Добавить задачу в очередь.
        score = priority * 1e12 + timestamp.
        ZPOPMIN берёт наименьший score → priority=1 (высший) выполняется первым.
        """
        score = priority * 1_000_000_000_000 + time.time()
        queue_key = self.QUEUE_KEY.format(org_id=org_id)

        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.zadd(queue_key, {task_id: score})
            pipe.hset(
                f"task:meta:{task_id}",
                mapping={
                    "device_id": device_id,
                    "org_id": org_id,
                    "priority": priority,
                    "enqueued_at": str(time.time()),
                },
            )
            await pipe.execute()

        logger.debug("task.enqueued", task_id=task_id, device_id=device_id, priority=priority)

    async def dequeue_for_device(
        self, device_id: str, org_id: str
    ) -> str | None:
        """
        Atomic dequeue для устройства.
        Использует Lua eval для атомарности (ZPOPMIN + SET lock).
        Fallback на pessimistic pipeline при недоступности eval (тесты с fakeredis).
        Возвращает task_id или None если устройство занято / очередь пуста.
        """
        running_key = self.RUNNING_KEY.format(device_id=device_id)

        # Быстрая проверка — если устройство занято, не трогаем ZSet
        already_running = await self.redis.get(running_key)
        if already_running:
            return None

        queue_key = self.QUEUE_KEY.format(org_id=org_id)

        try:
            result = await self.redis.eval(_LUA_DEQUEUE, 2, queue_key, running_key)
        except Exception:
            # Fallback: не атомарно, но приемлемо для тестов и Redis без Lua
            result = await self._dequeue_fallback(queue_key, running_key)

        if result is None:
            return None

        task_id = result if isinstance(result, str) else result.decode()
        logger.debug("task.dequeued", task_id=task_id, device_id=device_id)
        return task_id

    async def _dequeue_fallback(
        self, queue_key: str, running_key: str
    ) -> str | None:
        """Non-atomic fallback dequeue (used in tests / non-Lua environments)."""
        results = await self.redis.zpopmin(queue_key, 1)
        if not results:
            return None
        task_id = results[0] if isinstance(results[0], str) else results[0][0]
        # Convert tuple from ZPOPMIN if needed
        if isinstance(task_id, (list, tuple)):
            task_id = task_id[0]
        await self.redis.set(running_key, task_id, ex=3600)
        return task_id

    async def mark_completed(self, task_id: str, device_id: str) -> None:
        """Освободить устройство после завершения задачи."""
        await self.redis.delete(self.RUNNING_KEY.format(device_id=device_id))
        await self.redis.delete(f"task:meta:{task_id}")
        logger.debug("task.device_released", task_id=task_id, device_id=device_id)

    async def cancel_task(self, task_id: str, org_id: str) -> bool:
        """
        Отменить задачу из очереди (до начала выполнения).
        Возвращает True если задача была в очереди и удалена.
        """
        queue_key = self.QUEUE_KEY.format(org_id=org_id)
        removed = await self.redis.zrem(queue_key, task_id)
        if removed:
            await self.redis.delete(f"task:meta:{task_id}")
        return bool(removed)

    async def get_queue_depth(self, org_id: str) -> int:
        """Количество задач в очереди для org."""
        return await self.redis.zcard(self.QUEUE_KEY.format(org_id=org_id))

    async def is_device_busy(self, device_id: str) -> bool:
        return bool(await self.redis.exists(self.RUNNING_KEY.format(device_id=device_id)))
