# SPLIT-4 — Wave Batch Execution (Волновый запуск на флите)

**ТЗ-родитель:** TZ-04-Script-Engine  
**Ветка:** `stage/4-scripts`  
**Задача:** `SPHERE-024`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-04 SPLIT-5
**Интеграция при merge:** TZ-08 PC Agent работает с простой рассылкой; при merge подключить Wave Batch

---

## Цель Сплита

Запуск скрипта на N устройствах волнами с jitter задержкой. Избегаем одновременного запуска на всех устройствах (нагрузка на сеть, паттерны обнаружения).

---

## Шаг 1 — Batch Model

> ⚠️ **ВНИМАНИЕ АГЕНТУ: НЕ СОЗДАВАЙ КЛАССЫ МОДЕЛЕЙ!**
>
> Модель `TaskBatch` **уже определена** в **TZ-00 SPLIT-2 Шаг 4** (файл `backend/models/task_batch.py`).
> Дублирование класса вызовет `SAWarning: Table 'task_batches' already exists` и конфликт при merge!
>
> **Используй только импорты:**
>
> ```python
> from backend.models.task_batch import TaskBatch
> from backend.models.task import Task, TaskStatus
> from backend.models.script import Script
> ```
>
> **Поля TaskBatch (справка):** `org_id`, `script_id`, `name`, `status`, `total_devices`,
> `wave_size`, `wave_delay_ms`, `jitter_ms`, `completed`, `failed`, `webhook_url`
>
> ✅ **Твоя задача в этом сплите:** только `backend/services/batch_service.py` + `backend/services/workstation_mapping.py` + `backend/api/v1/batches/router.py`

> **HIGH-6:** функция `get_db_session()` определена в TZ-00 SPLIT-2. Добавить import:
>
> ```python
> from backend.database.engine import get_db_session  # добавить в импорты batch_service.py
> ```

---

## Шаг 2 — BatchExecutionRequest

```python
class BatchExecutionRequest(BaseModel):
    script_id: uuid.UUID
    device_ids: list[str] = Field(min_length=1, max_length=1000)
    wave_size: int = Field(default=10, ge=1, le=100)
    wave_delay_ms: int = Field(default=5000, ge=0, le=3600000)
    jitter_ms: int = Field(default=1000, ge=0, le=30000)
    priority: int = Field(default=5, ge=1, le=10)
    webhook_url: str | None = None
    stagger_by_workstation: bool = Field(
        default=True,
        description="Разбивать волны по рабочим станциям (равномерная нагрузка)"
    )
```

---

## Шаг 3 — WorkstationMappingService

```python
# backend/services/workstation_mapping.py
class WorkstationMappingService:
    """
    Распределяет устройства из батча по рабочим станциям.
    Цель: первая волна не перегружает одну рабочую станцию.
    """
    
    async def create_waves(
        self,
        device_ids: list[str],
        org_id: uuid.UUID,
        wave_size: int,
        stagger_by_workstation: bool,
    ) -> list[list[str]]:
        if not stagger_by_workstation:
            # Простое разбиение на chunks
            return [device_ids[i:i+wave_size] for i in range(0, len(device_ids), wave_size)]
        
        # Получить mapping device_id → workstation_id
        # FIX: id_str → id (модель Device в TZ-00 определяет PK как id: Mapped[uuid.UUID])
        stmt = (
            select(Device.id, Device.workstation_id)
            .where(Device.id.in_(device_ids), Device.org_id == org_id)
        )
        rows = (await self.db.execute(stmt)).all()
        
        # Группировать по workstation
        ws_to_devices: dict[str | None, list[str]] = {}
        for device_id, ws_id in rows:
            key = str(ws_id) if ws_id else "no_workstation"
            ws_to_devices.setdefault(key, []).append(device_id)
        
        # Round-robin по workstation для равномерного распределения
        waves: list[list[str]] = []
        current_wave: list[str] = []
        ws_queues = [deque(devs) for devs in ws_to_devices.values()]
        
        while any(ws_queues):
            for ws_queue in ws_queues:
                if ws_queue:
                    current_wave.append(ws_queue.popleft())
                    if len(current_wave) >= wave_size:
                        waves.append(current_wave)
                        current_wave = []
        
        if current_wave:
            waves.append(current_wave)
        
        return waves
```

---

## Шаг 4 — BatchExecutionService

```python
# backend/services/batch_service.py
import asyncio
import random
import structlog
from backend.database.engine import async_session_maker, get_db_session
from backend.services.task_service import TaskService

logger = structlog.get_logger()

# FIX-4.3: Глобальный set для фоновых задач — переживает HTTP-запрос.
# Если оставить на self (экземпляр сервиса), GC прибьёт задачи после ответа 202.
_background_tasks: set[asyncio.Task] = set()


class BatchExecutionService:
    
    def __init__(self, db: AsyncSession, session_maker: async_session_maker):
        self.db = db
        # FIX-4.1: Сохраняем фабрику сессий, а не DI-сессию.
        # Фоновая задача создаст свою сессию — не зависит от HTTP-запроса.
        self._session_maker = session_maker
    
    async def start_batch(
        self,
        request: BatchExecutionRequest,
        org_id: uuid.UUID,
    ) -> TaskBatch:
        # Создать batch запись (в рамках ТЕКУЩЕЙ сессии — запрос ещё жив)
        batch = TaskBatch(
            org_id=org_id,
            script_id=request.script_id,
            total_devices=len(request.device_ids),
            wave_size=request.wave_size,
            wave_delay_ms=request.wave_delay_ms,
            jitter_ms=request.jitter_ms,
            webhook_url=request.webhook_url,
        )
        self.db.add(batch)
        await self.db.flush()
        
        # Разбить на волны с учётом workstations
        waves = await self.mapping_svc.create_waves(
            request.device_ids, org_id, request.wave_size, request.stagger_by_workstation
        )
        
        # FIX-4.3: Глобальный set — таски не погибнут от GC
        task = asyncio.create_task(
            self._execute_waves(batch.id, waves, request, org_id)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        
        return batch
    
    async def _execute_waves(
        self,
        batch_id: uuid.UUID,
        waves: list[list[str]],
        request: BatchExecutionRequest,
        org_id: uuid.UUID,
    ):
        # FIX-4.1: Фоновая задача работает в ИЗОЛИРОВАННОЙ сессии.
        # DI-сессия self.db уже закрыта к этому моменту!
        async with self._session_maker() as db:
            task_svc = TaskService(db)
            
            for wave_num, wave_devices in enumerate(waves):
                logger.info(f"Launching wave {wave_num+1}/{len(waves)}", 
                           devices=len(wave_devices), batch_id=str(batch_id))
                
                # Запустить все устройства в волне параллельно
                tasks_created = []
                for device_id in wave_devices:
                    try:
                        task_record = await task_svc.create_task(
                            script_id=request.script_id,
                            device_id=device_id,
                            org_id=org_id,
                            priority=request.priority,
                        )
                        tasks_created.append(task_record.id)
                    except Exception as e:
                        logger.warning(f"Failed to create task for {device_id}: {e}")
                
                # Коммитим каждую волну отдельно — частичный прогресс сохраняется
                await db.commit()
                
                # Ждать задержку между волнами с jitter
                if wave_num < len(waves) - 1:
                    jitter = random.randint(0, request.jitter_ms)
                    await asyncio.sleep((request.wave_delay_ms + jitter) / 1000)
        
        # FIX-4.2: Обновить статус батча С КОММИТОМ
        from backend.models.task_batch import TaskBatchStatus
        async with self._session_maker() as db:
            batch = await db.get(TaskBatch, batch_id)
            batch.status = TaskBatchStatus.COMPLETED
            await db.commit()  # ← БЕЗ ЭТОГО статус навсегда зависнет в RUNNING!
        
        # Финальный webhook
        if request.webhook_url:
            await self._send_batch_complete_webhook(batch_id, request.webhook_url)
```

---

## Шаг 5 — Router

```python
@router.post("/batches", response_model=BatchResponse, status_code=202)
async def start_batch(body: BatchExecutionRequest, ...):
    """
    Асинхронный запуск. Возвращает batch_id немедленно.
    Прогресс через GET /batches/{id} или Events WebSocket.
    """
    batch = await svc.start_batch(body, current_user.org_id)
    return batch

@router.get("/batches/{batch_id}", response_model=BatchDetailResponse)
async def get_batch_status(batch_id: uuid.UUID, ...): ...

@router.delete("/batches/{batch_id}", status_code=204)
async def cancel_batch(batch_id: uuid.UUID, ...): ...
```

---

## Критерии готовности

- [ ] 1000 устройств, wave_size=50: все волны запускаются корректно, нет потерь
- [ ] Wave delay с jitter: каждая волна ждёт base ± jitter
- [ ] stagger_by_workstation=true: устройства равномерно от разных PC
- [ ] Cancel batch: оставшиеся волны не запускаются, running задачи завершаются
- [ ] Batch endpoint возвращает 202 Accepted немедленно (не ждёт завершения)
- [ ] Финальный webhook с total/completed/failed статистикой
