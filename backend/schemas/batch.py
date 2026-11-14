# backend/schemas/batch.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-4. Pydantic schemas для Wave Batch API.
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Запросы ──────────────────────────────────────────────────────────────────

class BatchExecutionRequest(BaseModel):
    script_id: uuid.UUID
    expected_current_version_id: uuid.UUID | None = None
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
        description="Зарезервированный URL callback; доставка ещё не реализована, используйте GET /batches/{id}",
    )
    stagger_by_workstation: bool = Field(
        default=True,
        description="Распределять волны по рабочим станциям равномерно",
    )
    name: str | None = Field(None, max_length=255)

    @field_validator("device_ids")
    @classmethod
    def unique_devices(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("device_ids must be unique")
        return value


class BroadcastBatchRequest(BaseModel):
    """Запуск скрипта на ВСЕХ онлайн-устройствах организации."""

    script_id: uuid.UUID
    expected_current_version_id: uuid.UUID | None = None
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
        description="Зарезервированный URL callback; доставка ещё не реализована, используйте GET /batches/{id}",
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
    script_version_id: uuid.UUID | None = None
    next_wave_index: int = 0
    next_wave_at: datetime | None = None
    admission_state: str = "legacy_unknown"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BatchSummary(BatchResponse):
    script_name: str | None = None
    wave_count: int | None = None


class BatchTargetState(StrEnum):
    PENDING_ADMISSION = "pending_admission"
    REJECTED = "rejected"
    NOT_ADMITTED_CANCELLED = "not_admitted_cancelled"
    UNKNOWN = "unknown"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class BatchTarget(BaseModel):
    device_id: uuid.UUID
    device_name: str | None = None
    wave_index: int = Field(ge=0)
    state: BatchTargetState
    task_id: uuid.UUID | None = None
    admission_http_status: int | None = Field(default=None, ge=400, le=499)
    cancel_requested_at: datetime | None = None
    timeout_requested_at: datetime | None = None


class BatchDetailResponse(BatchSummary):
    """Расширенный ответ с прогрессом волн."""
    notes: str | None = None
    admission_receipts: list[dict] = Field(default_factory=list)
    targets: list[BatchTarget] | None = None
    target_counts: dict[BatchTargetState, int] | None = None

    model_config = ConfigDict(from_attributes=True)


class BatchListResponse(BaseModel):
    items: list[BatchSummary]
    total: int
    page: int
    per_page: int
    pages: int


class BroadcastBatchResponse(BatchResponse):
    """Ответ broadcast-запуска — дополнительно содержит число онлайн-устройств."""
    online_devices: int = Field(description="Кол-во онлайн-устройств, включённых в батч")

    model_config = ConfigDict(from_attributes=True)
