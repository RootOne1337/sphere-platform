# backend/schemas/device_register.py
# ВЛАДЕЛЕЦ: TZ-12 Agent Discovery. Pydantic-схемы для автоматической регистрации устройств.
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Whitelist: безопасные символы для fingerprint (SHA-256 hex-digest + префикс)
FINGERPRINT_PATTERN = re.compile(r"^[a-zA-Z0-9:_\-]{1,200}$")

# Whitelist: workstation_id
WORKSTATION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,100}$")

# Whitelist: location code
LOCATION_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,50}$")


class DeviceRegisterRequest(BaseModel):
    """
    Запрос автоматической регистрации устройства.

    Вызывается Android/PC агентом при первом подключении.
    API-ключ с правом device:register передаётся в заголовке X-API-Key.
    """

    fingerprint: str = Field(
        min_length=8,
        max_length=200,
        description="Уникальный отпечаток устройства (SHA-256 composite fingerprint).",
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Имя устройства. Если null — автогенерация по шаблону.",
    )
    workstation_id: str | None = Field(
        default=None,
        max_length=100,
        description="ID воркстанции (PC-хоста). Для LDPlayer клонов.",
    )
    instance_index: int | None = Field(
        default=None,
        ge=0,
        description="Индекс LDPlayer инстанса (0-based).",
    )
    android_version: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=255)
    location: str | None = Field(
        default=None,
        max_length=50,
        description="Код локации (msk-office-1).",
    )
    device_type: str = Field(
        default="ldplayer",
        description="Тип устройства: ldplayer, physical, remote.",
    )
    meta: dict = Field(
        default_factory=dict,
        description="Дополнительные метаданные (ldplayer_name, clone_source и т.д.).",
    )

    @field_validator("fingerprint")
    @classmethod
    def validate_fingerprint(cls, v: str) -> str:
        if not FINGERPRINT_PATTERN.match(v):
            raise ValueError(
                "Fingerprint содержит недопустимые символы. "
                "Разрешены: буквы, цифры, ':', '_', '-'."
            )
        return v

    @field_validator("workstation_id")
    @classmethod
    def validate_workstation_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not WORKSTATION_ID_PATTERN.match(v):
            raise ValueError(
                "workstation_id содержит недопустимые символы. "
                "Разрешены: буквы, цифры, '_', '-'."
            )
        return v

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not LOCATION_PATTERN.match(v):
            raise ValueError(
                "location содержит недопустимые символы. "
                "Разрешены: буквы, цифры, '_', '-'."
            )
        return v

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, v: str) -> str:
        allowed = {"ldplayer", "physical", "remote", "genymotion", "nox"}
        if v not in allowed:
            raise ValueError(f"device_type должен быть одним из: {', '.join(sorted(allowed))}")
        return v


class DeviceRegisterResponse(BaseModel):
    """
    Ответ на успешную регистрацию устройства.

    Содержит device_id + JWT-токены для немедленного WS-подключения.
    """

    device_id: uuid.UUID = Field(description="UUID зарегистрированного устройства.")
    name: str = Field(description="Имя устройства (автоматическое или пользовательское).")
    access_token: str = Field(description="JWT access token для WS-аутентификации.")
    refresh_token: str = Field(description="JWT refresh token.")
    expires_in: int = Field(description="Время жизни access_token в секундах.")
    server_url: str = Field(description="Актуальный server_url для WS-подключения.")
    is_new: bool = Field(
        default=True,
        description="true — новое устройство, false — re-enrollment существующего.",
    )
    created_at: datetime | None = Field(default=None, description="Дата создания устройства.")
