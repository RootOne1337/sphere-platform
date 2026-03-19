# backend/schemas/event_trigger.py
# Pydantic-схемы для CRUD Event Trigger'ов.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateEventTriggerRequest(BaseModel):
    """Создание нового EventTrigger."""

    name: str = Field(..., min_length=1, max_length=255, description="Имя триггера")
    description: str | None = Field(None, description="Описание триггера")
    event_type_pattern: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Glob-паттерн для event_type: account.banned, account.*, task.* итд",
    )
    pipeline_id: uuid.UUID = Field(..., description="Pipeline для запуска при срабатывании")
    input_params_template: dict = Field(
        default_factory=dict,
        description="Шаблон параметров. Плейсхолдеры: {device_id}, {account_id}, {event_type}, {event_id}",
    )
    cooldown_seconds: int = Field(60, ge=0, description="Минимальный интервал между срабатываниями (сек)")
    max_triggers_per_hour: int = Field(100, ge=0, description="Максимум срабатываний в час (0 = без лимита)")


class UpdateEventTriggerRequest(BaseModel):
    """Обновление EventTrigger (все поля опциональные)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    event_type_pattern: str | None = Field(None, min_length=1, max_length=200)
    pipeline_id: uuid.UUID | None = None
    input_params_template: dict | None = None
    is_active: bool | None = None
    cooldown_seconds: int | None = Field(None, ge=0)
    max_triggers_per_hour: int | None = Field(None, ge=0)


class EventTriggerResponse(BaseModel):
    """Ответ с данными EventTrigger."""

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    event_type_pattern: str
    pipeline_id: uuid.UUID
    input_params_template: dict
    is_active: bool
    cooldown_seconds: int
    max_triggers_per_hour: int
    last_triggered_at: datetime | None
    total_triggers: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EventTriggerListResponse(BaseModel):
    """Пагинированный список EventTrigger'ов."""

    items: list[EventTriggerResponse]
    total: int
    page: int
    per_page: int
    pages: int
