# backend/schemas/pipeline.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. Pydantic-схемы для Pipeline API.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Описание шага Pipeline (JSONB-валидация) ─────────────────────────────────


class PipelineStepSchema(BaseModel):
    """
    Описание шага pipeline.

    Каждый шаг содержит id (уникальный внутри pipeline), тип, параметры
    и ссылки на следующие шаги (on_success / on_failure).
    """
    id: str = Field(..., min_length=1, max_length=128, description="Уникальный ID шага в pipeline")
    name: str = Field(..., min_length=1, max_length=255, description="Человекочитаемое имя шага")
    type: str = Field(..., description="Тип шага: execute_script, condition, action, delay, parallel, wait_for_event, n8n_workflow, loop, sub_pipeline")
    params: dict[str, Any] = Field(default_factory=dict, description="Параметры шага (зависят от type)")
    on_success: str | None = Field(None, description="ID следующего шага при успехе (null = конец)")
    on_failure: str | None = Field(None, description="ID следующего шага при ошибке (null = fail pipeline)")
    timeout_ms: int = Field(default=60_000, ge=1000, le=3_600_000, description="Таймаут шага (мс)")
    retries: int = Field(default=0, ge=0, le=10, description="Кол-во ретраев шага")


# ── Запросы ──────────────────────────────────────────────────────────────────


class CreatePipelineRequest(BaseModel):
    """Создание нового pipeline."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    steps: list[PipelineStepSchema] = Field(..., min_length=1, max_length=100)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    global_timeout_ms: int = Field(default=86_400_000, ge=10_000, le=259_200_000)
    max_retries: int = Field(default=0, ge=0, le=5)
    tags: list[str] = Field(default_factory=list, max_length=20)


class UpdatePipelineRequest(BaseModel):
    """Обновление pipeline (частичное)."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    steps: list[PipelineStepSchema] | None = None
    input_schema: dict[str, Any] | None = None
    global_timeout_ms: int | None = Field(None, ge=10_000, le=259_200_000)
    max_retries: int | None = Field(None, ge=0, le=5)
    is_active: bool | None = None
    tags: list[str] | None = None


class RunPipelineRequest(BaseModel):
    """Запуск pipeline на одном устройстве."""
    device_id: uuid.UUID
    input_params: dict[str, Any] = Field(default_factory=dict)


class RunPipelineBatchRequest(BaseModel):
    """Массовый запуск pipeline на нескольких устройствах."""
    device_ids: list[uuid.UUID] | None = None
    group_id: uuid.UUID | None = None
    device_tags: list[str] | None = None
    input_params: dict[str, Any] = Field(default_factory=dict)
    wave_size: int = Field(default=0, ge=0, le=1000, description="Размер волны (0 = все сразу)")
    wave_delay_seconds: int = Field(default=30, ge=0, le=3600, description="Задержка между волнами (секунды)")


# ── Ответы ───────────────────────────────────────────────────────────────────


class PipelineResponse(BaseModel):
    """Краткий ответ pipeline (для списков)."""
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None = None
    steps: list[dict[str, Any]]
    input_schema: dict[str, Any]
    global_timeout_ms: int
    max_retries: int
    version: int
    is_active: bool
    tags: list[str]
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PipelineRunResponse(BaseModel):
    """Ответ одного pipeline run."""
    id: uuid.UUID
    org_id: uuid.UUID
    pipeline_id: uuid.UUID
    device_id: uuid.UUID
    status: str
    current_step_id: str | None = None
    context: dict[str, Any]
    input_params: dict[str, Any]
    step_logs: list[dict[str, Any]]
    current_task_id: uuid.UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    retry_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PipelineBatchResponse(BaseModel):
    """Ответ массового запуска pipeline."""
    id: uuid.UUID
    org_id: uuid.UUID
    pipeline_id: uuid.UUID
    status: str
    total: int
    succeeded: int
    failed: int
    wave_config: dict[str, Any]
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Пагинация ─────────────────────────────────────────────────────────────────


class PipelineListResponse(BaseModel):
    items: list[PipelineResponse]
    total: int
    page: int
    per_page: int
    pages: int


class PipelineRunListResponse(BaseModel):
    items: list[PipelineRunResponse]
    total: int
    page: int
    per_page: int
    pages: int
