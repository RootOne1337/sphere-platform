# backend/schemas/account_sessions.py
# ВЛАДЕЛЕЦ: TZ-11 Account Sessions — Pydantic-схемы для API истории сессий аккаунтов.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StartSessionRequest(BaseModel):
    """Запрос на начало сессии (вызывается при assign аккаунта)."""

    account_id: uuid.UUID
    device_id: uuid.UUID
    script_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    pipeline_run_id: uuid.UUID | None = None
    meta: dict = Field(default_factory=dict)


class EndSessionRequest(BaseModel):
    """Запрос на завершение сессии (вызывается при release / бане / ошибке)."""

    end_reason: str = Field(..., min_length=1, max_length=50)
    error_message: str | None = Field(None, max_length=2000)
    nodes_executed: int = Field(default=0, ge=0)
    errors_count: int = Field(default=0, ge=0)
    level_after: int | None = None
    balance_after: float | None = None
    meta: dict = Field(default_factory=dict)

    @field_validator("end_reason")
    @classmethod
    def validate_end_reason(cls, v: str) -> str:
        allowed = {
            "completed", "banned", "captcha", "error",
            "manual", "rotation", "timeout", "device_offline",
        }
        if v not in allowed:
            raise ValueError(f"Допустимые причины: {', '.join(sorted(allowed))}")
        return v


class AccountSessionResponse(BaseModel):
    """Ответ с данными сессии."""

    id: uuid.UUID
    org_id: uuid.UUID
    account_id: uuid.UUID
    account_login: str | None = None
    account_game: str | None = None
    device_id: uuid.UUID
    device_name: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    error_message: str | None = None
    script_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    pipeline_run_id: uuid.UUID | None = None
    nodes_executed: int = 0
    errors_count: int = 0
    level_before: int | None = None
    level_after: int | None = None
    balance_before: float | None = None
    balance_after: float | None = None
    duration_seconds: int | None = None
    meta: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountSessionListResponse(BaseModel):
    """Пагинированный список сессий."""

    items: list[AccountSessionResponse]
    total: int
    page: int
    per_page: int
    pages: int


class SessionStatsResponse(BaseModel):
    """Агрегированная статистика сессий."""

    total_sessions: int = 0
    active_sessions: int = 0
    avg_duration_seconds: float | None = None
    by_end_reason: dict[str, int] = Field(default_factory=dict)
    total_nodes_executed: int = 0
    total_errors: int = 0
