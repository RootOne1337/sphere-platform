# tests/orchestrator/test_schedule_service.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-5. Unit-тесты ScheduleService.
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schedule import Schedule, ScheduleConflictPolicy, ScheduleTargetType


# ── Фикстуры ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_schedule(db_session: AsyncSession, test_org, test_user, test_script) -> Schedule:
    """Тестовое cron-расписание."""
    schedule = Schedule(
        org_id=test_org.id,
        name="Тестовое расписание",
        description="Запуск каждые 5 мин",
        cron_expression="*/5 * * * *",
        timezone="UTC",
        target_type=ScheduleTargetType.SCRIPT,
        script_id=test_script.id,
        input_params={},
        device_ids=[],
        only_online=True,
        conflict_policy=ScheduleConflictPolicy.SKIP,
        is_active=True,
        created_by_id=test_user.id,
    )
    db_session.add(schedule)
    await db_session.flush()
    return schedule


# ── Тесты ─────────────────────────────────────────────────────────────────────


class TestScheduleService:
    """Unit-тесты CRUD-операций ScheduleService."""

    @pytest.mark.asyncio
    async def test_create_schedule_cron(self, db_session: AsyncSession, test_org, test_user, test_script):
        """Создание cron-расписания — рассчитывает next_fire_at."""
        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        schedule = await svc.create(
            org_id=test_org.id,
            created_by_id=test_user.id,
            name="Cron Test",
            cron_expression="*/10 * * * *",
            timezone="UTC",
            target_type="script",
            script_id=test_script.id,
            input_params={},
            device_ids=[],
            only_online=True,
            conflict_policy="skip",
        )
        await db_session.flush()

        assert schedule.id is not None
        assert schedule.name == "Cron Test"
        assert schedule.cron_expression == "*/10 * * * *"
        assert schedule.next_fire_at is not None
        assert schedule.is_active is True

    @pytest.mark.asyncio
    async def test_create_schedule_interval(self, db_session: AsyncSession, test_org, test_user, test_script):
        """Создание interval-расписания."""
        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        schedule = await svc.create(
            org_id=test_org.id,
            created_by_id=test_user.id,
            name="Interval Test",
            interval_seconds=300,
            timezone="UTC",
            target_type="script",
            script_id=test_script.id,
            input_params={},
            device_ids=[],
            only_online=False,
            conflict_policy="queue",
        )
        await db_session.flush()

        assert schedule.interval_seconds == 300
        assert schedule.next_fire_at is not None

    @pytest.mark.asyncio
    async def test_create_schedule_one_shot(self, db_session: AsyncSession, test_org, test_user, test_script):
        """Создание one-shot расписания."""
        from backend.services.scheduler.schedule_service import ScheduleService

        fire_at = datetime.now(timezone.utc) + timedelta(hours=1)
        svc = ScheduleService(db_session)
        schedule = await svc.create(
            org_id=test_org.id,
            created_by_id=test_user.id,
            name="One Shot Test",
            one_shot_at=fire_at,
            timezone="UTC",
            target_type="script",
            script_id=test_script.id,
            input_params={},
            device_ids=[],
            only_online=False,
            conflict_policy="skip",
        )
        await db_session.flush()

        assert schedule.one_shot_at == fire_at
        assert schedule.next_fire_at is not None

    @pytest.mark.asyncio
    async def test_get_schedule(self, db_session: AsyncSession, test_org, test_schedule):
        """Получение расписания по ID."""
        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        fetched = await svc.get(test_schedule.id, test_org.id)
        assert fetched.id == test_schedule.id

    @pytest.mark.asyncio
    async def test_get_schedule_wrong_org(self, db_session: AsyncSession, test_schedule):
        """Попытка получить чужое расписание → 404."""
        from fastapi import HTTPException

        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await svc.get(test_schedule.id, uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_schedules(self, db_session: AsyncSession, test_org, test_schedule):
        """Список расписаний организации."""
        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        items, total = await svc.list_schedules(test_org.id)
        assert total >= 1
        assert any(s.id == test_schedule.id for s in items)

    @pytest.mark.asyncio
    async def test_toggle_deactivate(self, db_session: AsyncSession, test_org, test_schedule):
        """Выключение расписания сбрасывает next_fire_at."""
        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        schedule = await svc.toggle(test_schedule.id, test_org.id, active=False)
        assert schedule.is_active is False
        assert schedule.next_fire_at is None

    @pytest.mark.asyncio
    async def test_toggle_activate(self, db_session: AsyncSession, test_org, test_schedule):
        """Включение расписания рассчитывает next_fire_at."""
        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        await svc.toggle(test_schedule.id, test_org.id, active=False)
        schedule = await svc.toggle(test_schedule.id, test_org.id, active=True)
        assert schedule.is_active is True
        assert schedule.next_fire_at is not None

    @pytest.mark.asyncio
    async def test_delete_deactivates(self, db_session: AsyncSession, test_org, test_schedule):
        """Удаление (деактивация) расписания."""
        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        await svc.delete(test_schedule.id, test_org.id)
        await db_session.flush()
        assert test_schedule.is_active is False
        assert test_schedule.next_fire_at is None

    @pytest.mark.asyncio
    async def test_fire_now(self, db_session: AsyncSession, test_org, test_schedule):
        """Принудительное срабатывание устанавливает next_fire_at = now."""
        from backend.services.scheduler.schedule_service import ScheduleService

        svc = ScheduleService(db_session)
        before = datetime.now(timezone.utc)
        schedule = await svc.fire_now(test_schedule.id, test_org.id)
        assert schedule.next_fire_at is not None
        assert schedule.next_fire_at >= before


class TestScheduleServiceCompute:
    """Тесты _compute_next_fire (статический метод)."""

    @pytest.mark.asyncio
    async def test_compute_cron(self, db_session: AsyncSession, test_org, test_script, test_user):
        """Cron '*/5 * * * *' → next_fire в пределах 5 минут."""
        from backend.services.scheduler.schedule_service import ScheduleService

        schedule = Schedule(
            org_id=test_org.id,
            name="test",
            cron_expression="*/5 * * * *",
            timezone="UTC",
            target_type=ScheduleTargetType.SCRIPT,
            script_id=test_script.id,
            conflict_policy=ScheduleConflictPolicy.SKIP,
        )
        result = ScheduleService._compute_next_fire(schedule)
        assert result is not None
        diff = result - datetime.now(timezone.utc)
        assert diff.total_seconds() <= 300  # ≤ 5 минут

    @pytest.mark.asyncio
    async def test_compute_interval(self, db_session: AsyncSession, test_org, test_script):
        """Interval 600 сек → next_fire через ~600 секунд от now."""
        from backend.services.scheduler.schedule_service import ScheduleService

        schedule = Schedule(
            org_id=test_org.id,
            name="test",
            interval_seconds=600,
            timezone="UTC",
            target_type=ScheduleTargetType.SCRIPT,
            script_id=test_script.id,
            conflict_policy=ScheduleConflictPolicy.SKIP,
        )
        result = ScheduleService._compute_next_fire(schedule)
        assert result is not None
        diff = result - datetime.now(timezone.utc)
        assert 590 <= diff.total_seconds() <= 610

    @pytest.mark.asyncio
    async def test_compute_one_shot_future(self, db_session: AsyncSession, test_org, test_script):
        """One-shot в будущем → вернуть as-is."""
        from backend.services.scheduler.schedule_service import ScheduleService

        fire_at = datetime.now(timezone.utc) + timedelta(hours=2)
        schedule = Schedule(
            org_id=test_org.id,
            name="test",
            one_shot_at=fire_at,
            timezone="UTC",
            target_type=ScheduleTargetType.SCRIPT,
            script_id=test_script.id,
            conflict_policy=ScheduleConflictPolicy.SKIP,
        )
        result = ScheduleService._compute_next_fire(schedule)
        assert result == fire_at

    @pytest.mark.asyncio
    async def test_compute_one_shot_past(self, db_session: AsyncSession, test_org, test_script):
        """One-shot в прошлом → None."""
        from backend.services.scheduler.schedule_service import ScheduleService

        fire_at = datetime.now(timezone.utc) - timedelta(hours=1)
        schedule = Schedule(
            org_id=test_org.id,
            name="test",
            one_shot_at=fire_at,
            timezone="UTC",
            target_type=ScheduleTargetType.SCRIPT,
            script_id=test_script.id,
            conflict_policy=ScheduleConflictPolicy.SKIP,
        )
        result = ScheduleService._compute_next_fire(schedule)
        assert result is None
