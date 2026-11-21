# backend/schemas/event_trigger.py
# Pydantic-схемы для CRUD Event Trigger'ов.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

_INT32_MAX = 2_147_483_647
TriggerDecisionReason = Literal[
    "eligible", "pattern_mismatch", "trigger_disabled", "pipeline_unavailable", "cooldown", "hour_limit",
    "duplicate_event", "causal_cycle", "depth_limit", "root_limit", "cause_unavailable",
]


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
    cooldown_seconds: int = Field(60, ge=0, le=_INT32_MAX, description="Минимальный интервал между срабатываниями (сек)")
    max_triggers_per_hour: int = Field(100, ge=0, le=_INT32_MAX, description="Максимум за последние 60 минут (0 = без лимита)")


class UpdateEventTriggerRequest(BaseModel):
    """Обновление EventTrigger (все поля опциональные)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    event_type_pattern: str | None = Field(None, min_length=1, max_length=200)
    pipeline_id: uuid.UUID | None = None
    input_params_template: dict | None = None
    is_active: bool | None = None
    cooldown_seconds: int | None = Field(None, ge=0, le=_INT32_MAX)
    max_triggers_per_hour: int | None = Field(None, ge=0, le=_INT32_MAX)


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


class EventTriggerSimulationResponse(BaseModel):
    trigger_id: uuid.UUID
    event_type: str
    matches: bool
    would_admit: bool
    reason: TriggerDecisionReason
    observed_at: datetime
    retry_at: datetime | None
    recent_runs: int
    max_triggers_per_hour: int
    event_id: uuid.UUID | None = None
    event_origin: Literal["independent", "pipeline"] | None = None
    root_event_id: uuid.UUID | None = None
    cause_depth: int | None = None
    max_cause_depth: int
    root_runs: int | None = None
    max_root_runs: int
