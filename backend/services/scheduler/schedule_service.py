# backend/services/scheduler/schedule_service.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-5. CRUD-сервис для расписаний.
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import pytz
import structlog
from croniter import croniter
from fastapi import HTTPException
from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.pipeline import PipelineRun, PipelineRunStatus
from backend.models.schedule import (
    Schedule,
    ScheduleExecution,
    ScheduleExecutionStatus,
    ScheduleFireRequest,
)
from backend.models.task import Task, TaskStatus
from backend.schemas.schedule import ScheduleExecutionResponse
from backend.services.scheduler.schedule_timing import advance_schedule_revision, next_schedule_slot

logger = structlog.get_logger()
_TRIGGER_FIELDS = {"cron_expression", "interval_seconds", "one_shot_at"}
_TIMING_FIELDS = _TRIGGER_FIELDS | {"timezone", "active_from", "active_until", "is_active", "max_runs"}
_FIRE_KEY_LIFETIME = timedelta(hours=24)
_MAX_FIRE_KEYS_PER_SCHEDULE = 256


class ScheduleService:
    """
    CRUD-сервис управления расписаниями.

    Создание, обновление, удаление расписаний, а также
    расчёт next_fire_at через croniter.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── CRUD ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_jsonb_uuids(fields: dict[str, Any]) -> dict[str, Any]:
        """Конвертирует UUID-объекты в str для JSONB-полей (device_ids).

        JSONB-колонки сериализуются через json.dumps(), который не поддерживает
        uuid.UUID. Pydantic model_dump() возвращает UUID-объекты — нужна
        промежуточная нормализация.
        """
        if "device_ids" in fields and fields["device_ids"] is not None:
            fields["device_ids"] = [str(d) for d in fields["device_ids"]]
        return fields

    async def create(
        self,
        org_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
        **fields: Any,
    ) -> Schedule:
        """Создать расписание и рассчитать next_fire_at."""
        self._normalize_jsonb_uuids(fields)
        schedule = Schedule(
            org_id=org_id,
            created_by_id=created_by_id,
            **fields,
        )
        self._validate_timing(schedule, check_timezone=True, check_cron=True)
        schedule.next_fire_at = self._compute_next_fire(schedule)
        self.db.add(schedule)
        await self.db.flush()
        logger.info(
            "schedule.created",
            schedule_id=str(schedule.id),
            name=schedule.name,
            next_fire_at=str(schedule.next_fire_at),
        )
        return schedule

    async def get(self, schedule_id: uuid.UUID, org_id: uuid.UUID, *, for_update: bool = False) -> Schedule:
        """Получить расписание по ID."""
        query = select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        schedule = await self.db.scalar(query)
        if not schedule:
            raise HTTPException(status_code=404, detail="Расписание не найдено")
        return schedule

    @staticmethod
    def _check_revision(schedule: Schedule, expected_updated_at: datetime | None) -> None:
        if expected_updated_at is not None and expected_updated_at != ScheduleService._as_utc(schedule.updated_at):
            raise HTTPException(409, "schedule_revision_conflict")

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    def _touch_modified(self, schedule: Schedule) -> None:
        if self.db.is_modified(schedule):
            schedule.updated_at = advance_schedule_revision(schedule.updated_at)

    async def list_schedules(
        self,
        org_id: uuid.UUID,
        *,
        is_active: bool | None = None,
        target_type: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Schedule], int]:
        """Список расписаний с фильтрацией и пагинацией."""
        base = select(Schedule).where(Schedule.org_id == org_id)
        count_q = select(func.count()).select_from(Schedule).where(Schedule.org_id == org_id)

        if is_active is not None:
            base = base.where(Schedule.is_active == is_active)
            count_q = count_q.where(Schedule.is_active == is_active)
        if target_type is not None:
            base = base.where(Schedule.target_type == target_type)
            count_q = count_q.where(Schedule.target_type == target_type)

        total = await self.db.scalar(count_q) or 0
        items = (
            await self.db.scalars(
                base.order_by(Schedule.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
        return list(items), total

    async def update(
        self,
        schedule_id: uuid.UUID,
        org_id: uuid.UUID,
        *,
        expected_updated_at: datetime | None = None,
        **fields: Any,
    ) -> Schedule:
        """Частичное обновление расписания. Пересчитывает next_fire_at."""
        schedule = await self.get(schedule_id, org_id, for_update=True)
        self._check_revision(schedule, expected_updated_at)
        previous_timing = {key: getattr(schedule, key) for key in _TIMING_FIELDS}

        if any(key in fields and fields[key] is None for key in (
            "name", "timezone", "target_type", "input_params", "only_online", "conflict_policy", "is_active",
        )):
            raise HTTPException(422, "Обязательное поле расписания нельзя очистить")

        # Если меняется триггер — очистить конкурирующие
        # Определяем, какие триггеры устанавливаются (не-None).
        # Остальные триггеры обнуляем — CHECK-constraint ck_schedules_has_trigger
        # требует ровно один заполненный триггер.
        active_triggers = {key for key in _TRIGGER_FIELDS if fields.get(key) is not None}
        if active_triggers:
            for tf in _TRIGGER_FIELDS - active_triggers:
                setattr(schedule, tf, None)

        self._normalize_jsonb_uuids(fields)
        for key, value in fields.items():
            if not hasattr(schedule, key):
                continue
            # Явно переданный None — очистка поля (exclude_unset=True
            # гарантирует, что в dict попадают только заданные поля)
            setattr(schedule, key, value)

        if _TIMING_FIELDS.intersection(fields):
            self._validate_timing(
                schedule, check_timezone="timezone" in fields, check_cron="cron_expression" in fields,
            )
            if any(getattr(schedule, key) != value for key, value in previous_timing.items()):
                await self._replace_next_fire(schedule, self._compute_next_fire(schedule))
        self._touch_modified(schedule)
        await self.db.flush()
        logger.info(
            "schedule.updated",
            schedule_id=str(schedule_id),
            next_fire_at=str(schedule.next_fire_at),
        )
        return schedule

    async def delete(
        self, schedule_id: uuid.UUID, org_id: uuid.UUID, *, expected_updated_at: datetime | None = None,
    ) -> None:
        """Мягкое удаление — деактивация."""
        schedule = await self.get(schedule_id, org_id, for_update=True)
        self._check_revision(schedule, expected_updated_at)
        schedule.is_active = False
        await self._replace_next_fire(schedule, None)
        self._touch_modified(schedule)
        await self.db.flush()
        logger.info("schedule.deactivated", schedule_id=str(schedule_id))

    async def toggle(
        self, schedule_id: uuid.UUID, org_id: uuid.UUID, active: bool, *, expected_updated_at: datetime | None = None,
    ) -> Schedule:
        """Включить / выключить расписание."""
        schedule = await self.get(schedule_id, org_id, for_update=True)
        self._check_revision(schedule, expected_updated_at)
        if schedule.is_active == active:
            return schedule
        schedule.is_active = active
        await self._replace_next_fire(schedule, self._compute_next_fire(schedule) if active else None)
        self._touch_modified(schedule)
        await self.db.flush()
        logger.info("schedule.toggled", schedule_id=str(schedule_id), is_active=active)
        return schedule

    async def _replace_next_fire(self, schedule: Schedule, replacement: datetime | None) -> None:
        """Record the outcome of a superseded manual slot under the schedule row lock."""
        previous = schedule.next_fire_at
        if previous == replacement:
            return
        if previous is not None:
            requested = select(ScheduleFireRequest.request_key).where(
                ScheduleFireRequest.org_id == schedule.org_id,
                ScheduleFireRequest.schedule_id == schedule.id,
                ScheduleFireRequest.fire_at == previous,
            ).exists()
            already_recorded = select(ScheduleExecution.id).where(
                ScheduleExecution.org_id == schedule.org_id,
                ScheduleExecution.schedule_id == schedule.id,
                ScheduleExecution.fire_time == previous,
            ).exists()
            with self.db.no_autoflush:
                has_pending_request = await self.db.scalar(select(requested & ~already_recorded))
            if has_pending_request:
                now = datetime.now(timezone.utc)
                self.db.add(ScheduleExecution(
                    schedule_id=schedule.id,
                    org_id=schedule.org_id,
                    status=ScheduleExecutionStatus.SKIPPED,
                    fire_time=previous,
                    actual_time=now,
                    finished_at=now,
                    skip_reason=(
                        "Настройки расписания изменились до запуска"
                        if schedule.is_active else "Расписание выключено до запуска"
                    ),
                ))
        schedule.next_fire_at = replacement

    async def fire_now(self, schedule_id: uuid.UUID, org_id: uuid.UUID) -> Schedule:
        """Queue an unkeyed request for existing callers."""
        schedule, _, _ = await self.request_fire(schedule_id, org_id)
        return schedule

    async def request_fire(
        self, schedule_id: uuid.UUID, org_id: uuid.UUID, request_key: uuid.UUID | None = None,
        *, expected_updated_at: datetime | None = None,
    ) -> tuple[Schedule, datetime, bool]:
        """Remember a keyed receipt in the same transaction as its requested slot."""
        schedule = await self.get(schedule_id, org_id, for_update=True)
        now = datetime.now(timezone.utc)
        scope = (
            ScheduleFireRequest.org_id == org_id,
            ScheduleFireRequest.schedule_id == schedule_id,
        )
        if request_key is not None:
            existing = await self.db.scalar(select(ScheduleFireRequest).where(
                *scope, ScheduleFireRequest.request_key == request_key,
            ))
            if existing is not None and existing.expires_at > now:
                return schedule, existing.fire_at, True
        self._check_revision(schedule, expected_updated_at)
        if not schedule.is_active:
            raise HTTPException(409, "Включите расписание перед запуском")
        if (schedule.active_from and now < schedule.active_from) or (schedule.active_until and now > schedule.active_until):
            raise HTTPException(409, "Сейчас расписание вне окна активности")
        if schedule.max_runs is not None and schedule.total_runs >= schedule.max_runs:
            raise HTTPException(409, "Лимит запусков расписания исчерпан")
        due_at = schedule.next_fire_at
        if due_at is None or due_at > now:
            due_at = now
        if request_key is not None:
            await self.db.execute(delete(ScheduleFireRequest).where(*scope, ScheduleFireRequest.expires_at <= now))
            count = await self.db.scalar(select(func.count()).select_from(ScheduleFireRequest).where(*scope)) or 0
            if count >= _MAX_FIRE_KEYS_PER_SCHEDULE:
                raise HTTPException(429, "Лимит запросов расписания исчерпан. Повторите позже")
            self.db.add(ScheduleFireRequest(
                org_id=org_id, schedule_id=schedule_id, request_key=request_key,
                fire_at=due_at, expires_at=now + _FIRE_KEY_LIFETIME,
            ))
        schedule.next_fire_at = due_at
        self._touch_modified(schedule)
        await self.db.flush()
        logger.debug("schedule.fire_now", schedule_id=str(schedule_id), keyed=request_key is not None)
        return schedule, due_at, False

    # ── Executions ───────────────────────────────────────────────────────────

    async def list_executions(
        self,
        schedule_id: uuid.UUID,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[ScheduleExecutionResponse], int]:
        """Список срабатываний расписания."""
        # Проверить принадлежность
        await self.get(schedule_id, org_id)

        base = (
            select(ScheduleExecution)
            .where(ScheduleExecution.schedule_id == schedule_id, ScheduleExecution.org_id == org_id)
        )
        count_q = (
            select(func.count())
            .select_from(ScheduleExecution)
            .where(ScheduleExecution.schedule_id == schedule_id, ScheduleExecution.org_id == org_id)
        )

        total = await self.db.scalar(count_q) or 0
        items = (
            await self.db.scalars(
                base.order_by(ScheduleExecution.fire_time.desc(), ScheduleExecution.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
        return await self._project_execution_results(items, org_id), total

    async def _project_execution_results(
        self, executions: Sequence[ScheduleExecution], org_id: uuid.UUID,
    ) -> list[ScheduleExecutionResponse]:
        task_ids = {row.batch_id for row in executions if row.batch_id is not None}
        pipeline_ids = {str(row.pipeline_batch_id) for row in executions if row.pipeline_batch_id is not None}
        results: dict[str, tuple[int, int, datetime | None]] = {}
        if task_ids:
            batch = cast(Task.batch_id, String)
            rows = await self.db.execute(select(
                batch,
                func.count().filter(Task.status == TaskStatus.COMPLETED),
                func.count().filter(Task.status.in_((TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED))),
                func.max(Task.finished_at),
            ).where(Task.org_id == org_id, Task.batch_id.in_(task_ids)).group_by(batch))
            results.update((key, (succeeded, failed, finished)) for key, succeeded, failed, finished in rows)
        if pipeline_ids:
            batch = PipelineRun.context["batch_id"].astext
            rows = await self.db.execute(select(
                batch,
                func.count().filter(PipelineRun.status == PipelineRunStatus.COMPLETED),
                func.count().filter(PipelineRun.status.in_(
                    (PipelineRunStatus.FAILED, PipelineRunStatus.TIMED_OUT, PipelineRunStatus.CANCELLED),
                )),
                func.max(PipelineRun.finished_at),
            ).where(PipelineRun.org_id == org_id, batch.in_(pipeline_ids)).group_by(batch))
            results.update((key, (succeeded, failed, finished)) for key, succeeded, failed, finished in rows)

        responses = []
        for execution in executions:
            response = ScheduleExecutionResponse.model_validate(execution)
            result = results.get(str(execution.batch_id or execution.pipeline_batch_id))
            if result is not None and response.status == ScheduleExecutionStatus.TRIGGERED:
                succeeded, failed, finished = result
                response.tasks_succeeded = succeeded
                response.tasks_failed = failed
                if response.tasks_created > 0 and succeeded + failed == response.tasks_created:
                    response.status = (
                        ScheduleExecutionStatus.COMPLETED if failed == 0
                        else ScheduleExecutionStatus.FAILED if succeeded == 0
                        else ScheduleExecutionStatus.PARTIAL
                    )
                    response.finished_at = finished
            responses.append(response)
        return responses

    # ── Вспомогательные ──────────────────────────────────────────────────────

    @staticmethod
    def _validate_timing(schedule: Schedule, *, check_timezone: bool, check_cron: bool) -> None:
        if sum(getattr(schedule, key) is not None for key in _TRIGGER_FIELDS) != 1:
            raise HTTPException(422, "Укажите ровно один триггер расписания")
        if check_timezone and schedule.timezone not in pytz.all_timezones_set:
            raise HTTPException(422, "Укажите часовой пояс IANA")
        expression = schedule.cron_expression
        if check_cron and expression is not None and (
            len(expression.split()) != 5 or not croniter.is_valid(expression)
        ):
            raise HTTPException(422, "Некорректное cron-выражение из пяти полей")
        if schedule.active_from and schedule.active_until and schedule.active_from > schedule.active_until:
            raise HTTPException(422, "Начало окна активности позже его окончания")

    @staticmethod
    def _compute_next_fire(schedule: Schedule) -> datetime | None:
        """Choose the next eligible slot from the current time."""
        now = datetime.now(timezone.utc)
        return next_schedule_slot(schedule, now, interval_anchor=schedule.last_fired_at or now)
