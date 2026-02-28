# backend/schemas/schedule.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-5. Pydantic-схемы для Schedule API.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Запросы ──────────────────────────────────────────────────────────────────


class CreateScheduleRequest(BaseModel):
    """
    Создание расписания.

    Обязателен ровно один триггер: cron_expression, interval_seconds или one_shot_at.
    Обязательна минимум одна стратегия таргетирования: device_ids, group_id или device_tags.
    """
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

    # Триггеры (взаимоисключающие)
    cron_expression: str | None = Field(None, max_length=128, description="Cron 5 полей: '5,25,45 * * * *'")
    interval_seconds: int | None = Field(None, ge=60, le=86_400, description="Интервал (60..86400 сек)")
    one_shot_at: datetime | None = Field(None, description="Однократный запуск в указанное время (UTC)")

    timezone: str = Field(default="UTC", max_length=64, description="IANA таймзона для cron")

    # Цель
    target_type: str = Field(..., description="script | pipeline")
    script_id: uuid.UUID | None = None
    pipeline_id: uuid.UUID | None = None
    input_params: dict[str, Any] = Field(default_factory=dict)

    # Таргетирование устройств
    device_ids: list[uuid.UUID] | None = None
    group_id: uuid.UUID | None = None
    device_tags: list[str] | None = None
    only_online: bool = True

    # Конфликтная политика
    conflict_policy: str = Field(default="skip", description="skip | queue | cancel")

    # Окно активности
    active_from: datetime | None = None
    active_until: datetime | None = None

    # Лимит запусков
    max_runs: int | None = Field(None, ge=1, le=100_000)

    @model_validator(mode="after")
    def _validate_triggers(self) -> "CreateScheduleRequest":
        """Проверка: ровно один триггер обязателен."""
        triggers = [
            self.cron_expression is not None,
            self.interval_seconds is not None,
            self.one_shot_at is not None,
        ]
        if sum(triggers) != 1:
            raise ValueError("Укажите ровно один триггер: cron_expression, interval_seconds или one_shot_at")
        return self

    @model_validator(mode="after")
    def _validate_target(self) -> "CreateScheduleRequest":
        """Проверка: цель соответствует target_type."""
        if self.target_type == "script" and self.script_id is None:
            raise ValueError("script_id обязателен при target_type='script'")
        if self.target_type == "pipeline" and self.pipeline_id is None:
            raise ValueError("pipeline_id обязателен при target_type='pipeline'")
        return self

    @model_validator(mode="after")
    def _validate_device_targeting(self) -> "CreateScheduleRequest":
        """Проверка: минимум одна стратегия таргетирования устройств."""
        has_targets = any([
            self.device_ids,
            self.group_id is not None,
            self.device_tags,
        ])
        if not has_targets:
            raise ValueError("Укажите хотя бы один способ таргетирования: device_ids, group_id или device_tags")
        return self


class UpdateScheduleRequest(BaseModel):
    """Обновление расписания (частичное)."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    cron_expression: str | None = None
    interval_seconds: int | None = Field(None, ge=60, le=86_400)
    one_shot_at: datetime | None = None
    timezone: str | None = Field(None, max_length=64)
    input_params: dict[str, Any] | None = None
    device_ids: list[uuid.UUID] | None = None
    group_id: uuid.UUID | None = None
    device_tags: list[str] | None = None
    only_online: bool | None = None
    conflict_policy: str | None = None
    is_active: bool | None = None
    active_from: datetime | None = None
    active_until: datetime | None = None
    max_runs: int | None = Field(None, ge=1, le=100_000)


# ── Ответы ───────────────────────────────────────────────────────────────────


class ScheduleResponse(BaseModel):
    """Ответ расписания."""
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None = None
    cron_expression: str | None = None
    interval_seconds: int | None = None
    one_shot_at: datetime | None = None
    timezone: str
    target_type: str
    script_id: uuid.UUID | None = None
    pipeline_id: uuid.UUID | None = None
    input_params: dict[str, Any]
    device_ids: list[str] | None = None
    group_id: uuid.UUID | None = None
    device_tags: list[str] | None = None
    only_online: bool
    conflict_policy: str
    is_active: bool
    active_from: datetime | None = None
    active_until: datetime | None = None
    max_runs: int | None = None
    total_runs: int
    next_fire_at: datetime | None = None
    last_fired_at: datetime | None = None
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScheduleExecutionResponse(BaseModel):
    """Ответ срабатывания расписания."""
    id: uuid.UUID
    schedule_id: uuid.UUID
    org_id: uuid.UUID
    status: str
    fire_time: datetime
    actual_time: datetime
    devices_targeted: int
    tasks_created: int
    tasks_succeeded: int
    tasks_failed: int
    batch_id: uuid.UUID | None = None
    pipeline_batch_id: uuid.UUID | None = None
    skip_reason: str | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Пагинация ─────────────────────────────────────────────────────────────────


class ScheduleListResponse(BaseModel):
    items: list[ScheduleResponse]
    total: int
    page: int
    per_page: int
    pages: int


class ScheduleExecutionListResponse(BaseModel):
    items: list[ScheduleExecutionResponse]
    total: int
    page: int
    per_page: int
    pages: int
