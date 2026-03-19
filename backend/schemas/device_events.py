# backend/schemas/device_events.py
# ВЛАДЕЛЕЦ: TZ-11 Device Events — Pydantic-схемы для API событий устройств.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateDeviceEventRequest(BaseModel):
    """Запрос на создание события (от агента или внутреннего сервиса)."""

    device_id: uuid.UUID
    event_type: str = Field(..., min_length=1, max_length=100)
    severity: str = Field(default="info")
    message: str | None = Field(None, max_length=2000)
    account_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    pipeline_run_id: uuid.UUID | None = None
    data: dict = Field(default_factory=dict)
    occurred_at: datetime | None = None

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"debug", "info", "warning", "error", "critical"}
        if v not in allowed:
            raise ValueError(f"Допустимые уровни: {', '.join(sorted(allowed))}")
        return v

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        """Только буквы, цифры, точки, подчёркивания и дефисы."""
        v = v.strip().lower()
        import re
        if not re.match(r"^[a-z0-9][a-z0-9._\-]{0,98}[a-z0-9]$", v):
            raise ValueError("Недопустимый формат event_type (a-z0-9._-)")
        return v


class DeviceEventResponse(BaseModel):
    """Ответ с данными события."""

    id: uuid.UUID
    org_id: uuid.UUID
    device_id: uuid.UUID
    device_name: str | None = None
    event_type: str
    severity: str
    message: str | None = None
    account_id: uuid.UUID | None = None
    account_login: str | None = None
    task_id: uuid.UUID | None = None
    pipeline_run_id: uuid.UUID | None = None
    data: dict = Field(default_factory=dict)
    occurred_at: datetime
    processed: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeviceEventListResponse(BaseModel):
    """Пагинированный список событий."""

    items: list[DeviceEventResponse]
    total: int
    page: int
    per_page: int
    pages: int


class EventStatsResponse(BaseModel):
    """Агрегированная статистика событий."""

    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    unprocessed: int = 0
