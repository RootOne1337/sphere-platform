# backend/schemas/pipeline.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. Pydantic-схемы для Pipeline API.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Описание шага Pipeline (JSONB-валидация) ─────────────────────────────────


class PipelineStepSchema(BaseModel):
    """
    Описание шага pipeline.

    Каждый шаг содержит id (уникальный внутри pipeline), тип, параметры
    и ссылки на следующие шаги (on_success / on_failure).
    """
    id: str = Field(..., min_length=1, max_length=128, description="Уникальный ID шага в pipeline")
    name: str = Field(..., min_length=1, max_length=255, description="Человекочитаемое имя шага")
    type: Literal["execute_script", "condition", "action", "delay", "parallel", "wait_for_event", "n8n_workflow", "loop", "sub_pipeline"]
    params: dict[str, Any] = Field(default_factory=dict, description="Параметры шага (зависят от type)")
    on_success: str | None = Field(None, description="ID следующего шага при успехе (null = конец)")
    on_failure: str | None = Field(None, description="ID следующего шага при ошибке (null = fail pipeline)")
    timeout_ms: int = Field(default=60_000, ge=1000, le=3_600_000, description="Таймаут шага (мс)")
    retries: int = Field(default=0, ge=0, le=10, description="Кол-во ретраев шага")


def validate_step_links(steps: list[PipelineStepSchema]) -> None:
    ids = {step.id for step in steps}
    if len(ids) != len(steps):
        raise ValueError("Step IDs must be unique within a pipeline")
    for step in steps:
        for target in (step.on_success, step.on_failure):
            if target is not None and target not in ids:
                raise ValueError(f"Step {step.id} references an unknown step {target}")
    # Cycles are intentional for loop/condition workflows; do not require a DAG.


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

    @model_validator(mode="after")
    def validate_graph(self) -> CreatePipelineRequest:
        validate_step_links(self.steps)
        return self


class UpdatePipelineRequest(BaseModel):
    """Обновление pipeline (частичное)."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    steps: list[PipelineStepSchema] | None = Field(None, min_length=1, max_length=100)
    input_schema: dict[str, Any] | None = None
    global_timeout_ms: int | None = Field(None, ge=10_000, le=259_200_000)
    max_retries: int | None = Field(None, ge=0, le=5)
    is_active: bool | None = None
    tags: list[str] | None = Field(None, max_length=20)
    expected_updated_at: datetime | None = Field(None, description="Optional optimistic condition from the inspected PipelineResponse")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_patch(self) -> UpdatePipelineRequest:
        for field in self.model_fields_set - {"description", "expected_updated_at"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null; omit it to retain its current value")
        if self.expected_updated_at is not None and self.expected_updated_at.utcoffset() is None:
            raise ValueError("expected_updated_at must include a timezone")
        if self.steps is not None:
            validate_step_links(self.steps)
        return self


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
    current_child_run_id: uuid.UUID | None = None
    execution_phase: str = "ready"
    execution_generation: int = 0
    execution_lease_until: datetime | None = None
    step_started_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested_at: datetime | None = None
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
