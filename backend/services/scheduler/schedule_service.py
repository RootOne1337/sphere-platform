# backend/services/scheduler/schedule_service.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-5. CRUD-сервис для расписаний.
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from croniter import croniter
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schedule import (
    Schedule,
    ScheduleConflictPolicy,
    ScheduleExecution,
    ScheduleTargetType,
)

logger = structlog.get_logger()


class ScheduleService:
    """
    CRUD-сервис управления расписаниями.

    Создание, обновление, удаление расписаний, а также
    расчёт next_fire_at через croniter.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def create(
        self,
        org_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
        **fields: Any,
    ) -> Schedule:
        """Создать расписание и рассчитать next_fire_at."""
        schedule = Schedule(
            org_id=org_id,
            created_by_id=created_by_id,
            **fields,
        )
        # Рассчитать first fire
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

    async def get(self, schedule_id: uuid.UUID, org_id: uuid.UUID) -> Schedule:
        """Получить расписание по ID."""
        schedule = await self.db.scalar(
            select(Schedule).where(
                Schedule.id == schedule_id,
                Schedule.org_id == org_id,
            )
        )
        if not schedule:
            raise HTTPException(status_code=404, detail="Расписание не найдено")
        return schedule

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
        **fields: Any,
    ) -> Schedule:
        """Частичное обновление расписания. Пересчитывает next_fire_at."""
        schedule = await self.get(schedule_id, org_id)

        # Если меняется триггер — очистить другие
        trigger_fields = {"cron_expression", "interval_seconds", "one_shot_at"}
        changing_triggers = trigger_fields & set(fields.keys())
        if changing_triggers:
            for tf in trigger_fields - changing_triggers:
                if fields.get(tf) is None:
                    setattr(schedule, tf, None)

        for key, value in fields.items():
            if value is not None and hasattr(schedule, key):
                setattr(schedule, key, value)

        # Пересчитать next_fire_at
        schedule.next_fire_at = self._compute_next_fire(schedule)
        await self.db.flush()
        logger.info(
            "schedule.updated",
            schedule_id=str(schedule_id),
            next_fire_at=str(schedule.next_fire_at),
        )
        return schedule

    async def delete(self, schedule_id: uuid.UUID, org_id: uuid.UUID) -> None:
        """Мягкое удаление — деактивация."""
        schedule = await self.get(schedule_id, org_id)
        schedule.is_active = False
        schedule.next_fire_at = None
        await self.db.flush()
        logger.info("schedule.deactivated", schedule_id=str(schedule_id))

    async def toggle(self, schedule_id: uuid.UUID, org_id: uuid.UUID, active: bool) -> Schedule:
        """Включить / выключить расписание."""
        schedule = await self.get(schedule_id, org_id)
        schedule.is_active = active
        if active:
            schedule.next_fire_at = self._compute_next_fire(schedule)
        else:
            schedule.next_fire_at = None
        await self.db.flush()
        logger.info("schedule.toggled", schedule_id=str(schedule_id), is_active=active)
        return schedule

    async def fire_now(self, schedule_id: uuid.UUID, org_id: uuid.UUID) -> Schedule:
        """Принудительное срабатывание — установить next_fire_at = now."""
        schedule = await self.get(schedule_id, org_id)
        schedule.next_fire_at = datetime.now(timezone.utc)
        await self.db.flush()
        logger.info("schedule.fire_now", schedule_id=str(schedule_id))
        return schedule

    # ── Executions ───────────────────────────────────────────────────────────

    async def list_executions(
        self,
        schedule_id: uuid.UUID,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[ScheduleExecution], int]:
        """Список срабатываний расписания."""
        # Проверить принадлежность
        await self.get(schedule_id, org_id)

        base = (
            select(ScheduleExecution)
            .where(ScheduleExecution.schedule_id == schedule_id)
        )
        count_q = (
            select(func.count())
            .select_from(ScheduleExecution)
            .where(ScheduleExecution.schedule_id == schedule_id)
        )

        total = await self.db.scalar(count_q) or 0
        items = (
            await self.db.scalars(
                base.order_by(ScheduleExecution.fire_time.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
        return list(items), total

    # ── Вспомогательные ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_next_fire(schedule: Schedule) -> datetime | None:
        """
        Рассчитать следующее время срабатывания.

        - cron_expression → croniter.get_next()
        - interval_seconds → last_fired + interval (или now + interval)
        - one_shot_at → возвращаем as-is если в будущем
        """
        now = datetime.now(timezone.utc)

        if schedule.cron_expression:
            try:
                import pytz
                tz = pytz.timezone(schedule.timezone or "UTC")
            except Exception:
                tz = pytz.UTC
            local_now = now.astimezone(tz)
            cron = croniter(schedule.cron_expression, local_now)
            next_local = cron.get_next(datetime)
            return next_local.astimezone(timezone.utc)

        if schedule.interval_seconds:
            base_time = schedule.last_fired_at or now
            from datetime import timedelta
            return base_time + timedelta(seconds=schedule.interval_seconds)

        if schedule.one_shot_at:
            if schedule.one_shot_at > now:
                return schedule.one_shot_at
            return None  # Уже прошло

        return None
