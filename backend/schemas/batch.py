# backend/schemas/batch.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-4. Pydantic schemas для Wave Batch API.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Запросы ──────────────────────────────────────────────────────────────────

class BatchExecutionRequest(BaseModel):
    script_id: uuid.UUID
    device_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=1000,
        description="Список UUID устройств для запуска",
    )
    wave_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Кол-во устройств в одной волне",
    )
    wave_delay_ms: int = Field(
        default=5000,
        ge=0,
        le=3_600_000,
        description="Задержка между волнами (мс)",
    )
    jitter_ms: int = Field(
        default=1000,
        ge=0,
        le=30_000,
        description="Случайный разброс задержки (мс)",
    )
    priority: int = Field(default=5, ge=1, le=10)
    webhook_url: str | None = Field(
        None,
        max_length=2048,
        description="URL callback при завершении всего батча",
    )
    stagger_by_workstation: bool = Field(
        default=True,
        description="Распределять волны по рабочим станциям равномерно",
    )
    name: str | None = Field(None, max_length=255)


class BroadcastBatchRequest(BaseModel):
    """Запуск скрипта на ВСЕХ онлайн-устройствах организации."""

    script_id: uuid.UUID
    wave_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Кол-во устройств в одной волне",
    )
    wave_delay_ms: int = Field(
        default=5000,
        ge=0,
        le=3_600_000,
        description="Задержка между волнами (мс)",
    )
    jitter_ms: int = Field(
        default=1000,
        ge=0,
        le=30_000,
        description="Случайный разброс задержки (мс)",
    )
    priority: int = Field(default=5, ge=1, le=10)
    webhook_url: str | None = Field(
        None,
        max_length=2048,
        description="URL callback при завершении всего батча",
    )
    stagger_by_workstation: bool = Field(
        default=True,
        description="Распределять волны по рабочим станциям равномерно",
    )
    name: str | None = Field(None, max_length=255)


# ── Ответы ───────────────────────────────────────────────────────────────────

class BatchResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    script_id: uuid.UUID
    name: str | None = None
    status: str
    total: int
    succeeded: int
    failed: int
    wave_config: dict
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BatchDetailResponse(BatchResponse):
    """Расширенный ответ с прогрессом волн."""
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class BroadcastBatchResponse(BatchResponse):
    """Ответ broadcast-запуска — дополнительно содержит число онлайн-устройств."""
    online_devices: int = Field(description="Кол-во онлайн-устройств, включённых в батч")

    model_config = ConfigDict(from_attributes=True)
