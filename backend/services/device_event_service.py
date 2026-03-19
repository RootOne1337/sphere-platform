# backend/services/device_event_service.py
# ВЛАДЕЛЕЦ: TZ-11 Device Events — сервис для работы с персистентными событиями устройств.
# Отвечает за: создание событий, фильтрация, статистика, пометка обработанных.
# НЕ делает commit() — это ответственность вызывающего (router или EventReactor).
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device_event import DeviceEvent, EventSeverity
from backend.schemas.device_events import (
    CreateDeviceEventRequest,
    DeviceEventResponse,
    EventStatsResponse,
)

logger = structlog.get_logger()


class DeviceEventService:
    """Сервис управления событиями устройств."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Helpers ──────────────────────────────────────────────────────────

    def _to_response(self, event: DeviceEvent) -> DeviceEventResponse:
        """ORM → Pydantic response."""
        device_name = None
        if event.device:
            device_name = event.device.name
        account_login = None
        if event.account:
            account_login = event.account.login
        return DeviceEventResponse(
            id=event.id,
            org_id=event.org_id,
            device_id=event.device_id,
            device_name=device_name,
            event_type=event.event_type,
            severity=event.severity.value if isinstance(event.severity, EventSeverity) else str(event.severity),
            message=event.message,
            account_id=event.account_id,
            account_login=account_login,
            task_id=event.task_id,
            pipeline_run_id=event.pipeline_run_id,
            data=event.data,
            occurred_at=event.occurred_at,
            processed=event.processed,
            created_at=event.created_at,
            updated_at=event.updated_at,
        )

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def create_event(
        self,
        org_id: uuid.UUID,
        data: CreateDeviceEventRequest,
    ) -> DeviceEventResponse:
        """Создать новое событие."""
        event = DeviceEvent(
            org_id=org_id,
            device_id=data.device_id,
            event_type=data.event_type,
            severity=EventSeverity(data.severity),
            message=data.message,
            account_id=data.account_id,
            task_id=data.task_id,
            pipeline_run_id=data.pipeline_run_id,
            data=data.data,
            occurred_at=data.occurred_at or datetime.now(timezone.utc),
            processed=False,
        )
        self.db.add(event)
        await self.db.flush()

        logger.info(
            "device_event.created",
            event_id=str(event.id),
            event_type=data.event_type,
            severity=data.severity,
            device_id=str(data.device_id),
        )
        return self._to_response(event)

    async def create_event_internal(
        self,
        org_id: uuid.UUID,
        device_id: uuid.UUID,
        event_type: str,
        severity: str = "info",
        message: str | None = None,
        account_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        pipeline_run_id: uuid.UUID | None = None,
        data: dict | None = None,
    ) -> DeviceEvent:
        """
        Создать событие из внутреннего кода (EventReactor, pipeline итд).

        Возвращает ORM-объект (не Pydantic) для дальнейшей обработки.
        """
        event = DeviceEvent(
            org_id=org_id,
            device_id=device_id,
            event_type=event_type,
            severity=EventSeverity(severity),
            message=message,
            account_id=account_id,
            task_id=task_id,
            pipeline_run_id=pipeline_run_id,
            data=data or {},
            occurred_at=datetime.now(timezone.utc),
            processed=False,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_events(
        self,
        org_id: uuid.UUID,
        device_id: uuid.UUID | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        account_id: uuid.UUID | None = None,
        processed: bool | None = None,
        search: str | None = None,
        sort_by: str = "occurred_at",
        sort_dir: str = "desc",
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[DeviceEventResponse], int]:
        """Пагинированный список событий с фильтрами."""
        conditions = [DeviceEvent.org_id == org_id]

        if device_id:
            conditions.append(DeviceEvent.device_id == device_id)
        if event_type:
            conditions.append(DeviceEvent.event_type == event_type)
        if severity:
            try:
                conditions.append(DeviceEvent.severity == EventSeverity(severity))
            except ValueError:
                pass
        if account_id:
            conditions.append(DeviceEvent.account_id == account_id)
        if processed is not None:
            conditions.append(DeviceEvent.processed == processed)
        if search:
            like = f"%{search}%"
            conditions.append(
                or_(
                    DeviceEvent.event_type.ilike(like),
                    DeviceEvent.message.ilike(like),
                )
            )

        # Сортировка (белый список)
        sort_columns = {
            "occurred_at": DeviceEvent.occurred_at,
            "created_at": DeviceEvent.created_at,
            "event_type": DeviceEvent.event_type,
            "severity": DeviceEvent.severity,
        }
        sort_col = sort_columns.get(sort_by, DeviceEvent.occurred_at)
        order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

        # Count
        count_stmt = select(func.count()).select_from(DeviceEvent).where(*conditions)
        total = (await self.db.execute(count_stmt)).scalar_one()

        # Data
        stmt = (
            select(DeviceEvent)
            .where(*conditions)
            .order_by(order)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(stmt)).scalars().all()

        return [self._to_response(e) for e in rows], total

    async def get_event(
        self,
        event_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> DeviceEventResponse:
        """Получить одно событие по ID."""
        from fastapi import HTTPException

        stmt = select(DeviceEvent).where(
            DeviceEvent.id == event_id,
            DeviceEvent.org_id == org_id,
        )
        event = (await self.db.execute(stmt)).scalar_one_or_none()
        if not event:
            raise HTTPException(status_code=404, detail="Событие не найдено")
        return self._to_response(event)

    async def mark_processed(
        self,
        event_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> None:
        """Пометить событие как обработанное EventReactor'ом."""
        from fastapi import HTTPException

        stmt = select(DeviceEvent).where(
            DeviceEvent.id == event_id,
            DeviceEvent.org_id == org_id,
        )
        event = (await self.db.execute(stmt)).scalar_one_or_none()
        if not event:
            raise HTTPException(status_code=404, detail="Событие не найдено")
        event.processed = True
        await self.db.flush()

    async def get_stats(
        self,
        org_id: uuid.UUID,
        device_id: uuid.UUID | None = None,
    ) -> EventStatsResponse:
        """Агрегированная статистика событий."""
        conditions = [DeviceEvent.org_id == org_id]
        if device_id:
            conditions.append(DeviceEvent.device_id == device_id)

        # Общее количество
        total = (await self.db.execute(
            select(func.count()).select_from(DeviceEvent).where(*conditions)
        )).scalar_one()

        # Необработанные
        unprocessed = (await self.db.execute(
            select(func.count()).select_from(DeviceEvent).where(
                *conditions, DeviceEvent.processed.is_(False),
            )
        )).scalar_one()

        # По severity
        severity_rows = (await self.db.execute(
            select(DeviceEvent.severity, func.count())
            .where(*conditions)
            .group_by(DeviceEvent.severity)
        )).all()
        by_severity = {
            (row[0].value if isinstance(row[0], EventSeverity) else str(row[0])): row[1]
            for row in severity_rows
        }

        # По типу (top-20)
        type_rows = (await self.db.execute(
            select(DeviceEvent.event_type, func.count())
            .where(*conditions)
            .group_by(DeviceEvent.event_type)
            .order_by(func.count().desc())
            .limit(20)
        )).all()
        by_type = {row[0]: row[1] for row in type_rows}

        return EventStatsResponse(
            total=total,
            by_severity=by_severity,
            by_type=by_type,
            unprocessed=unprocessed,
        )
