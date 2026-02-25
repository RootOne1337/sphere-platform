# backend/schemas/webhook.py
# TZ-09 SPLIT-5 — Pydantic schemas for webhook CRUD API
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, HttpUrl, field_validator


class WebhookCreate(BaseModel):
    name: str
    url: HttpUrl
    events: list[str]
    tags: list[str] = []
    secret: str | None = None  # if not provided — generated server-side

    @field_validator("events")
    @classmethod
    def events_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("events list cannot be empty")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        return v


class WebhookUpdate(BaseModel):
    name: str | None = None
    events: list[str] | None = None
    tags: list[str] | None = None
    is_active: bool | None = None


class WebhookResponse(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    events: list[str]
    tags: list[str]
    is_active: bool
    secret: str | None = None  # returned only on create, never on GET
    last_triggered_at: datetime | None = None
    failure_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookListResponse(BaseModel):
    items: list[WebhookResponse]
    total: int
