# backend/schemas/pipeline_settings.py
# ВЛАДЕЛЕЦ: TZ-13 Orchestration Pipeline.
# Pydantic-схемы для настроек оркестрации.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PipelineSettingsResponse(BaseModel):
    """Полный ответ с настройками оркестрации."""

    id: uuid.UUID
    org_id: uuid.UUID

    # Главные переключатели
    orchestration_enabled: bool
    scheduler_enabled: bool

    # Регистрация
    registration_enabled: bool
    max_concurrent_registrations: int
    registration_script_id: uuid.UUID | None
    registration_timeout_seconds: int

    # Фарм
    farming_enabled: bool
    max_concurrent_farming: int
    farming_script_id: uuid.UUID | None
    farming_session_duration_seconds: int

    # Уровни
    default_target_level: int
    cooldown_between_sessions_minutes: int

    # Ники
    nick_generation_enabled: bool
    nick_pattern: str

    # Мониторинг
    ban_detection_enabled: bool
    auto_replace_banned: bool

    # Мета
    notes: str | None = None
    meta: dict = Field(default_factory=dict)

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UpdatePipelineSettingsRequest(BaseModel):
    """Запрос на обновление настроек (все поля опциональны — partial update)."""

    # Главные переключатели
    orchestration_enabled: bool | None = None
    scheduler_enabled: bool | None = None

    # Регистрация
    registration_enabled: bool | None = None
    max_concurrent_registrations: int | None = Field(None, ge=1, le=100)
    registration_script_id: uuid.UUID | None = None
    registration_timeout_seconds: int | None = Field(None, ge=60, le=7200)

    # Фарм
    farming_enabled: bool | None = None
    max_concurrent_farming: int | None = Field(None, ge=1, le=500)
    farming_script_id: uuid.UUID | None = None
    farming_session_duration_seconds: int | None = Field(None, ge=300, le=86400)

    # Уровни
    default_target_level: int | None = Field(None, ge=1, le=100)
    cooldown_between_sessions_minutes: int | None = Field(None, ge=0, le=1440)

    # Ники
    nick_generation_enabled: bool | None = None
    nick_pattern: str | None = Field(None, min_length=3, max_length=100)

    # Мониторинг
    ban_detection_enabled: bool | None = None
    auto_replace_banned: bool | None = None

    # Мета
    notes: str | None = None


class ToggleRequest(BaseModel):
    """Запрос на переключение on/off."""

    enabled: bool


class NickGenerateRequest(BaseModel):
    """Запрос на генерацию никнейма."""

    count: int = Field(1, ge=1, le=100, description="Количество ников для генерации")
    pattern: str = Field("{first_name}_{last_name}", max_length=100)
    gender: str | None = Field(None, pattern="^(male|female)$")


class NickGenerateResponse(BaseModel):
    """Ответ с сгенерированными никами."""

    nicknames: list[str]


class NickCheckRequest(BaseModel):
    """Запрос на проверку доступности ника."""

    nickname: str = Field(min_length=2, max_length=100)


class NickCheckResponse(BaseModel):
    """Ответ проверки доступности ника."""

    nickname: str
    available: bool


class OrchestrationStatusResponse(BaseModel):
    """Текущий статус оркестрации (runtime info)."""

    orchestration_enabled: bool
    scheduler_enabled: bool
    registration_enabled: bool
    farming_enabled: bool

    # Текущая активность
    active_registrations: int = 0
    active_farming_sessions: int = 0
    pending_registrations: int = 0
    total_devices_with_server: int = 0
    total_free_accounts: int = 0
    total_banned_accounts: int = 0

    # Статистика за сессию (с последнего рестарта)
    registrations_completed: int = 0
    registrations_failed: int = 0
    bans_detected: int = 0


class ServerListResponse(BaseModel):
    """Список доступных игровых серверов."""

    servers: list[ServerInfo]


class ServerInfo(BaseModel):
    """Информация об игровом сервере."""

    id: int
    name: str
    domain: str
    port: int
