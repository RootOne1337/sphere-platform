# backend/schemas/groups.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-2. Device Group schemas.
from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

_NAME_MAX = 255
_DESC_MAX = 1000


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESC_MAX)
    color: str | None = Field(default=None)
    parent_group_id: uuid.UUID | None = None

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


class UpdateGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESC_MAX)
    color: str | None = None
    parent_group_id: uuid.UUID | None = None

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


class GroupResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    color: str | None
    parent_group_id: uuid.UUID | None
    org_id: uuid.UUID
    total_devices: int = 0
    online_devices: int = 0


class MoveDevicesRequest(BaseModel):
    device_ids: list[str] = Field(min_length=1, max_length=500)
    group_id: uuid.UUID | None = None  # None = remove from this group


class SetTagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        if len(v) > 20:
            raise ValueError("Maximum 20 tags per device")
        cleaned: list[str] = []
        for tag in v:
            t = tag.strip()
            if not t:
                continue
            t = re.sub(r"[^\w\-]", "", t.lower())[:50]
            if t:
                cleaned.append(t)
        return cleaned
