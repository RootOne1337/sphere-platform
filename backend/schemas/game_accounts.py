# backend/schemas/game_accounts.py
# ВЛАДЕЛЕЦ: TZ-10 Game Account Management.
# Pydantic-схемы для CRUD игровых аккаунтов: запросы, ответы, фильтры, импорт.
# Поддержка игровой специфики: сервер, никнейм, двойной баланс (RUB/BC),
# VIP, законопослушность, регистрационные данные.
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Безопасный паттерн: логин может содержать буквы, цифры, @, _, ., -
LOGIN_PATTERN = re.compile(r"^[\w@.\-+]{1,255}$")
# Название игры: буквы, цифры, пробелы, _, -, .
GAME_PATTERN = re.compile(r"^[\w\s.\-]{1,100}$")
# Никнейм: кириллица, латиница, цифры, _, пробел
NICKNAME_PATTERN = re.compile(r"^[\w\sА-Яа-яЁё]{1,100}$")
# Допустимые типы VIP
VIP_TYPES = {"none", "silver", "gold", "platinum", "diamond"}
# Допустимые значения пола
GENDER_VALUES = {"male", "female"}
# Допустимые провайдеры регистрации
REGISTRATION_PROVIDERS = {"manual", "auto", "guest"}


# ── Create ────────────────────────────────────────────────────────────────────


class CreateGameAccountRequest(BaseModel):
    """Запрос на создание игрового аккаунта."""

    game: str = Field(..., min_length=1, max_length=100, description="Название игры / приложения")
    login: str = Field(..., min_length=1, max_length=255, description="Логин / email / username")
    password: str = Field(..., min_length=1, max_length=500, description="Пароль")

    # Игровой сервер и персонаж
    server_name: str | None = Field(None, max_length=50, description="Название сервера (RED, MOSCOW, KAZAN...)")
    nickname: str | None = Field(None, max_length=100, description="Никнейм персонажа (Имя_Фамилия)")
    gender: str | None = Field(None, description="Пол персонажа (male / female)")

    # Игровая статистика
    level: int | None = Field(None, ge=0, description="Уровень аккаунта")
    target_level: int | None = Field(None, ge=0, description="Целевой уровень прокачки")
    experience: int | None = Field(None, ge=0, description="Текущий опыт (EXP)")
    balance_rub: float | None = Field(None, ge=0, description="Баланс игровых рублей")
    balance_bc: float | None = Field(None, ge=0, description="Баланс BC (донат-валюта)")

    # VIP и законопослушность
    vip_type: str | None = Field(None, description="Тип VIP (none / silver / gold / platinum / diamond)")
    vip_expires_at: datetime | None = Field(None, description="Дата окончания VIP")
    lawfulness: int | None = Field(None, ge=0, le=100, description="Законопослушность (0–100)")

    # Регистрационные данные
    registered_at: datetime | None = Field(None, description="Дата регистрации в игре")
    registration_ip: str | None = Field(None, max_length=45, description="IP регистрации")
    registration_location: str | None = Field(None, max_length=200, description="Локация спавна")
    registration_provider: str | None = Field(None, description="Провайдер регистрации (manual / auto / guest)")

    meta: dict | None = Field(default_factory=dict, description="Произвольные метаданные")

    @field_validator("game")
    @classmethod
    def validate_game(cls, v: str) -> str:
        v = v.strip()
        if not GAME_PATTERN.match(v):
            raise ValueError("Название игры содержит недопустимые символы")
        return v

    @field_validator("login")
    @classmethod
    def validate_login(cls, v: str) -> str:
        v = v.strip()
        if not LOGIN_PATTERN.match(v):
            raise ValueError("Логин содержит недопустимые символы")
        return v

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not NICKNAME_PATTERN.match(v):
            raise ValueError("Никнейм содержит недопустимые символы")
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in GENDER_VALUES:
            raise ValueError(f"Допустимые значения пола: {', '.join(sorted(GENDER_VALUES))}")
        return v

    @field_validator("vip_type")
    @classmethod
    def validate_vip_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in VIP_TYPES:
            raise ValueError(f"Допустимые типы VIP: {', '.join(sorted(VIP_TYPES))}")
        return v

    @field_validator("registration_provider")
    @classmethod
    def validate_registration_provider(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in REGISTRATION_PROVIDERS:
            raise ValueError(f"Допустимые провайдеры: {', '.join(sorted(REGISTRATION_PROVIDERS))}")
        return v


# ── Update ────────────────────────────────────────────────────────────────────


class UpdateGameAccountRequest(BaseModel):
    """Запрос на обновление полей аккаунта (PATCH — только переданные поля)."""

    login: str | None = Field(None, min_length=1, max_length=255)
    password: str | None = Field(None, min_length=1, max_length=500)
    status: str | None = Field(None, description="Новый статус (free, disabled, archived)")
    status_reason: str | None = Field(None, max_length=1000)

    # Игровой сервер и персонаж
    server_name: str | None = Field(None, max_length=50)
    nickname: str | None = Field(None, max_length=100)

    # Игровая статистика
    level: int | None = Field(None, ge=0)
    target_level: int | None = Field(None, ge=0)
    experience: int | None = Field(None, ge=0)
    balance_rub: float | None = Field(None, ge=0)
    balance_bc: float | None = Field(None, ge=0)

    # VIP и законопослушность
    vip_type: str | None = Field(None)
    vip_expires_at: datetime | None = None
    lawfulness: int | None = Field(None, ge=0, le=100)

    meta: dict | None = None

    @field_validator("login")
    @classmethod
    def validate_login(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not LOGIN_PATTERN.match(v):
            raise ValueError("Логин содержит недопустимые символы")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return None
        allowed = {"free", "disabled", "archived", "cooldown"}
        if v not in allowed:
            raise ValueError(f"Допустимые статусы для ручной установки: {', '.join(sorted(allowed))}")
        return v

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not NICKNAME_PATTERN.match(v):
            raise ValueError("Никнейм содержит недопустимые символы")
        return v

    @field_validator("vip_type")
    @classmethod
    def validate_vip_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in VIP_TYPES:
            raise ValueError(f"Допустимые типы VIP: {', '.join(sorted(VIP_TYPES))}")
        return v


# ── Import ────────────────────────────────────────────────────────────────────


class ImportAccountItem(BaseModel):
    """Один аккаунт в массовом импорте."""

    game: str = Field(..., min_length=1, max_length=100)
    login: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=500)
    server_name: str | None = Field(None, max_length=50)
    nickname: str | None = Field(None, max_length=100)
    level: int | None = Field(None, ge=0)
    balance_rub: float | None = Field(None, ge=0)
    balance_bc: float | None = Field(None, ge=0)
    meta: dict | None = None

    @field_validator("game")
    @classmethod
    def validate_game(cls, v: str) -> str:
        v = v.strip()
        if not GAME_PATTERN.match(v):
            raise ValueError("Название игры содержит недопустимые символы")
        return v

    @field_validator("login")
    @classmethod
    def validate_login(cls, v: str) -> str:
        v = v.strip()
        if not LOGIN_PATTERN.match(v):
            raise ValueError("Логин содержит недопустимые символы")
        return v


class ImportAccountsRequest(BaseModel):
    """Массовый импорт аккаунтов (до 1000 за раз)."""

    accounts: list[ImportAccountItem] = Field(..., min_length=1, max_length=1000)


class ImportAccountsResponse(BaseModel):
    """Результат массового импорта."""

    created: int
    skipped: int
    errors: list[str]


# ── Assign / Release ─────────────────────────────────────────────────────────


class AssignAccountRequest(BaseModel):
    """Привязать аккаунт к устройству."""

    device_id: uuid.UUID


class ReleaseAccountRequest(BaseModel):
    """Отвязать аккаунт от устройства (с опциональным кулдауном)."""

    cooldown_minutes: int | None = Field(None, ge=0, le=10080, description="Кулдаун в минутах (макс 7 дней)")


# ── Response ──────────────────────────────────────────────────────────────────


class GameAccountResponse(BaseModel):
    """Ответ — полная информация об аккаунте."""

    id: uuid.UUID
    org_id: uuid.UUID
    game: str
    login: str
    # Пароль не возвращается в ответе по умолчанию — только если show_password=true
    status: str
    status_reason: str | None = None
    status_changed_at: datetime | None = None
    device_id: uuid.UUID | None = None
    device_name: str | None = None
    assigned_at: datetime | None = None

    # Игровой сервер и персонаж
    server_name: str | None = None
    nickname: str | None = None
    gender: str | None = None

    # Игровая статистика
    level: int | None = None
    target_level: int | None = None
    experience: int | None = None
    balance_rub: float | None = None
    balance_bc: float | None = None
    last_balance_update: datetime | None = None
    is_leveled: bool = False

    # VIP и законопослушность
    vip_type: str | None = None
    vip_expires_at: datetime | None = None
    lawfulness: int | None = None

    # Статистика банов
    total_bans: int = 0
    last_ban_at: datetime | None = None
    ban_reason: str | None = None

    # Статистика сессий
    total_sessions: int = 0
    last_session_end: datetime | None = None
    cooldown_until: datetime | None = None

    # Регистрационные данные
    registered_at: datetime | None = None
    registration_provider: str | None = None

    meta: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GameAccountWithPasswordResponse(GameAccountResponse):
    """Ответ с паролем (для экспорта / детального просмотра)."""

    password: str


class GameAccountListResponse(BaseModel):
    """Пагинированный список аккаунтов."""

    items: list[GameAccountResponse]
    total: int
    page: int
    per_page: int
    pages: int


# ── Stats ─────────────────────────────────────────────────────────────────────


class AccountStatsResponse(BaseModel):
    """Агрегированная статистика аккаунтов для дашборда."""

    total: int = 0
    free: int = 0
    in_use: int = 0
    cooldown: int = 0
    banned: int = 0
    captcha: int = 0
    phone_verify: int = 0
    disabled: int = 0
    archived: int = 0
    pending_registration: int = 0
    leveled: int = 0
    games: list[str] = Field(default_factory=list, description="Уникальные игры")
    servers: list[str] = Field(default_factory=list, description="Уникальные серверы")


class ServerInfo(BaseModel):
    """Информация об одном игровом сервере."""

    id: int
    name: str
    domain: str
    port: int


class ServerListResponse(BaseModel):
    """Список всех серверов."""

    servers: list[ServerInfo]
    total: int
