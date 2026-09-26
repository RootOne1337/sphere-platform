# backend/services/scheduler/scheduler_engine.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-5. Фоновый движок исполнения расписаний.
#
# Цикл работы (каждые N секунд):
# 1. SELECT schedules WHERE is_active=true AND next_fire_at <= NOW() FOR UPDATE SKIP LOCKED
# 2. Для каждого: проверить conflict_policy → создать задачи/pipeline runs
# 3. Создать ScheduleExecution
# 4. Пересчитать next_fire_at
# 5. Если one_shot — деактивировать
#
# Безопасность: FOR UPDATE SKIP LOCKED гарантирует корректность при multi-instance.
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import AsyncSessionLocal
from backend.database.tenant import bind_tenant_context
from backend.models.schedule import (
    Schedule,
    ScheduleConflictPolicy,
    ScheduleExecution,
    ScheduleExecutionStatus,
    ScheduleTargetType,
)

logger = structlog.get_logger()

# Интервал поллинга расписаний
_POLL_INTERVAL_SECONDS = 5.0
_DISCOVERY_TIMEOUT_SECONDS = 5.0
_FIRING_TIMEOUT_SECONDS = 15.0
_PAGE_SIZE = 50
_CONCURRENCY = 4


class SchedulerEngine:
    """
    Фоновый движок расписаний.

    Поллит таблицу schedules, находит «созревшие» записи
    (next_fire_at <= NOW()), и запускает соответствующие задачи.
    """

    def __init__(self) -> None:
        self._running = False
        self._cursor: uuid.UUID | None = None

    async def start(self) -> None:
        """Запуск фонового loop."""
        self._running = True
        logger.info("scheduler_engine.started")
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.error("scheduler_engine.tick_error", error=str(exc))
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Остановка."""
        self._running = False
        logger.info("scheduler_engine.stopped")

    async def _discover_schedules(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
        async with asyncio.timeout(_DISCOVERY_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
            query = text("SELECT * FROM sphere_auth.schedule_work(:after)")
            rows = list((await db.execute(query, {"after": self._cursor})).all())
            if not rows and self._cursor is not None:
                rows = list((await db.execute(query, {"after": None})).all())
        return [(row[0], row[1]) for row in rows]

    async def _tick(self) -> None:
        """Discover UUIDs, then atomically process each firing in its own tenant."""
        candidates = await self._discover_schedules()
        for offset in range(0, len(candidates), _CONCURRENCY):
            await asyncio.gather(*(self._fire_schedule(*item)
                                   for item in candidates[offset:offset + _CONCURRENCY]))
        # A broken schedule must not permanently hide the next due page.
        self._cursor = candidates[-1][0] if len(candidates) == _PAGE_SIZE else None

    async def _fire_schedule(self, schedule_id: uuid.UUID, org_id: uuid.UUID) -> None:
        try:
            async with asyncio.timeout(_FIRING_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
                await bind_tenant_context(db, str(org_id))
                schedule = await db.scalar(select(Schedule).where(
                    Schedule.id == schedule_id, Schedule.org_id == org_id,
                    Schedule.is_active.is_(True), Schedule.next_fire_at <= func.clock_timestamp(),
                ).with_for_update(skip_locked=True).execution_options(populate_existing=True))
                if schedule is None:
                    return
                # All child rows, the execution receipt and next-fire state
                # commit together. The SQL dispatcher owns subsequent delivery;
                # a Redis enqueue is unnecessary and cannot acknowledge a firing.
                await self._process_schedule(schedule, datetime.now(timezone.utc), db, [])
                await db.commit()
        except Exception as exc:
            # Session exit rolls back partial writes. A lost commit ACK is
            # resolved by rereading the schedule, never by blind immediate replay.
            logger.error("scheduler_engine.schedule_error", schedule_id=str(schedule_id),
                         org_id=str(org_id), error_type=type(exc).__name__)

    async def _process_schedule(
        self,
        schedule: Schedule,
        fire_time: datetime,
        db: AsyncSession,
        pending_enqueue: list[tuple[str, str, str, int]] | None = None,
    ) -> None:
        """
        Обработать одно «созревшее» расписание.

        1. Проверить max_runs
        2. Проверить active_from / active_until
        3. Проверить conflict_policy
        4. Резолвить устройства
        5. Создать задачи / pipeline runs
        6. Записать ScheduleExecution
        7. Пересчитать next_fire_at
        """
        # Проверка лимита запусков
        if schedule.max_runs and schedule.total_runs >= schedule.max_runs:
            schedule.is_active = False
            schedule.next_fire_at = None
            logger.info("schedule.max_runs_reached", schedule_id=str(schedule.id))
            return

        # Проверка окна активности
        now = datetime.now(timezone.utc)
        if schedule.active_from and now < schedule.active_from:
            return
        if schedule.active_until and now > schedule.active_until:
            schedule.is_active = False
            schedule.next_fire_at = None
            return

        # Проверка conflict_policy
        if schedule.conflict_policy == ScheduleConflictPolicy.SKIP:
            has_running = await self._has_running_tasks(schedule, db)
            if has_running:
                # Пропустить тик, создать запись SKIPPED
                execution = ScheduleExecution(
                    schedule_id=schedule.id,
                    org_id=schedule.org_id,
                    status=ScheduleExecutionStatus.SKIPPED,
                    fire_time=fire_time,
                    actual_time=now,
                    skip_reason="Предыдущий запуск ещё не завершён (conflict_policy=skip)",
                )
                db.add(execution)
                # Пересчитать next_fire_at
                self._advance_fire_time(schedule)
                return

        if schedule.conflict_policy == ScheduleConflictPolicy.CANCEL_PREVIOUS:
            cancelled = await self._cancel_previous_tasks(schedule, db)
            if cancelled > 0:
                logger.info(
                    "schedule.cancelled_previous",
                    schedule_id=str(schedule.id),
                    cancelled_count=cancelled,
                )

        # Резолвить устройства
        device_ids = await self._resolve_devices(schedule, db)
        if not device_ids:
            execution = ScheduleExecution(
                schedule_id=schedule.id,
                org_id=schedule.org_id,
                status=ScheduleExecutionStatus.SKIPPED,
                fire_time=fire_time,
                actual_time=now,
                skip_reason="Нет подходящих устройств",
            )
            db.add(execution)
            self._advance_fire_time(schedule)
            return

        # Запуск задач / pipeline runs
        tasks_created = 0
        batch_id = None
        pipeline_batch_id = None

        if schedule.target_type == ScheduleTargetType.SCRIPT and schedule.script_id:
            tasks_created, batch_id = await self._create_script_tasks(
                schedule, device_ids, db, pending_enqueue,
            )
        elif schedule.target_type == ScheduleTargetType.PIPELINE and schedule.pipeline_id:
            tasks_created, pipeline_batch_id = await self._create_pipeline_runs(
                schedule, device_ids, db,
            )

        # Создать запись о срабатывании
        execution = ScheduleExecution(
            schedule_id=schedule.id,
            org_id=schedule.org_id,
            status=ScheduleExecutionStatus.TRIGGERED,
            fire_time=fire_time,
            actual_time=now,
            devices_targeted=len(device_ids),
            tasks_created=tasks_created,
            batch_id=batch_id,
            pipeline_batch_id=pipeline_batch_id,
        )
        db.add(execution)

        # Обновить schedule
        schedule.total_runs += 1
        schedule.last_fired_at = now

        # One-shot — деактивировать
        if schedule.one_shot_at:
            schedule.is_active = False
            schedule.next_fire_at = None
        else:
            self._advance_fire_time(schedule)

        logger.info(
            "schedule.fired",
            schedule_id=str(schedule.id),
            devices=len(device_ids),
            tasks=tasks_created,
        )

    async def _resolve_devices(
        self,
        schedule: Schedule,
        db: AsyncSession,
    ) -> list[uuid.UUID]:
        """Резолвить устройства на основе device_ids / group_id / device_tags."""
        from backend.models.device import Device, device_group_members

        result: set[uuid.UUID] = set()

        if schedule.device_ids:
            uuids = [uuid.UUID(d) if isinstance(d, str) else d for d in schedule.device_ids]
            base = select(Device.id).where(
                Device.id.in_(uuids),
                Device.org_id == schedule.org_id,
                Device.is_active.is_(True),
            )
            rows = await db.scalars(base)
            result.update(rows.all())

        if schedule.group_id:
            member_ids = await db.scalars(
                select(device_group_members.c.device_id).where(
                    device_group_members.c.group_id == schedule.group_id,
                )
            )
            result.update(member_ids.all())

        if schedule.device_tags:
            for tag in schedule.device_tags:
                tagged = await db.scalars(
                    select(Device.id).where(
                        Device.org_id == schedule.org_id,
                        Device.is_active.is_(True),
                        Device.tags.contains([tag]),
                    )
                )
                result.update(tagged.all())

        if schedule.only_online and result:
            from backend.database.redis_client import redis_binary
            from backend.services.device_status_cache import DeviceStatusCache

            if redis_binary is None:
                raise RuntimeError("schedule_presence_unavailable")
            cache = DeviceStatusCache(redis_binary)
            device_ids = sorted(result)
            online_ids: list[uuid.UUID] = []
            # Keep the firing atomic, but cap presence I/O while holding its lock.
            # Failure defers the whole firing; it must not mean "all online".
            async with asyncio.timeout(2):
                for offset in range(0, len(device_ids), 512):
                    page = device_ids[offset:offset + 512]
                    presence = await cache.bulk_get_status([str(did) for did in page])
                    online_ids.extend(did for did in page if (status := presence.get(str(did)))
                                      is not None and status.status == "online")
            return online_ids

        return sorted(result)

    async def _create_script_tasks(
        self,
        schedule: Schedule,
        device_ids: list[uuid.UUID],
        db: AsyncSession,
        pending_enqueue: list[tuple[str, str, str, int]] | None = None,
    ) -> tuple[int, uuid.UUID | None]:
        """Создать задачи (Task) для script-расписания с enqueue в Redis."""
        from backend.models.script import Script, ScriptVersion
        from backend.models.task import Task, TaskStatus
        from backend.models.task_batch import TaskBatch

        # Получить script_version_id для корректного исполнения
        script = await db.get(Script, schedule.script_id)
        if not script or not script.current_version_id:
            logger.error(
                "scheduler.script_not_found_or_no_version",
                script_id=str(schedule.script_id),
            )
            return 0, None

        # FIX BUG-B: Извлечь timeout из DAG-версии скрипта.
        # Без этого task.timeout_seconds = 300 (дефолт модели) → payload.timeout_ms = 300_000
        # → DagRunner использует 5-минутный таймаут вместо DAG-ного (например, 86_400_000 = 24ч).
        # Цепочка: task.timeout_seconds → payload.timeout_ms → CommandDispatcher → DagRunner.
        task_timeout_seconds = 300  # дефолт, если DAG не указывает свой
        version = await db.get(ScriptVersion, script.current_version_id)
        if version and version.dag and isinstance(version.dag, dict):
            dag_timeout_ms = version.dag.get("timeout_ms")
            if isinstance(dag_timeout_ms, (int, float)) and dag_timeout_ms > 0:
                task_timeout_seconds = int(dag_timeout_ms / 1000)
                logger.info(
                    "scheduler.dag_timeout_applied",
                    timeout_seconds=task_timeout_seconds,
                    dag_timeout_ms=dag_timeout_ms,
                    script_id=str(schedule.script_id),
                )

        batch = TaskBatch(
            org_id=schedule.org_id,
            script_id=schedule.script_id,
            status="running",
            total=len(device_ids),
        )
        db.add(batch)
        await db.flush()

        created_tasks: list[Task] = []
        for did in device_ids:
            # Добавляем служебные маркеры в input_params для отладки и фильтрации в UI.
            # _source / _schedule_id не влияют на выполнение DAG — они
            # только дают возможность отличить задачи планировщика от ручных запусков.
            task_params = dict(schedule.input_params or {})
            task_params.setdefault("_source", "scheduler")
            task_params.setdefault("_schedule_id", str(schedule.id))

            task = Task(
                org_id=schedule.org_id,
                script_id=schedule.script_id,
                script_version_id=script.current_version_id,
                device_id=did,
                batch_id=batch.id,
                status=TaskStatus.QUEUED,
                priority=5,
                timeout_seconds=task_timeout_seconds,
                input_params=task_params,
            )
            db.add(task)
            created_tasks.append(task)

        await db.flush()

        # FIX BUG-1: НЕ enqueue в Redis здесь! Задачи добавляются в pending_enqueue
        # и будут зайнкючены в _tick() ПОСЛЕ db.commit(), чтобы dispatcher
        # гарантированно нашёл их в БД.
        if pending_enqueue is not None:
            for task in created_tasks:
                pending_enqueue.append((
                    str(task.id),
                    str(task.device_id),
                    str(task.org_id),
                    task.priority,
                ))
        else:
            # Fallback: прямой enqueue (для вызовов вне _tick, например fire_now)
            try:
                from backend.database.redis_client import redis_binary
                if redis_binary:
                    from backend.services.task_queue import TaskQueue
                    queue = TaskQueue(redis_binary)
                    for task in created_tasks:
                        await queue.enqueue(
                            str(task.id),
                            str(task.device_id),
                            str(task.org_id),
                            task.priority,
                        )
            except Exception as exc:
                logger.error("scheduler.enqueue_failed", error=str(exc))

        return len(device_ids), batch.id

    async def _create_pipeline_runs(
        self,
        schedule: Schedule,
        device_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> tuple[int, uuid.UUID | None]:
        """Создать PipelineRun для pipeline-расписания."""
        from backend.models.pipeline import Pipeline, PipelineBatch, PipelineRun, PipelineRunStatus

        pipeline = await db.get(Pipeline, schedule.pipeline_id)
        if not pipeline:
            logger.error("scheduler.pipeline_not_found", pipeline_id=str(schedule.pipeline_id))
            return 0, None

        batch = PipelineBatch(
            org_id=schedule.org_id,
            pipeline_id=pipeline.id,
            status="running",
            total=len(device_ids),
            created_by_id=schedule.created_by_id,
        )
        db.add(batch)
        await db.flush()

        for did in device_ids:
            run = PipelineRun(
                org_id=schedule.org_id,
                pipeline_id=pipeline.id,
                device_id=did,
                status=PipelineRunStatus.QUEUED,
                input_params=schedule.input_params or {},
                steps_snapshot=pipeline.steps,
                context={"schedule_id": str(schedule.id), "batch_id": str(batch.id)},
                step_logs=[],
            )
            db.add(run)

        await db.flush()
        return len(device_ids), batch.id

    # Буфер (в секундах) после таймаута задачи, прежде чем считать её «зависшей».
    # Задача с timeout_seconds=N считается зависшей через N + _STALE_BUFFER_SECONDS секунд.
    # Watchdog закроет задачу по timeout_seconds, а буфер даёт запас
    # на сетевую задержку и обработку результата.
    _STALE_BUFFER_SECONDS: int = 600  # 10 мин запас после таймаута

    # Фиксированный порог для pipeline-ов (у них нет per-task timeout_seconds)
    _PIPELINE_STALE_MINUTES: int = 120  # 2 часа

    async def _has_running_tasks(
        self,
        schedule: Schedule,
        db: AsyncSession,
    ) -> bool:
        """
        Проверка: есть ли незавершённые (и не зависшие) задачи от предыдущего запуска.

        Задача считается «зависшей» если прошло timeout_seconds + _STALE_BUFFER_SECONDS
        с момента создания. Watchdog закроет её по timeout, а буфер даёт запас.
        Зависшие задачи не препятствуют запуску нового тика.
        """
        # Проверяем последнюю execution — есть ли у неё незавершённые задачи
        last_exec = await db.scalar(
            select(ScheduleExecution)
            .where(
                ScheduleExecution.schedule_id == schedule.id,
                ScheduleExecution.status == ScheduleExecutionStatus.TRIGGERED,
            )
            .order_by(ScheduleExecution.fire_time.desc())
            .limit(1)
        )
        if not last_exec:
            return False

        # Проверяем задачи batch — динамический порог на основе timeout_seconds задачи
        if last_exec.batch_id:
            from backend.models.task import Task, TaskStatus
            running_count = await db.scalar(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.batch_id == last_exec.batch_id,
                    Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.ASSIGNED]),
                    # Задача НЕ зависшая если: created_at + timeout + buffer > now()
                    Task.created_at + (Task.timeout_seconds + self._STALE_BUFFER_SECONDS)
                    * timedelta(seconds=1) > func.now(),
                )
            )
            return (running_count or 0) > 0

        if last_exec.pipeline_batch_id:
            from backend.models.pipeline import PipelineRun, PipelineRunStatus
            pipeline_stale_cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=self._PIPELINE_STALE_MINUTES
            )
            running_count = await db.scalar(
                select(func.count())
                .select_from(PipelineRun)
                .where(
                    PipelineRun.context["batch_id"].astext == str(last_exec.pipeline_batch_id),
                    PipelineRun.status.in_([
                        PipelineRunStatus.QUEUED,
                        PipelineRunStatus.RUNNING,
                        PipelineRunStatus.WAITING,
                    ]),
                    PipelineRun.created_at > pipeline_stale_cutoff,
                )
            )
            return (running_count or 0) > 0

        return False

    async def _cancel_previous_tasks(
        self,
        schedule: Schedule,
        db: AsyncSession,
    ) -> int:
        """
        Отменить все незавершённые задачи предыдущего запуска расписания.

        Records durable cancellation intent for ASSIGNED/RUNNING work.
        Only never-dispatched QUEUED work becomes terminal immediately.
        Returns the number of accepted requests, not physical stop confirmations.
        """
        cancelled = 0

        # Найти последнее triggered execution
        last_exec = await db.scalar(
            select(ScheduleExecution)
            .where(
                ScheduleExecution.schedule_id == schedule.id,
                ScheduleExecution.org_id == schedule.org_id,
                ScheduleExecution.status == ScheduleExecutionStatus.TRIGGERED,
            )
            .order_by(ScheduleExecution.fire_time.desc())
            .limit(1)
        )
        if not last_exec:
            return 0

        if last_exec.batch_id:
            from backend.models.task import Task, TaskStatus

            # Serialize against result handlers before any queue/stop effect.
            # Refresh identity-map values after waiting; never cancel a committed outcome.
            running_tasks = (
                await db.scalars(
                    select(Task).where(
                        Task.batch_id == last_exec.batch_id,
                        Task.org_id == schedule.org_id,
                        Task.status.in_([
                            TaskStatus.QUEUED,
                            TaskStatus.RUNNING,
                            TaskStatus.ASSIGNED,
                        ]),
                    ).order_by(Task.id).with_for_update().execution_options(populate_existing=True)
                )
            ).all()

            from backend.services.task_service import TaskService

            for task in running_tasks:
                await TaskService(db)._request_cancellation(task)
                cancelled += 1

        if last_exec.pipeline_batch_id:
            from backend.models.pipeline import PipelineRun, PipelineRunStatus

            running_runs = (
                await db.scalars(
                    select(PipelineRun).where(
                        PipelineRun.context["batch_id"].astext == str(last_exec.pipeline_batch_id),
                        PipelineRun.org_id == schedule.org_id,
                        PipelineRun.status.in_([
                            PipelineRunStatus.QUEUED,
                            PipelineRunStatus.RUNNING,
                            PipelineRunStatus.WAITING,
                            PipelineRunStatus.PAUSED,
                        ]),
                    ).order_by(PipelineRun.id).with_for_update().execution_options(populate_existing=True)
                )
            ).all()

            for run in running_runs:
                now = datetime.now(timezone.utc)
                run.cancel_requested_at = run.cancel_requested_at or now
                # Do not acquire Task after PipelineRun. The cancellation
                # reconciler uses Task -> PipelineRun ordering and stops children.
                # A run with no current_task_id can still own an active nested
                # pipeline. Only the reconciler can establish terminality.
                cancelled += 1

        return cancelled

    @staticmethod
    def _advance_fire_time(schedule: Schedule) -> None:
        """Пересчитать next_fire_at после срабатывания."""
        from backend.services.scheduler.schedule_service import ScheduleService
        next_fire = ScheduleService._compute_next_fire(schedule)
        now = datetime.now(timezone.utc)
        if schedule.interval_seconds and next_fire is not None and next_fire <= now:
            period = timedelta(seconds=schedule.interval_seconds)
            # Preserve cadence, skip missed slots, and retain last actual firing.
            next_fire += ((now - next_fire) // period + 1) * period
        schedule.next_fire_at = next_fire
