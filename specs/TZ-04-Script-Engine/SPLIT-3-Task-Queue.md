# SPLIT-3 — Task Queue (Очередь выполнения скриптов)

**ТЗ-родитель:** TZ-04-Script-Engine  
**Ветка:** `stage/4-scripts`  
**Задача:** `SPHERE-023`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-04 SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-07 Android Agent работает с собственным task handler; при merge подключить реальную очередь

---

## Цель Сплита

Приоритетная очередь задач на Redis. Ограничение параллельного выполнения на одном устройстве. Полный lifecycle задачи: pending → running → done/failed.

---

## Шаг 1 — Task Model

> ⚠️ **ВНИМАНИЕ АГЕНТУ: НЕ СОЗДАВАЙ КЛАССЫ МОДЕЛЕЙ!**
>
> Модели `TaskStatus` и `Task` **уже определены** в **TZ-00 SPLIT-2 Шаг 4** (файл `backend/models/task.py`).
> Дублирование класса вызовет `SAWarning: Table 'tasks' already exists` и конфликт при merge!
>
> **Используй только импорты:**
>
> ```python
> from backend.models.task import Task, TaskStatus
> from backend.models.script import Script, ScriptVersion
> from backend.models.task_batch import TaskBatch
> ```
>
> **Поля Task (справка):** `org_id`, `script_id`, `script_version_id`, `device_id`, `status` (TaskStatus),
> `priority`, `started_at`, `completed_at`, `current_node`, `progress`, `result`, `error_msg`, `logs`, `webhook_url`, `batch_id`
>
> ✅ **Твоя задача в этом сплите:** только `backend/services/task_queue.py` + `backend/services/task_service.py` + `backend/api/v1/tasks/router.py`

---

## Шаг 2 — Redis Task Queue

```python
# backend/services/task_queue.py
class TaskQueue:
    """
    Приоритетная очередь задач на основе Redis Sorted Set.
    Score = priority * 1e12 + timestamp (меньше = раньше)
    """
    
    QUEUE_KEY = "task_queue:{org_id}"
    RUNNING_KEY = "task_running:{device_id}"
    MAX_CONCURRENT_PER_DEVICE = 1  # Одна задача на устройство
    
    def __init__(self, redis):
        self.redis = redis
    
    async def enqueue(self, task_id: str, device_id: str, org_id: str, priority: int = 5):
        """Добавить задачу в очередь."""
        score = priority * 1e12 + time.time()
        queue_key = self.QUEUE_KEY.format(org_id=org_id)
        
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.zadd(queue_key, {task_id: score})
            pipe.hset(f"task:meta:{task_id}", mapping={
                "device_id": device_id,
                "org_id": org_id,
                "priority": priority,
                "enqueued_at": time.time(),
            })
            await pipe.execute()
    
    async def dequeue_for_device(self, device_id: str, org_id: str) -> str | None:
        """
        Получить следующую задачу для устройства (с atomic lock).
        Returns task_id или None если устройство занято / очередь пуста.
        """
        running_key = self.RUNNING_KEY.format(device_id=device_id)
        
        # Atomic check-and-set: если устройство не занято
        already_running = await self.redis.get(running_key)
        if already_running:
            return None
        
        queue_key = self.QUEUE_KEY.format(org_id=org_id)
        
        # Lua script для атомарной операции: ZPOPMIN + SET
        lua_script = """
        local task_id = redis.call('ZPOPMIN', KEYS[1], 1)
        if #task_id == 0 then return nil end
        local tid = task_id[1]
        redis.call('SET', KEYS[2], tid, 'EX', 3600)
        return tid
        """
        result = await self.redis.eval(lua_script, 2, queue_key, running_key)
        return result.decode() if result else None
    
    async def mark_completed(self, task_id: str, device_id: str):
        """Освободить устройство после завершения задачи."""
        await self.redis.delete(self.RUNNING_KEY.format(device_id=device_id))
    
    async def cancel_task(self, task_id: str, org_id: str) -> bool:
        """Отменить задачу из очереди (до начала выполнения)."""
        queue_key = self.QUEUE_KEY.format(org_id=org_id)
        removed = await self.redis.zrem(queue_key, task_id)
        return bool(removed)
    
    async def get_queue_depth(self, org_id: str) -> int:
        return await self.redis.zcard(self.QUEUE_KEY.format(org_id=org_id))
```

---

## Шаг 3 — Task Service

```python
# backend/services/task_service.py
from datetime import datetime, timezone  # MED-6: timezone необходим для datetime.now(timezone.utc)

class TaskService:
    async def create_task(
        self,
        script_id: uuid.UUID,
        device_id: str,
        org_id: uuid.UUID,
        priority: int = 5,
        webhook_url: str | None = None,
    ) -> Task:
        # Получить текущую версию скрипта
        script = await self._get_script(script_id, org_id)
        if not script.current_version_id:
            raise HTTPException(400, "Script has no versions")
        
        # Проверить что устройство принадлежит org
        device = await self._get_device(device_id, org_id)
        
        # Идемпотентность: проверить нет ли уже PENDING/RUNNING задачи
        # с тем же dag_hash для этого устройства (защита от дублирующих вызовов n8n/webhook)
        version = await self.db.get(ScriptVersion, script.current_version_id)
        duplicate = await self.db.scalar(
            select(Task.id).where(
                Task.device_id == device_id,
                Task.org_id == org_id,
                Task.script_version_id == script.current_version_id,
                Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            ).limit(1)
        )
        if duplicate:
            raise HTTPException(409, f"Task already queued/running for device '{device_id}' (task_id={duplicate})")
        
        task = Task(
            org_id=org_id,
            script_id=script_id,
            script_version_id=script.current_version_id,
            device_id=device_id,
            priority=priority,
            webhook_url=webhook_url,
        )
        self.db.add(task)
        await self.db.flush()
        
        # Добавить в Redis очередь
        await self.queue.enqueue(str(task.id), device_id, str(org_id), priority)
        
        return task
    
    async def dispatch_pending_tasks(self):
        """
        Запускается периодически (или триггером) — отправляет задачи агентам.
        По одной задаче на устройство.
        """
        # Получить все онлайн устройства
        online_devices = await self.status_cache.get_online_device_ids()
        
        for device_id in online_devices:
            task_id = await self.queue.dequeue_for_device(device_id, ...)
            if not task_id:
                continue
            
            # Получить DAG
            task = await self.db.get(Task, uuid.UUID(task_id))
            version = await self.db.get(ScriptVersion, task.script_version_id)
            
            # Отправить команду агенту
            sent = await self.publisher.send_command_to_device(device_id, {
                "type": "execute_dag",
                "task_id": task_id,
                "dag": version.dag,
                "timeout_ms": 3_600_000,
            })
            
            if sent:
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now(timezone.utc)  # MED-6: utcnow() deprecated since Python 3.12
            else:
                # Агент оффлайн — вернуть в очередь
                await self.queue.enqueue(task_id, device_id, str(task.org_id), task.priority)

# ─── FIX ARCH-3: SCHEDULER ДЛЯ dispatch_pending_tasks() ────────────
# КРИТИЧНО: Без этого кода dispatch_pending_tasks() НИГДЕ не вызывается!
# Задачи будут вечно висеть в Redis ZSet очереди.
#
# Добавить в backend/main.py → register_startup():
#   asyncio.create_task(_task_dispatcher_loop(task_service))
#
# Интервал 5 секунд — компромисс между латенси и нагрузкой на Redis.
# При 1000 устройств: ~1000 ZPOPMIN каждые 5с = 200 ops/s — допустимо.
# ────────────────────────────────────────────────────────────────────

_dispatcher_task: asyncio.Task | None = None  # global reference — защита от GC

async def _task_dispatcher_loop(task_service: TaskService):
    """
    Периодически раздаёт задачи из Redis очереди онлайн-агентам.
    Запускается один раз при старте через register_startup().
    """
    logger.info("Task dispatcher loop запущен (интервал=5с)")
    while True:
        try:
            await task_service.dispatch_pending_tasks()
        except Exception as e:
            logger.error("Dispatch error", error=str(e), exc_info=True)
        await asyncio.sleep(5)

def start_dispatcher(task_service: TaskService):
    """Вызвать из lifespan/register_startup."""
    global _dispatcher_task
    _dispatcher_task = asyncio.create_task(
        _task_dispatcher_loop(task_service),
        name="task_dispatcher",
    )
    
    async def handle_task_result(self, task_id: str, device_id: str, result: dict):
        """Вызывается при получении command_result от агента."""
        task = await self.db.get(Task, uuid.UUID(task_id))
        if not task:
            return
        
        task.status = TaskStatus.COMPLETED if result.get("success") else TaskStatus.FAILED
        task.completed_at = datetime.now(timezone.utc)  # MED-6: utcnow() deprecated since Python 3.12
        task.result = result
        task.error_msg = result.get("error")
        
        await self.queue.mark_completed(task_id, device_id)
        
        # Webhook callback
        if task.webhook_url:
            # HIGH-5: сохраняем reference на task — без этого GC удалит задачу до завершения
            if not hasattr(self, '_pending_tasks'):
                self._pending_tasks: set[asyncio.Task] = set()
            _t = asyncio.create_task(self._call_webhook(task))
            self._pending_tasks.add(_t)
            _t.add_done_callback(self._pending_tasks.discard)
        
        # Событие в Fleet Events
        await self.events.command_completed(device_id, str(task.org_id), task_id, result)
```

---

## Критерии готовности

- [ ] Два устройства обрабатывают задачи параллельно (atomic dequeue via Lua)
- [ ] Одно устройство: не более 1 задачи одновременно
- [ ] Задача с priority=1 выполняется раньше priority=10
- [ ] Агент оффлайн: задача остаётся в очереди (не теряется)
- [ ] Cancel pending до начала выполнения работает
- [ ] Webhook вызывается асинхронно (не блокирует основную логику)
