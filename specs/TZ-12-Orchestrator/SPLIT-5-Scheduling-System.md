# TZ-12 SPLIT-5 — Система расписаний: Cron Scheduler, периодический запуск скриптов и pipeline-ов

> **Статус:** Draft  
> **Приоритет:** P1  
> **Зависимости:** SPLIT-4 (Orchestrator Engine), TZ-04 (Task Engine)

---

## 1. Мотивация

### 1.1 Требование

> *«На 5-й, 25-й и 45-й минуте каждого часа запускается определённый скрипт»*

Текущий стек позволяет запустить скрипт/pipeline только **вручную** — через API вызов или через n8n workflow. Нет встроенного инструмента для:

- Периодического запуска скриптов по расписанию (cron)
- Интервальных запусков (каждые N минут)
- Расписания на группу устройств / по тегам
- Отключения и включения расписаний без удаления
- Watchdog расписаний (если предыдущий запуск ещё не завершён)

### 1.2 Архитектурный выбор

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| **APScheduler** | Зрелая библиотека, хороший cron-синтаксис | Привязка к одному процессу; потеря при рестарте |
| **Celery Beat** | Распределённый, проверен | Тяжёлая зависимость, Celery + Broker |
| **Собственный scheduler + PostgreSQL** | Полный контроль, персистенция, SKIP LOCKED | Нет готового cron парсера (берём `croniter`) |
| **n8n Schedule Trigger** | Уже есть инструмент | Не хватает контроля: пауза/delete/conflict resolution |

**Решение: Собственный DB-backed Scheduler** с библиотекой `croniter` для парсинга cron-выражений.

Причины:
1. **Отказоустойчивость** — расписания в PostgreSQL, не теряются при рестарте
2. **Масштабирование** — `FOR UPDATE SKIP LOCKED` для N инстансов бэкенда
3. **API-first** — CRUD через REST, UI управление
4. **Конфликты** — встроенная логика: что делать, если предыдущий запуск не завершён

---

## 2. Модель данных

### 2.1 Schedule — Расписание

```python
class ScheduleConflictPolicy(str, Enum):
    """Политика при конфликте: предыдущий запуск ещё не завершён."""
    SKIP = "skip"              # Пропустить текущий тик
    QUEUE = "queue"            # Поставить в очередь
    CANCEL_PREVIOUS = "cancel" # Отменить предыдущий, запустить новый


class ScheduleTargetType(str, Enum):
    """Тип цели расписания."""
    SCRIPT = "script"          # Запуск одного скрипта
    PIPELINE = "pipeline"      # Запуск pipeline (SPLIT-4)


class Schedule(Base, UUIDMixin, TimestampMixin):
    """Расписание запуска скрипта или pipeline.
    
    Поддерживает:
    - Cron-выражения (5 полей: минуты, часы, день месяца, месяц, день недели)
    - Интервальные расписания (каждые N минут/часов)
    - Разовые (one_shot) — однократный запуск в заданное время
    - Таргетирование: конкретное устройство, группа, теги
    - Конфликтные политики
    """
    __tablename__ = "schedules"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Тип расписания
    cron_expression: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="Cron (5 полей): '5,25,45 * * * *' = 5/25/45 мин каждого часа"
    )
    interval_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Интервал в секундах (альтернатива cron)"
    )
    one_shot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Однократный запуск в указанное время"
    )
    
    # Таймзона
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC",
        comment="Таймзона для cron (IANA: Europe/Moscow, America/New_York)"
    )
    
    # Цель запуска
    target_type: Mapped[ScheduleTargetType] = mapped_column(
        SQLAlchemyEnum(ScheduleTargetType), nullable=False
    )
    script_id: Mapped[UUID | None] = mapped_column(ForeignKey("scripts.id"), nullable=True)
    pipeline_id: Mapped[UUID | None] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    
    # Входные параметры для скрипта/pipeline
    input_params: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Таргетирование устройств
    device_ids: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="Список UUID конкретных устройств"
    )
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    device_tags: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="Теги устройств — запуск на всех с этими тегами"
    )
    only_online: Mapped[bool] = mapped_column(
        default=True, comment="Запускать только на online устройствах"
    )
    
    # Конфликтная политика
    conflict_policy: Mapped[ScheduleConflictPolicy] = mapped_column(
        SQLAlchemyEnum(ScheduleConflictPolicy),
        default=ScheduleConflictPolicy.SKIP,
    )
    
    # Состояние
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    
    # Окно активности (опциональное)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Лимиты
    max_runs: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Макс. кол-во запусков (null = безлимит)"
    )
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    
    # Расчётное время следующего срабатывания
    next_fire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
        comment="Рассчитанное время следующего срабатывания"
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Кто создал
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    __table_args__ = (
        Index("ix_schedules_next_fire", "is_active", "next_fire_at"),
        Index("ix_schedules_org_active", "org_id", "is_active"),
        CheckConstraint(
            "(cron_expression IS NOT NULL) OR (interval_seconds IS NOT NULL) OR (one_shot_at IS NOT NULL)",
            name="ck_schedules_has_trigger",
        ),
    )
```

### 2.2 ScheduleExecution — Лог срабатываний

```python
class ScheduleExecutionStatus(str, Enum):
    TRIGGERED = "triggered"    # Расписание сработало, запуск создан
    SKIPPED = "skipped"        # Пропущено (конфликт / устройства offline)
    COMPLETED = "completed"    # Все запущенные задачи завершены
    PARTIAL = "partial"        # Часть задач succeed, часть fail
    FAILED = "failed"          # Все задачи провалились


class ScheduleExecution(Base, UUIDMixin, TimestampMixin):
    """Запись об одном срабатывании расписания.
    
    Хранит результат: сколько устройств затронуто,
    сколько задач создано, общий статус.
    """
    __tablename__ = "schedule_executions"

    schedule_id: Mapped[UUID] = mapped_column(ForeignKey("schedules.id"), nullable=False, index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    
    status: Mapped[ScheduleExecutionStatus] = mapped_column(
        SQLAlchemyEnum(ScheduleExecutionStatus), default=ScheduleExecutionStatus.TRIGGERED
    )
    
    fire_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Плановое время срабатывания"
    )
    actual_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Фактическое время срабатывания"
    )
    
    # Статистика
    devices_targeted: Mapped[int] = mapped_column(Integer, default=0)
    tasks_created: Mapped[int] = mapped_column(Integer, default=0)
    tasks_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, default=0)
    
    # ID пачки задач/pipeline runs
    batch_id: Mapped[UUID | None] = mapped_column(nullable=True)
    pipeline_batch_id: Mapped[UUID | None] = mapped_column(nullable=True)
    
    # Причина пропуска (если SKIPPED)
    skip_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    
    # Тайминги
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    __table_args__ = (
        Index("ix_schedule_executions_schedule_fire", "schedule_id", "fire_time"),
    )
```

---

## 3. Scheduler Engine

### 3.1 Архитектура

```
┌──────────────────────────────────────────────────────────────────────┐
│                        SchedulerEngine                               │
│                                                                      │
│  ┌──────────────────┐     ┌────────────────────┐                     │
│  │  _tick() loop    │────►│  SELECT schedules   │                     │
│  │  каждые 10 сек   │     │  WHERE next_fire_at │                     │
│  │                  │     │  <= NOW()            │                     │
│  └──────────────────┘     │  FOR UPDATE          │                     │
│                           │  SKIP LOCKED         │                     │
│                           └─────────┬────────────┘                     │
│                                     │                                  │
│                                     ▼                                  │
│                           ┌────────────────────┐                       │
│                           │  _fire_schedule()  │                       │
│                           └──────┬─────────────┘                       │
│                                  │                                     │
│              ┌───────────────────┼───────────────────┐                 │
│              ▼                   ▼                   ▼                 │
│     ┌──────────────┐   ┌──────────────┐   ┌──────────────┐           │
│     │ Resolve      │   │ Conflict     │   │ Create tasks │           │
│     │ devices      │   │ check        │   │ or pipeline  │           │
│     │ (tags/group) │   │ (skip/cancel)│   │ runs         │           │
│     └──────────────┘   └──────────────┘   └──────────────┘           │
│                                                                      │
│  ┌──────────────────┐                                                │
│  │ Recalculate      │  croniter(expr) → next_fire_at                 │
│  │ next_fire_at     │                                                │
│  └──────────────────┘                                                │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 SchedulerEngine — Основной класс

```python
# backend/services/scheduler/scheduler_engine.py

from croniter import croniter
from zoneinfo import ZoneInfo

class SchedulerEngine:
    """DB-backed scheduler для периодического запуска скриптов и pipeline-ов.
    
    Свойства:
    1. Персистентность: next_fire_at хранится в PostgreSQL
    2. Масштабирование: FOR UPDATE SKIP LOCKED — безопасен для N инстансов
    3. Точность: тик каждые 10 секунд, макс. задержка ~10с
    4. Таймзоны: полная поддержка IANA (через zoneinfo)
    5. Конфликты: skip / queue / cancel_previous
    """

    def __init__(
        self,
        session_maker: async_sessionmaker,
        task_service: TaskService,
        pipeline_scheduler: PipelineScheduler,
        batch_service: BatchService,
        redis: Redis,
    ):
        self._session_maker = session_maker
        self._task_service = task_service
        self._pipeline_scheduler = pipeline_scheduler
        self._batch_service = batch_service
        self._redis = redis

    async def run_forever(self) -> None:
        """Основной бесконечный цикл.
        
        Каждые 10 секунд проверяет: есть ли расписания,
        у которых next_fire_at <= now().
        """
        logger.info("scheduler_engine.started")
        
        while True:
            try:
                fired_count = await self._tick()
                if fired_count:
                    logger.info("scheduler_engine.tick", fired=fired_count)
            except Exception as e:
                logger.error("scheduler_engine.error", error=str(e), exc_info=True)
            
            await asyncio.sleep(10)

    async def _tick(self) -> int:
        """Одна итерация: найти сработавшие расписания, обработать их."""
        now = datetime.now(timezone.utc)
        fired = 0

        async with self._session_maker() as db:
            schedules = (await db.execute(
                select(Schedule)
                .where(
                    Schedule.is_active == True,
                    Schedule.next_fire_at.isnot(None),
                    Schedule.next_fire_at <= now,
                )
                .order_by(Schedule.next_fire_at.asc())
                .limit(50)
                .with_for_update(skip_locked=True)
            )).scalars().all()

            for schedule in schedules:
                try:
                    await self._fire_schedule(schedule, now, db)
                    fired += 1
                except Exception as e:
                    logger.error(
                        "scheduler_engine.fire_error",
                        schedule_id=str(schedule.id),
                        error=str(e),
                        exc_info=True,
                    )
                
                # Пересчитать next_fire_at
                schedule.last_fired_at = now
                schedule.total_runs += 1
                schedule.next_fire_at = self._calculate_next_fire(schedule, now)
                
                # Проверить лимит запусков
                if schedule.max_runs and schedule.total_runs >= schedule.max_runs:
                    schedule.is_active = False
                    schedule.next_fire_at = None
                
                # Проверить окно активности
                if schedule.active_until and now >= schedule.active_until:
                    schedule.is_active = False
                    schedule.next_fire_at = None
                
                # one_shot — деактивировать после однократного запуска
                if schedule.one_shot_at:
                    schedule.is_active = False
                    schedule.next_fire_at = None

            await db.commit()

        return fired

    async def _fire_schedule(
        self, schedule: Schedule, now: datetime, db: AsyncSession
    ) -> None:
        """Сработать расписание: определить устройства, проверить конфликты, создать задачи."""
        
        # 1. Определить целевые устройства
        device_ids = await self._resolve_devices(schedule, db)
        if not device_ids:
            await self._log_execution(
                schedule, now, db,
                status=ScheduleExecutionStatus.SKIPPED,
                skip_reason="Нет подходящих устройств (offline или не найдены)",
            )
            return

        # 2. Проверить конфликты
        if schedule.conflict_policy != ScheduleConflictPolicy.QUEUE:
            has_conflict = await self._check_conflict(schedule, device_ids, db)
            if has_conflict:
                if schedule.conflict_policy == ScheduleConflictPolicy.SKIP:
                    await self._log_execution(
                        schedule, now, db,
                        status=ScheduleExecutionStatus.SKIPPED,
                        skip_reason="Предыдущий запуск ещё не завершён (policy=skip)",
                    )
                    return
                elif schedule.conflict_policy == ScheduleConflictPolicy.CANCEL_PREVIOUS:
                    await self._cancel_previous(schedule, db)

        # 3. Создать задачи/pipeline runs
        execution = await self._create_runs(schedule, device_ids, now, db)
        
        logger.info(
            "scheduler_engine.fired",
            schedule_id=str(schedule.id),
            schedule_name=schedule.name,
            devices=len(device_ids),
            execution_id=str(execution.id),
        )

    async def _resolve_devices(self, schedule: Schedule, db: AsyncSession) -> list[UUID]:
        """Определить список устройств для запуска.
        
        Приоритет: device_ids > group_id > device_tags.
        Если only_online=True — фильтровать через Redis.
        """
        if schedule.device_ids:
            device_ids = [UUID(d) for d in schedule.device_ids]
        elif schedule.group_id:
            # Устройства из группы
            result = await db.execute(
                select(Device.id).where(Device.group_id == schedule.group_id)
            )
            device_ids = list(result.scalars().all())
        elif schedule.device_tags:
            # Устройства по тегам (все теги должны присутствовать)
            result = await db.execute(
                select(Device.id).where(
                    Device.tags.contains(schedule.device_tags)
                )
            )
            device_ids = list(result.scalars().all())
        else:
            return []

        # Фильтр по online-статусу (Redis)
        if schedule.only_online and device_ids:
            online_ids = []
            for did in device_ids:
                status = await self._redis.get(f"device:{did}:status")
                if status and status.decode() == "online":
                    online_ids.append(did)
            return online_ids

        return device_ids

    async def _check_conflict(
        self, schedule: Schedule, device_ids: list[UUID], db: AsyncSession
    ) -> bool:
        """Проверить: есть ли незавершённые запуски от этого расписания."""
        result = await db.execute(
            select(ScheduleExecution.id)
            .where(
                ScheduleExecution.schedule_id == schedule.id,
                ScheduleExecution.status == ScheduleExecutionStatus.TRIGGERED,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _cancel_previous(self, schedule: Schedule, db: AsyncSession) -> None:
        """Отменить предыдущие незавершённые запуски."""
        execs = (await db.execute(
            select(ScheduleExecution)
            .where(
                ScheduleExecution.schedule_id == schedule.id,
                ScheduleExecution.status == ScheduleExecutionStatus.TRIGGERED,
            )
        )).scalars().all()

        for ex in execs:
            ex.status = ScheduleExecutionStatus.SKIPPED
            ex.skip_reason = "Отменено: policy=cancel_previous"
            ex.finished_at = datetime.now(timezone.utc)
            # Также отменить связанные tasks/pipeline runs
            if ex.batch_id:
                await self._task_service.cancel_batch(ex.batch_id, db)
            if ex.pipeline_batch_id:
                await self._pipeline_scheduler.cancel_batch(ex.pipeline_batch_id, db)

    async def _create_runs(
        self, schedule: Schedule, device_ids: list[UUID], now: datetime, db: AsyncSession
    ) -> ScheduleExecution:
        """Создать задачи или pipeline runs для всех целевых устройств."""
        
        execution = ScheduleExecution(
            schedule_id=schedule.id,
            org_id=schedule.org_id,
            status=ScheduleExecutionStatus.TRIGGERED,
            fire_time=schedule.next_fire_at,
            actual_time=now,
            devices_targeted=len(device_ids),
        )

        if schedule.target_type == ScheduleTargetType.SCRIPT:
            # Создать batch задач
            batch = await self._batch_service.start_batch(
                script_id=schedule.script_id,
                device_ids=device_ids,
                org_id=schedule.org_id,
                wave_config={},
                db=db,
            )
            execution.batch_id = batch.id
            execution.tasks_created = len(device_ids)

        elif schedule.target_type == ScheduleTargetType.PIPELINE:
            # Создать pipeline runs для каждого устройства
            runs_created = 0
            for device_id in device_ids:
                pipeline = await db.get(Pipeline, schedule.pipeline_id)
                run = PipelineRun(
                    org_id=schedule.org_id,
                    pipeline_id=schedule.pipeline_id,
                    device_id=device_id,
                    status=PipelineRunStatus.QUEUED,
                    input_params=schedule.input_params,
                    steps_snapshot=pipeline.steps,
                    context=dict(schedule.input_params),
                )
                db.add(run)
                runs_created += 1
            execution.tasks_created = runs_created

        db.add(execution)
        return execution

    def _calculate_next_fire(self, schedule: Schedule, after: datetime) -> datetime | None:
        """Рассчитать время следующего срабатывания.
        
        Использует croniter для cron-выражений.
        """
        if schedule.one_shot_at:
            return None  # Однократный — больше не срабатывает
        
        if schedule.cron_expression:
            try:
                tz = ZoneInfo(schedule.timezone)
                after_local = after.astimezone(tz)
                cron = croniter(schedule.cron_expression, after_local)
                next_local = cron.get_next(datetime)
                return next_local.astimezone(timezone.utc)
            except Exception as e:
                logger.error("scheduler.cron_parse_error", expr=schedule.cron_expression, error=str(e))
                return None
        
        if schedule.interval_seconds:
            return after + timedelta(seconds=schedule.interval_seconds)
        
        return None

    async def _log_execution(
        self,
        schedule: Schedule,
        now: datetime,
        db: AsyncSession,
        status: ScheduleExecutionStatus,
        skip_reason: str | None = None,
    ) -> None:
        """Записать лог пропущенного срабатывания."""
        execution = ScheduleExecution(
            schedule_id=schedule.id,
            org_id=schedule.org_id,
            status=status,
            fire_time=schedule.next_fire_at,
            actual_time=now,
            finished_at=now,
            skip_reason=skip_reason,
        )
        db.add(execution)
```

### 3.3 Recalculate Trigger для CRUD

```python
# backend/services/scheduler/schedule_service.py

class ScheduleService:
    """CRUD-сервис для управления расписаниями."""

    def __init__(self, session_maker: async_sessionmaker):
        self._session_maker = session_maker

    async def create(self, data: ScheduleCreate, org_id: UUID, user_id: UUID) -> Schedule:
        """Создать расписание с автоматическим расчётом next_fire_at."""
        async with self._session_maker() as db:
            schedule = Schedule(
                org_id=org_id,
                created_by_id=user_id,
                **data.model_dump(exclude_none=True),
            )
            
            # Валидация cron-выражения
            if schedule.cron_expression:
                if not croniter.is_valid(schedule.cron_expression):
                    raise ValueError(f"Невалидное cron-выражение: {schedule.cron_expression}")
            
            # Валидация таймзоны
            try:
                ZoneInfo(schedule.timezone)
            except KeyError:
                raise ValueError(f"Неизвестная таймзона: {schedule.timezone}")
            
            # Расчёт first fire
            schedule.next_fire_at = self._calculate_first_fire(schedule)
            
            db.add(schedule)
            await db.commit()
            await db.refresh(schedule)
            return schedule

    async def update(self, schedule_id: UUID, data: ScheduleUpdate, org_id: UUID) -> Schedule:
        """Обновить расписание — пересчитать next_fire_at."""
        async with self._session_maker() as db:
            schedule = await db.get(Schedule, schedule_id)
            if not schedule or schedule.org_id != org_id:
                raise NotFoundException("Расписание не найдено")
            
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(schedule, key, value)
            
            # Пересчитать next_fire_at при изменении cron/interval
            schedule.next_fire_at = self._calculate_first_fire(schedule)
            
            await db.commit()
            await db.refresh(schedule)
            return schedule

    async def toggle(self, schedule_id: UUID, is_active: bool, org_id: UUID) -> Schedule:
        """Включить/выключить расписание."""
        async with self._session_maker() as db:
            schedule = await db.get(Schedule, schedule_id)
            if not schedule or schedule.org_id != org_id:
                raise NotFoundException("Расписание не найдено")
            
            schedule.is_active = is_active
            if is_active:
                schedule.next_fire_at = self._calculate_first_fire(schedule)
            else:
                schedule.next_fire_at = None
            
            await db.commit()
            await db.refresh(schedule)
            return schedule

    async def delete(self, schedule_id: UUID, org_id: UUID) -> None:
        """Мягкое удаление — деактивация."""
        async with self._session_maker() as db:
            schedule = await db.get(Schedule, schedule_id)
            if not schedule or schedule.org_id != org_id:
                raise NotFoundException("Расписание не найдено")
            schedule.is_active = False
            schedule.next_fire_at = None
            await db.commit()

    async def list_schedules(
        self, org_id: UUID, is_active: bool | None = None, limit: int = 50, offset: int = 0
    ) -> list[Schedule]:
        async with self._session_maker() as db:
            query = select(Schedule).where(Schedule.org_id == org_id)
            if is_active is not None:
                query = query.where(Schedule.is_active == is_active)
            query = query.order_by(Schedule.created_at.desc()).limit(limit).offset(offset)
            result = await db.execute(query)
            return list(result.scalars().all())

    async def get_executions(
        self, schedule_id: UUID, org_id: UUID, limit: int = 50
    ) -> list[ScheduleExecution]:
        async with self._session_maker() as db:
            result = await db.execute(
                select(ScheduleExecution)
                .where(
                    ScheduleExecution.schedule_id == schedule_id,
                    ScheduleExecution.org_id == org_id,
                )
                .order_by(ScheduleExecution.fire_time.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    def _calculate_first_fire(self, schedule: Schedule) -> datetime | None:
        """Расчёт первого/следующего срабатывания."""
        now = datetime.now(timezone.utc)
        
        if schedule.one_shot_at:
            return schedule.one_shot_at if schedule.one_shot_at > now else None
        
        # Окно активности: если active_from в будущем — начинаем оттуда
        start = max(now, schedule.active_from) if schedule.active_from else now
        
        if schedule.cron_expression:
            try:
                tz = ZoneInfo(schedule.timezone)
                start_local = start.astimezone(tz)
                cron = croniter(schedule.cron_expression, start_local)
                return cron.get_next(datetime).astimezone(timezone.utc)
            except Exception:
                return None
        
        if schedule.interval_seconds:
            return start + timedelta(seconds=schedule.interval_seconds)
        
        return None
```

---

## 4. REST API

### 4.1 Endpoints

```
POST   /api/v1/schedules                      — Создать расписание
GET    /api/v1/schedules                      — Список расписаний (фильтры: active, target_type)
GET    /api/v1/schedules/{id}                 — Детали расписания
PATCH  /api/v1/schedules/{id}                 — Обновить расписание
DELETE /api/v1/schedules/{id}                 — Удалить (soft) расписание
POST   /api/v1/schedules/{id}/toggle          — Включить / выключить
POST   /api/v1/schedules/{id}/fire-now        — Принудительное срабатывание (вне расписания)
GET    /api/v1/schedules/{id}/executions      — История срабатываний
GET    /api/v1/schedules/{id}/next-fires      — Предпросмотр N будущих срабатываний
```

### 4.2 Пример запроса

```json
POST /api/v1/schedules
{
    "name": "Фарм BR — каждые 20 минут",
    "cron_expression": "5,25,45 * * * *",
    "timezone": "Europe/Moscow",
    "target_type": "pipeline",
    "pipeline_id": "...",
    "device_tags": ["farm", "blackrussia"],
    "only_online": true,
    "conflict_policy": "skip",
    "input_params": {
        "game_id": "blackrussia"
    }
}
```

### 4.3 Предпросмотр будущих срабатываний

```python
@router.get("/{schedule_id}/next-fires")
async def preview_next_fires(schedule_id: UUID, count: int = Query(10, ge=1, le=100)):
    """Показать следующие N времён срабатывания (для UI)."""
    schedule = await schedule_service.get(schedule_id, org_id)
    
    fires = []
    tz = ZoneInfo(schedule.timezone)
    current = datetime.now(tz)
    cron = croniter(schedule.cron_expression, current)
    
    for _ in range(count):
        next_fire = cron.get_next(datetime)
        fires.append(next_fire.isoformat())
    
    return {"fires": fires, "timezone": schedule.timezone}
```

---

## 5. Примеры расписаний

### 5.1 «На 5-й, 25-й и 45-й минуте каждого часа»

```json
{
    "cron_expression": "5,25,45 * * * *",
    "timezone": "Europe/Moscow"
}
```

Результат: 00:05, 00:25, 00:45, 01:05, 01:25, ...

### 5.2 «Каждые 30 минут с 10:00 до 22:00 по МСК»

```json
{
    "cron_expression": "*/30 10-21 * * *",
    "timezone": "Europe/Moscow"
}
```

### 5.3 «Каждый рабочий день в 08:00 — запуск фарма»

```json
{
    "cron_expression": "0 8 * * 1-5",
    "timezone": "Europe/Moscow"
}
```

### 5.4 «Каждые 15 минут — только на устройствах с тегом "premium"»

```json
{
    "interval_seconds": 900,
    "device_tags": ["premium"],
    "only_online": true

}
```

### 5.5 «Однократный запуск через 2 часа»

```json
{
    "one_shot_at": "2025-01-15T14:00:00Z",
    "device_ids": ["device-uuid-1"]
}
```

---

## 6. Обработка таймзон и DST

### 6.1 Принцип

| Аспект | Решение |
|--------|---------|
| **Хранение** | `next_fire_at` всегда в UTC (TIMESTAMP WITH TIME ZONE) |
| **Расчёт** | Cron парсится в локальной таймзоне через `zoneinfo.ZoneInfo` |
| **DST переход** | `croniter` с `zoneinfo` корректно обрабатывает переходы DST |
| **UI** | Frontend показывает время в таймзоне расписания |
| **Валидация** | Только IANA таймзоны (Europe/Moscow, не MSK) |

### 6.2 Пример: DST переход

Расписание: `0 2 * * *` (в 02:00 по Europe/Moscow)

Весной при переходе +3 → +3 (Россия не имеет DST, но для стран с DST):
- `croniter` в сочетании с `zoneinfo` автоматически пропускает несуществующие времена и корректно обрабатывает дубликаты.

---

## 7. n8n Schedule Node — расширение

### 7.1 SphereScheduleManager Node

```typescript
// n8n-nodes/nodes/SphereScheduleManager/SphereScheduleManager.node.ts

// Позволяет n8n workflow создавать/управлять расписаниями через API.
// Операции: create, update, toggle, delete, list, fire_now

{
    displayName: 'Sphere Schedule Manager',
    name: 'sphereScheduleManager',
    group: ['transform'],
    description: 'Управление расписаниями Sphere Platform',
    properties: [
        {
            displayName: 'Operation',
            name: 'operation',
            type: 'options',
            options: [
                { name: 'Create', value: 'create' },
                { name: 'Update', value: 'update' },
                { name: 'Toggle', value: 'toggle' },
                { name: 'Delete', value: 'delete' },
                { name: 'List', value: 'list' },
                { name: 'Fire Now', value: 'fire_now' },
            ],
        },
        // ... поля для cron_expression, target, devices ...
    ]
}
```

---

## 8. Безопасность

| Аспект | Решение |
|--------|---------|
| **RLS** | `schedule.org_id` — фильтрация по организации |
| **Cron injection** | Валидация cron через `croniter.is_valid()` |
| **Таймзона** | Whitelist IANA, `ZoneInfo` — нет произвольных строк |
| **Бесконечный запуск** | `max_runs`, `active_until`, `is_active` — несколько уровней защиты |
| **DoS через cron** | `interval_seconds` ≥ 60, cron не чаще 1 раза в минуту |
| **Конфликты** | `conflict_policy` — явное управление поведением при overlap |

---

## 9. Отказоустойчивость

| Сценарий | Механизм |
|----------|----------|
| **Рестарт бэкенда** | `next_fire_at` в PostgreSQL — подхватится после перезапуска |
| **Пропущенный тик** | При первом тике после рестарта — все просроченные `next_fire_at` сработают |
| **N инстансов бэкенда** | `FOR UPDATE SKIP LOCKED` — каждое расписание обрабатывается ровно одним |
| **Потеря Redis** | Scheduler работает с PostgreSQL; фильтр `only_online` деградирует (пропуск тика) |
| **DAG скрипт завис** | Независимо от scheduler: Task timeout + конфликтная политика при следующем тике |

---

## 10. Миграция Alembic

```python
# alembic/versions/xxxxx_add_schedules.py

def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.dialects.postgresql.UUID, primary_key=True),
        sa.Column("org_id", sa.dialects.postgresql.UUID, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("cron_expression", sa.String(128), nullable=True),
        sa.Column("interval_seconds", sa.Integer, nullable=True),
        sa.Column("one_shot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(64), server_default="UTC"),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("script_id", sa.dialects.postgresql.UUID, sa.ForeignKey("scripts.id"), nullable=True),
        sa.Column("pipeline_id", sa.dialects.postgresql.UUID, sa.ForeignKey("pipelines.id"), nullable=True),
        sa.Column("input_params", sa.dialects.postgresql.JSONB, server_default="{}"),
        sa.Column("device_ids", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("group_id", sa.dialects.postgresql.UUID, sa.ForeignKey("groups.id"), nullable=True),
        sa.Column("device_tags", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("only_online", sa.Boolean, server_default="true"),
        sa.Column("conflict_policy", sa.String(32), server_default="skip"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_runs", sa.Integer, nullable=True),
        sa.Column("total_runs", sa.Integer, server_default="0"),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.dialects.postgresql.UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    op.create_index("ix_schedules_next_fire", "schedules", ["is_active", "next_fire_at"])
    op.create_index("ix_schedules_org_active", "schedules", ["org_id", "is_active"])

    op.create_table(
        "schedule_executions",
        sa.Column("id", sa.dialects.postgresql.UUID, primary_key=True),
        sa.Column("schedule_id", sa.dialects.postgresql.UUID, sa.ForeignKey("schedules.id"), nullable=False),
        sa.Column("org_id", sa.dialects.postgresql.UUID, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("fire_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("devices_targeted", sa.Integer, server_default="0"),
        sa.Column("tasks_created", sa.Integer, server_default="0"),
        sa.Column("tasks_succeeded", sa.Integer, server_default="0"),
        sa.Column("tasks_failed", sa.Integer, server_default="0"),
        sa.Column("batch_id", sa.dialects.postgresql.UUID, nullable=True),
        sa.Column("pipeline_batch_id", sa.dialects.postgresql.UUID, nullable=True),
        sa.Column("skip_reason", sa.String(512), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    op.create_index(
        "ix_schedule_executions_schedule_fire", "schedule_executions", ["schedule_id", "fire_time"]
    )

    # RLS
    op.execute("ALTER TABLE schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE schedule_executions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("schedule_executions")
    op.drop_table("schedules")
```

---

## 11. Зависимости

```
# requirements.txt — добавить:
croniter>=2.0.0       # Парсинг cron-выражений
```

---

## 12. Таблица изменений

| Компонент | Файл | Описание |
|-----------|------|----------|
| Backend | `models/schedule.py` | NEW: Schedule, ScheduleExecution, enum-ы |
| Backend | `schemas/schedule.py` | NEW: ScheduleCreate, ScheduleUpdate, ScheduleResponse |
| Backend | `services/scheduler/scheduler_engine.py` | NEW: SchedulerEngine (фоновый loop + fire logic) |
| Backend | `services/scheduler/schedule_service.py` | NEW: ScheduleService (CRUD + next_fire calc) |
| Backend | `api/v1/schedules/router.py` | NEW: REST API для расписаний |
| Backend | `requirements.txt` | + croniter>=2.0.0 |
| Backend | `alembic/versions/` | Миграция: schedules, schedule_executions |
| Backend | `main.py` | + запуск SchedulerEngine.run_forever в lifespan |
| n8n | `SphereScheduleManager/` | NEW: n8n node для управления расписаниями |
| Frontend | `app/schedules/` | NEW: Schedule Builder UI |
| Frontend | `components/schedules/` | NEW: CronEditor, ScheduleCalendar, ExecutionLog |

---

## 13. Критерии готовности

- [ ] Таблицы schedules, schedule_executions созданы с RLS, индексами и CHECK constraint
- [ ] SchedulerEngine: фоновый loop с FOR UPDATE SKIP LOCKED, интервал 10с
- [ ] Cron-выражения: парсинг через croniter, валидация при создании
- [ ] Interval: альтернативный режим каждые N секунд (минимум 60)
- [ ] One-shot: однократный запуск с автоматической деактивацией
- [ ] Таймзоны: IANA через zoneinfo, корректная обработка DST
- [ ] Conflict policies: skip, queue, cancel_previous — все протестированы
- [ ] only_online фильтр: проверка через Redis перед запуском
- [ ] ScheduleService: CRUD + toggle + fire-now + next-fires preview
- [ ] REST API: все endpoints с авторизацией и RLS
- [ ] Интеграция с TaskService (target_type=script) и PipelineScheduler (target_type=pipeline)
- [ ] Миграция Alembic успешно накатывается и откатывается
- [ ] Нагрузочный тест: 1000 активных расписаний, тик за < 1с
- [ ] UI: CronEditor с визуальным предпросмотром следующих 10 срабатываний
