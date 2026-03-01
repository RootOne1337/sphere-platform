# backend/schemas/locations.py
# ВЛАДЕЛЕЦ: TZ-02. Pydantic-схемы для Location endpoints.
from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

_NAME_MAX = 255
_DESC_MAX = 1000
_ADDR_MAX = 500


class CreateLocationRequest(BaseModel):
    """Создание локации."""
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESC_MAX)
    color: str | None = Field(default=None)
    address: str | None = Field(default=None, max_length=_ADDR_MAX)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    parent_location_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be blank")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is not None and not COLOR_PATTERN.match(v):
            raise ValueError("color must be in #RRGGBB format")
        return v


class UpdateLocationRequest(BaseModel):
    """Обновление локации (partial update)."""
    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESC_MAX)
    color: str | None = None
    address: str | None = Field(default=None, max_length=_ADDR_MAX)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    parent_location_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("name cannot be blank")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is not None and not COLOR_PATTERN.match(v):
            raise ValueError("color must be in #RRGGBB format")
        return v


class LocationResponse(BaseModel):
    """Ответ на GET/POST/PUT location."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    color: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    parent_location_id: uuid.UUID | None
    org_id: uuid.UUID
    total_devices: int = 0
    online_devices: int = 0


class MoveDevicesToLocationRequest(BaseModel):
    """Назначить/переместить устройства в локацию."""
    device_ids: list[str] = Field(min_length=1, max_length=500)


class LocationListResponse(BaseModel):
    """Список локаций."""
    items: list[LocationResponse]
    total: int
