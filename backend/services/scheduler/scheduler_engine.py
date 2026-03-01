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
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import AsyncSessionLocal
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


class SchedulerEngine:
    """
    Фоновый движок расписаний.

    Поллит таблицу schedules, находит «созревшие» записи
    (next_fire_at <= NOW()), и запускает соответствующие задачи.
    """

    def __init__(self) -> None:
        self._running = False

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

    async def _tick(self) -> None:
        """Один тик: найти созревшие расписания и обработать."""
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Schedule)
                .where(
                    Schedule.is_active.is_(True),
                    Schedule.next_fire_at <= now,
                )
                .order_by(Schedule.next_fire_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
            schedules = result.scalars().all()

            for schedule in schedules:
                try:
                    await self._process_schedule(schedule, now, db)
                except Exception as exc:
                    logger.error(
                        "scheduler_engine.schedule_error",
                        schedule_id=str(schedule.id),
                        error=str(exc),
                    )

            await db.commit()

    async def _process_schedule(
        self,
        schedule: Schedule,
        fire_time: datetime,
        db: AsyncSession,
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
                schedule, device_ids, db,
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

        # Фильтр only_online — проверяем через Redis кэш
        if schedule.only_online and result:
            try:
                from backend.database.redis_client import redis_binary
                if redis_binary:
                    from backend.services.device_status_cache import DeviceStatusCache
                    cache = DeviceStatusCache(redis_binary)
                    online_ids = set()
                    for did in result:
                        status = await cache.get_status(str(did))
                        if status and status.status == "online":
                            online_ids.add(did)
                    return list(online_ids)
            except Exception as exc:
                logger.warning("scheduler.online_check_failed", error=str(exc))

        return list(result)

    async def _create_script_tasks(
        self,
        schedule: Schedule,
        device_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> tuple[int, uuid.UUID | None]:
        """Создать задачи (Task) для script-расписания с enqueue в Redis."""
        from backend.models.script import Script
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
            task = Task(
                org_id=schedule.org_id,
                script_id=schedule.script_id,
                script_version_id=script.current_version_id,
                device_id=did,
                batch_id=batch.id,
                status=TaskStatus.QUEUED,
                priority=5,
                input_params=schedule.input_params or {},
            )
            db.add(task)
            created_tasks.append(task)

        await db.flush()

        # Enqueue в Redis для диспетчеризации TaskService.dispatch_pending_tasks
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

    async def _has_running_tasks(
        self,
        schedule: Schedule,
        db: AsyncSession,
    ) -> bool:
        """Проверка: есть ли незавершённые задачи от предыдущего запуска."""
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

        # Проверяем задачи batch
        if last_exec.batch_id:
            from backend.models.task import Task, TaskStatus
            running_count = await db.scalar(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.batch_id == last_exec.batch_id,
                    Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.ASSIGNED]),
                )
            )
            return (running_count or 0) > 0

        if last_exec.pipeline_batch_id:
            from backend.models.pipeline import PipelineRun, PipelineRunStatus
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

        Для RUNNING задач отправляет CANCEL_DAG через WebSocket агенту.
        Для QUEUED/ASSIGNED — отменяет из Redis-очереди.
        Возвращает количество отменённых задач.
        """
        cancelled = 0

        # Найти последнее triggered execution
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
            return 0

        now = datetime.now(timezone.utc)

        if last_exec.batch_id:
            from backend.models.task import Task, TaskStatus

            running_tasks = (
                await db.scalars(
                    select(Task).where(
                        Task.batch_id == last_exec.batch_id,
                        Task.status.in_([
                            TaskStatus.QUEUED,
                            TaskStatus.RUNNING,
                            TaskStatus.ASSIGNED,
                        ]),
                    )
                )
            ).all()

            # Получить publisher и queue для отмены
            publisher = None
            queue = None
            try:
                from backend.database.redis_client import redis_binary
                if redis_binary:
                    from backend.websocket.pubsub_router import get_pubsub_publisher
                    from backend.services.task_queue import TaskQueue
                    publisher = get_pubsub_publisher()
                    queue = TaskQueue(redis_binary)
            except Exception as exc:
                logger.warning("scheduler.cancel_deps_failed", error=str(exc))

            for task in running_tasks:
                try:
                    if task.status == TaskStatus.RUNNING and publisher:
                        # Отправить CANCEL_DAG агенту через WebSocket
                        await publisher.send_command_live(
                            str(task.device_id),
                            {
                                "command_id": str(task.id),
                                "type": "CANCEL_DAG",
                                "signed_at": int(now.timestamp()),
                                "payload": {"task_id": str(task.id)},
                            },
                        )

                    if task.status in (TaskStatus.QUEUED, TaskStatus.ASSIGNED) and queue:
                        await queue.cancel_task(str(task.id), str(task.org_id))

                    # Освободить running lock
                    if queue:
                        await queue.mark_completed(str(task.id), str(task.device_id))

                    task.status = TaskStatus.CANCELLED
                    task.finished_at = now
                    task.error_message = "Отменено планировщиком (conflict_policy=cancel)"
                    cancelled += 1

                    logger.info(
                        "scheduler.task_cancelled",
                        task_id=str(task.id),
                        device_id=str(task.device_id),
                    )
                except Exception as exc:
                    logger.error(
                        "scheduler.cancel_task_error",
                        task_id=str(task.id),
                        error=str(exc),
                    )

        if last_exec.pipeline_batch_id:
            from backend.models.pipeline import PipelineRun, PipelineRunStatus

            running_runs = (
                await db.scalars(
                    select(PipelineRun).where(
                        PipelineRun.context["batch_id"].astext == str(last_exec.pipeline_batch_id),
                        PipelineRun.status.in_([
                            PipelineRunStatus.QUEUED,
                            PipelineRunStatus.RUNNING,
                            PipelineRunStatus.WAITING,
                        ]),
                    )
                )
            ).all()

            for run in running_runs:
                run.status = PipelineRunStatus.CANCELLED
                run.finished_at = now
                cancelled += 1

        return cancelled

    @staticmethod
    def _advance_fire_time(schedule: Schedule) -> None:
        """Пересчитать next_fire_at после срабатывания."""
        from backend.services.scheduler.schedule_service import ScheduleService
        schedule.next_fire_at = ScheduleService._compute_next_fire(schedule)
