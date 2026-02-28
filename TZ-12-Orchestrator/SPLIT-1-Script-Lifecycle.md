# TZ-12 SPLIT-1 — Полный жизненный цикл скрипта: Start / Pause / Resume / Stop

> **Статус:** Draft  
> **Приоритет:** P0 (критический путь)  
> **Зависимости:** TZ-04 SPLIT-3 (Task Queue), TZ-07 (Android Agent), TZ-03 (WebSocket)

---

## 1. Мотивация

На текущий момент агент поддерживает только два состояния выполнения:
- **RUNNING** — DAG выполняется
- **CANCELLED** — DAG прерван через `cancelRequested = true`

**Проблемы:**
1. Нет команды **PAUSE** — невозможно приостановить скрипт и продолжить позже (например, ожидание загрузки патча игры, или ручная проверка оператором)
2. Нет команды **RESUME** — после PAUSE нужно возобновить с того же узла
3. `cancelRequested` — грубый флаг без гарантий: нода может завершиться наполовину
4. Нет **graceful stop** — отличия между "мягкая остановка после текущего узла" и "немедленное убийство"
5. При 1000+ эмуляторов оператор должен массово управлять состояниями (pause all, resume all)

---

## 2. Целевая архитектура

### 2.1 Расширенная State Machine задачи

```
                        ┌─────────────┐
                        │   QUEUED    │
                        └──────┬──────┘
                               │ dispatch
                        ┌──────▼──────┐
                        │  ASSIGNED   │
                        └──────┬──────┘
                               │ agent ACK
                ┌──────────────▼──────────────┐
                │          RUNNING            │
                └──┬────────┬────────┬────────┘
                   │        │        │
          PAUSE_DAG│ STOP_DAG│ CANCEL_DAG│ timeout/error
                   │        │        │        │
           ┌───────▼──┐  ┌──▼─────┐  ┌▼──────┐  ┌▼──────┐
           │  PAUSED  │  │STOPPING│  │CANCEL-│  │FAILED │
           └────┬─────┘  └──┬─────┘  │ LED   │  └───────┘
         RESUME │     done  │        └───────┘
           ┌────▼─────┐  ┌──▼──────┐
           │ RUNNING  │  │COMPLETED│
           └──────────┘  └─────────┘
```

### 2.2 Новые WebSocket-команды

| Команда | Направление | Описание |
|---------|-------------|----------|
| `PAUSE_DAG` | Backend → Agent | Приостановить после текущего узла |
| `RESUME_DAG` | Backend → Agent | Возобновить с точки паузы |
| `STOP_DAG` | Backend → Agent | Мягкая остановка: завершить текущий узел → отправить результат → стоп |
| `CANCEL_DAG` | Backend → Agent | Жёсткая отмена: немедленный break (уже реализован) |

### 2.3 Протокол обмена

```
Backend → Agent:  { "type": "PAUSE_DAG",  "command_id": "...", "task_id": "..." }
Agent  → Backend: { "type": "command_result", "command_id": "...", "status": "completed",
                     "result": { "paused_at_node": "scan_all", "nodes_executed": 142, 
                                 "ctx_snapshot": {...} } }
```

---

## 3. Реализация: Android-агент (DagRunner.kt)

### 3.1 Новые состояния

```kotlin
enum class DagState {
    IDLE,       // Ничего не выполняется
    RUNNING,    // DAG выполняется
    PAUSING,    // Получена PAUSE, ждём завершения текущего узла
    PAUSED,     // Приостановлен: ctx сохранён, ожидает RESUME
    STOPPING,   // Получен STOP, ждём завершения текущего узла
    CANCELLED,  // Отменён
}
```

### 3.2 Модификация основного цикла DagRunner

```kotlin
// Текущий цикл:
while (currentNodeId != null) {
    if (cancelRequested) { break }
    // ... executeNode() ...
}

// Новый цикл:
while (currentNodeId != null) {
    // Проверка состояния ПЕРЕД каждым узлом
    when (state.get()) {
        DagState.CANCELLED -> {
            Timber.i("[DAG] Cancelled at node '$currentNodeId'")
            break
        }
        DagState.STOPPING -> {
            Timber.i("[DAG] Graceful stop at node '$currentNodeId'")
            break  // Но success = true, отправляем partial result
        }
        DagState.PAUSING -> {
            Timber.i("[DAG] Pausing at node '$currentNodeId'")
            state.set(DagState.PAUSED)
            // Сохраняем контекст для resume
            val snapshot = PauseSnapshot(
                currentNodeId = currentNodeId,
                ctx = HashMap(ctx),
                nodeLogs = ArrayList(nodeLogs),
                nodesExecuted = nodeLogs.size,
            )
            savePauseSnapshot(commandId, snapshot)
            // Уведомляем бэкенд
            sendPauseAck(commandId, snapshot)
            // Ожидаем RESUME (suspending coroutine)
            resumeLatch.await()  // CompletableDeferred<Unit>
            state.set(DagState.RUNNING)
            Timber.i("[DAG] Resumed from node '$currentNodeId'")
        }
        else -> { /* RUNNING — продолжаем */ }
    }

    // ... executeNode() как обычно ...
}
```

### 3.3 Сохранение контекста паузы

```kotlin
data class PauseSnapshot(
    val currentNodeId: String,
    val ctx: Map<String, Any?>,
    val nodeLogs: List<JsonObject>,
    val nodesExecuted: Int,
    val pausedAt: Long = System.currentTimeMillis(),
)

/**
 * Снапшот сохраняется в EncryptedSharedPreferences.
 * При краше/перезагрузке — восстанавливаемся.
 * При RESUME — читаем снапшот и продолжаем.
 */
private fun savePauseSnapshot(commandId: String, snapshot: PauseSnapshot) {
    val json = Json.encodeToString(snapshot.toJsonObject())
    prefs.edit().putString("pause_snapshot_$commandId", json).apply()
}
```

### 3.4 Обработка RESUME

```kotlin
// В CommandDispatcher.kt:
CommandType.RESUME_DAG -> {
    val taskId = cmd.payload["task_id"]?.jsonPrimitive?.content
    dagRunner.resume(taskId)
    buildJsonObject { put("status", "resumed") }
}

// В DagRunner.kt:
fun resume(taskId: String?) {
    if (state.get() == DagState.PAUSED) {
        resumeLatch.complete(Unit)
        Timber.i("[DAG] Resume signal received")
    }
}
```

---

## 4. Реализация: Backend

### 4.1 Расширение TaskStatus

```python
class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    PAUSED = "paused"         # ← НОВЫЙ
    STOPPING = "stopping"     # ← НОВЫЙ
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
```

### 4.2 Новые API-эндпоинты

```python
# backend/api/v1/tasks/router.py

@router.post("/{task_id}/pause", status_code=202)
async def pause_task(task_id: UUID, svc: TaskService = Depends()):
    """Приостановить выполняющийся скрипт."""
    task = await svc.pause_task(task_id)
    return {"status": "pause_requested", "task_id": str(task.id)}

@router.post("/{task_id}/resume", status_code=202)
async def resume_task(task_id: UUID, svc: TaskService = Depends()):
    """Возобновить приостановленный скрипт."""
    task = await svc.resume_task(task_id)
    return {"status": "resume_requested", "task_id": str(task.id)}

@router.post("/{task_id}/stop", status_code=202)
async def stop_task(task_id: UUID, svc: TaskService = Depends()):
    """Мягкая остановка: завершить текущий узел и остановить."""
    task = await svc.stop_task(task_id)
    return {"status": "stop_requested", "task_id": str(task.id)}
```

### 4.3 TaskService — методы управления

```python
async def pause_task(self, task_id: UUID) -> Task:
    task = await self._get_task(task_id)
    if task.status != TaskStatus.RUNNING:
        raise HTTPException(409, f"Cannot pause task in status '{task.status}'")
    
    # Отправить команду агенту
    delivered = await self.publisher.send_command_live(
        str(task.device_id),
        {"type": "PAUSE_DAG", "command_id": str(uuid4()), "task_id": str(task_id)}
    )
    if not delivered:
        raise HTTPException(502, "Agent is offline")
    
    task.status = TaskStatus.PAUSED
    await self.db.commit()
    
    # Событие для фронтенда и n8n
    await self.event_publisher.emit(FleetEvent(
        event_type=EventType.TASK_PAUSED,
        device_id=str(task.device_id),
        org_id=str(task.org_id),
        payload={"task_id": str(task_id)},
    ))
    return task
```

### 4.4 Массовые операции

```python
# POST /bulk/tasks/pause
@router.post("/tasks/pause", status_code=202)
async def bulk_pause(body: BulkTaskAction, svc: TaskService = Depends()):
    """Массовая пауза: по device_ids, group_id, tag или batch_id."""
    results = await svc.bulk_pause(body)
    return {"paused": results.success_count, "failed": results.fail_count}

# Аналогично: /bulk/tasks/resume, /bulk/tasks/stop
```

---

## 5. Реализация: Frontend

### 5.1 Кнопки управления

```tsx
// frontend/components/sphere/TaskActionButtons.tsx
function TaskActionButtons({ task }: { task: Task }) {
    return (
        <div className="flex gap-2">
            {task.status === "running" && (
                <>
                    <Button variant="outline" onClick={() => pauseTask(task.id)}>
                        <PauseIcon /> Пауза
                    </Button>
                    <Button variant="destructive" onClick={() => stopTask(task.id)}>
                        <StopIcon /> Стоп
                    </Button>
                </>
            )}
            {task.status === "paused" && (
                <Button variant="default" onClick={() => resumeTask(task.id)}>
                    <PlayIcon /> Продолжить
                </Button>
            )}
        </div>
    )
}
```

### 5.2 Hooks

```ts
// frontend/lib/hooks/useTasks.ts — расширение
export function usePauseTask() {
    return useMutation({
        mutationFn: (taskId: string) => api.post(`/tasks/${taskId}/pause`),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] }),
    })
}
// Аналогично: useResumeTask, useStopTask
```

---

## 6. Безопасность и отказоустойчивость

### 6.1 Race condition: PAUSE во время executeNode()

**Проблема:** Если PAUSE приходит во время длительного `findElement()` (10 сек polling), нода завершится, и PAUSE применится ПЕРЕД следующей нодой. Это корректно — мы не прерываем ноду на полпути.

### 6.2 Crash recovery: агент перезапустился в PAUSED

**Решение:** `PauseSnapshot` сохранён в `EncryptedSharedPreferences`. При старте агента:
1. Проверить наличие `pause_snapshot_*`
2. Если есть → отправить бэкенду `task_paused` с snapshot
3. Бэкенд знает, что задача в PAUSED — покажет во фронтенде

### 6.3 TTL для PAUSED

**Правило:** Задача в PAUSED более 24 часов → автоматический TIMEOUT.
```python
# В background task (каждые 5 минут):
stale_paused = select(Task).where(
    Task.status == TaskStatus.PAUSED,
    Task.updated_at < datetime.utcnow() - timedelta(hours=24),
)
for task in stale_paused:
    task.status = TaskStatus.TIMEOUT
    task.error_message = "Paused for >24h without resume"
```

### 6.4 Concurrency: два PAUSE подряд

Второй PAUSE → 409 Conflict (`"Cannot pause task in status 'paused'"`)

---

## 7. WebSocket-события для n8n

```python
# Новые EventType:
class EventType(str, Enum):
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"
    TASK_STOPPING = "task_stopping"
```

n8n `SphereEventTrigger` автоматически подхватит новые типы через `eventType: all`.

---

## 8. Таблица изменений

| Компонент | Файл | Что менять |
|-----------|------|-----------|
| Android | `DagRunner.kt` | DagState enum, pause/resume logic, snapshot save |
| Android | `CommandDispatcher.kt` | PAUSE_DAG, RESUME_DAG, STOP_DAG handlers |
| Backend | `models/task.py` | TaskStatus + PAUSED, STOPPING |
| Backend | `services/task_service.py` | pause_task(), resume_task(), stop_task() |
| Backend | `api/v1/tasks/router.py` | POST /{id}/pause, /{id}/resume, /{id}/stop |
| Backend | `api/v1/bulk/router.py` | POST /tasks/pause, /tasks/resume, /tasks/stop |
| Backend | `websocket/event_publisher.py` | TASK_PAUSED, TASK_RESUMED events |
| Backend | `tasks/stale_cleanup.py` | NEW: TTL для PAUSED задач |
| Frontend | `useTasks.ts` | usePauseTask, useResumeTask, useStopTask |
| Frontend | `TaskActionButtons.tsx` | NEW: кнопки Pause/Resume/Stop |

---

## 9. Критерии готовности

- [ ] Агент корректно ставит DAG на паузу после завершения текущего узла
- [ ] Агент сохраняет PauseSnapshot в EncryptedSharedPreferences
- [ ] RESUME продолжает DAG с того же узла и ctx
- [ ] STOP мягко завершает DAG с partial result (success=true)
- [ ] CANCEL немедленно прерывает (success=false) — обратная совместимость
- [ ] Фронтенд показывает кнопки Pause/Resume/Stop в зависимости от статуса
- [ ] n8n получает события task_paused, task_resumed
- [ ] Массовые операции: pause/resume/stop по device_ids, group, batch
- [ ] PAUSED > 24h → автоматический TIMEOUT
- [ ] Crash recovery: агент при старте проверяет pause snapshots
- [ ] Тесты: unit + integration для всех переходов state machine
