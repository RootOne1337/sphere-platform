# backend/schemas/devices.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-1. Pydantic schemas для device endpoints.
# Защита от injection — whitelist паттерны на serial и tags.
from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Whitelist: только безопасные символы.
# Блокирует shell injection: ; && | ` $ > < etc.
SERIAL_PATTERN = re.compile(r"^[a-zA-Z0-9:_.\-]{1,100}$")
TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{1,50}$")


# ── Create ────────────────────────────────────────────────────────────────────

class CreateDeviceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    serial: str | None = Field(
        None,
        max_length=100,
        description="ADB serial / device identifier: emulator-5554, ld:0, sphere_abc123",
    )
    type: Literal["ldplayer", "physical", "remote"] = "ldplayer"
    ip_address: str | None = None
    adb_port: int | None = Field(None, ge=1, le=65535)
    android_version: str | None = Field(None, max_length=50)
    device_model: str | None = Field(None, max_length=255)
    workstation_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = None

    @field_validator("serial")
    @classmethod
    def validate_serial(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not SERIAL_PATTERN.match(v):
            raise ValueError(
                "Serial must contain only letters, digits, ':', '_', '.', '-'"
            )
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        for tag in v:
            if not TAG_PATTERN.match(tag):
                raise ValueError(
                    f"Tag '{tag}' contains invalid characters. "
                    "Only letters, digits, '_', '-', '.' are allowed."
                )
        return v

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError("Invalid IP address format")
        return v


# ── Update ────────────────────────────────────────────────────────────────────

class UpdateDeviceRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    serial: str | None = Field(None, max_length=100)
    type: Literal["ldplayer", "physical", "remote"] | None = None
    ip_address: str | None = None
    adb_port: int | None = Field(None, ge=1, le=65535)
    android_version: str | None = Field(None, max_length=50)
    device_model: str | None = Field(None, max_length=255)
    workstation_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    tags: list[str] | None = None
    notes: str | None = None
    is_active: bool | None = None

    @field_validator("serial")
    @classmethod
    def validate_serial(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not SERIAL_PATTERN.match(v):
            raise ValueError(
                "Serial must contain only letters, digits, ':', '_', '.', '-'"
            )
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        for tag in v:
            if not TAG_PATTERN.match(tag):
                raise ValueError(f"Tag '{tag}' contains invalid characters")
        return v

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError("Invalid IP address format")
        return v


# ── Response ──────────────────────────────────────────────────────────────────

class DeviceResponse(BaseModel):
    """Ответ на GET/POST/PUT device — все поля из DB + meta + live-телеметрия из Redis."""

    id: uuid.UUID
    name: str
    serial: str | None = None
    type: str | None = None          # из meta["type"]
    status: str                      # last_status из DB (или live из Redis)
    is_active: bool
    ip_address: str | None = None    # из meta["ip_address"]
    adb_port: int | None = None      # из meta["adb_port"]
    android_version: str | None = None
    device_model: str | None = None  # model column
    workstation_id: uuid.UUID | None = None   # из meta["workstation_id"]
    group_ids: list[uuid.UUID] = Field(default_factory=list)  # M2M groups
    location_ids: list[uuid.UUID] = Field(default_factory=list)  # M2M locations
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    # Live-телеметрия из Redis (обогащается в list/get endpoints)
    battery_level: int | None = None
    cpu_usage: float | None = None
    ram_usage_mb: int | None = None
    screen_on: bool | None = None
    adb_connected: bool = False
    vpn_active: bool | None = None
    last_heartbeat: datetime | None = None

    model_config = ConfigDict(from_attributes=False)


class DeviceStatusResponse(DeviceResponse):
    """Расширенный ответ для GET /devices/{id}/status — добавляет live из Redis."""

    live: str | None = None  # None если агент оффлайн (TTL истёк)


# ── List ──────────────────────────────────────────────────────────────────────

class DeviceListResponse(BaseModel):
    items: list[DeviceResponse]
    total: int
    page: int
    per_page: int
    pages: int
