# backend/services/pipeline_settings_service.py
# ВЛАДЕЛЕЦ: TZ-13 Orchestration Pipeline.
# Сервис управления персистентными настройками оркестрации.
# Реализует singleton-паттерн: одна запись per org_id.
# При первом обращении автоматически создаёт запись с дефолтами.
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.pipeline_settings import PipelineSettings

logger = structlog.get_logger()


class PipelineSettingsService:
    """
    CRUD-сервис для персистентных настроек оркестрации.

    Гарантирует singleton per org: если записи нет — создаёт с дефолтами.
    Все настройки хранятся в PostgreSQL и выживают после рестарта сервера.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_or_create(self, org_id: uuid.UUID) -> PipelineSettings:
        """
        Получить настройки для организации. Создаёт запись с дефолтами, если нет.

        Returns:
            PipelineSettings — всегда валидный объект.
        """
        result = await self._db.execute(
            select(PipelineSettings).where(PipelineSettings.org_id == org_id)
        )
        settings = result.scalar_one_or_none()

        if settings is None:
            settings = PipelineSettings(org_id=org_id)
            self._db.add(settings)
            await self._db.flush()
            logger.info(
                "pipeline_settings.created_defaults",
                org_id=str(org_id),
                settings_id=str(settings.id),
            )

        return settings

    async def update(
        self,
        org_id: uuid.UUID,
        updates: dict,
    ) -> PipelineSettings:
        """
        Частичное обновление настроек (partial update).

        Args:
            org_id: ID организации.
            updates: Словарь обновлений (только непустые поля).

        Returns:
            Обновлённый PipelineSettings.
        """
        settings = await self.get_or_create(org_id)

        changed_fields: list[str] = []
        for field, value in updates.items():
            if value is not None and hasattr(settings, field):
                old_value = getattr(settings, field)
                if old_value != value:
                    setattr(settings, field, value)
                    changed_fields.append(field)

        if changed_fields:
            await self._db.flush()
            logger.info(
                "pipeline_settings.updated",
                org_id=str(org_id),
                changed_fields=changed_fields,
            )

        return settings

    async def toggle_orchestration(
        self, org_id: uuid.UUID, enabled: bool
    ) -> PipelineSettings:
        """Переключить оркестрацию on/off."""
        return await self.update(org_id, {"orchestration_enabled": enabled})

    async def toggle_scheduler(
        self, org_id: uuid.UUID, enabled: bool
    ) -> PipelineSettings:
        """Переключить планировщик on/off."""
        return await self.update(org_id, {"scheduler_enabled": enabled})

    async def toggle_registration(
        self, org_id: uuid.UUID, enabled: bool
    ) -> PipelineSettings:
        """Переключить авто-регистрацию on/off."""
        return await self.update(org_id, {"registration_enabled": enabled})

    async def toggle_farming(
        self, org_id: uuid.UUID, enabled: bool
    ) -> PipelineSettings:
        """Переключить авто-фарм on/off."""
        return await self.update(org_id, {"farming_enabled": enabled})
