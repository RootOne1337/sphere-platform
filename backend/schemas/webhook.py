# backend/schemas/webhook.py
# TZ-09 SPLIT-5 — Pydantic schemas for webhook CRUD API
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

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
    receiver_allowed: bool = False

    model_config = {"from_attributes": True}


class WebhookListResponse(BaseModel):
    items: list[WebhookResponse]
    total: int
    publishing_enabled: bool = False
    supported_events: list[str] = []


DeliveryStatus = Literal["pending", "sending", "delivered", "dead"]


class WebhookDeliveryResponse(BaseModel):
    id: uuid.UUID
    webhook_id: uuid.UUID | None
    subject_id: uuid.UUID | None
    source: Literal["task_callback", "subscription"]
    event_type: str
    status: DeliveryStatus
    attempts_count: int
    max_attempts: int
    replay_count: int
    next_attempt_at: datetime | None
    last_http_status: int | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    can_replay: bool = False

    model_config = {"from_attributes": True}


class WebhookDeliveryAttempt(BaseModel):
    number: int
    status: Literal["sending", "delivered", "retry", "dead", "unknown"]
    http_status: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class WebhookDeliveryDetail(WebhookDeliveryResponse):
    attempts: list[WebhookDeliveryAttempt]


class WebhookDeliveryList(BaseModel):
    items: list[WebhookDeliveryResponse]
    total: int
    page: int
    per_page: int
