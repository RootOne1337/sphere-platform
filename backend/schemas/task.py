# backend/schemas/task.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-3+5. Pydantic schemas для Task API.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Запросы ──────────────────────────────────────────────────────────────────

class CreateTaskRequest(BaseModel):
    script_id: uuid.UUID
    device_id: uuid.UUID
    priority: int = Field(default=5, ge=1, le=10)
    webhook_url: str | None = Field(
        None,
        max_length=2048,
        description="URL для callback при завершении задачи",
    )


# ── Ответы ───────────────────────────────────────────────────────────────────

class TaskResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    script_id: uuid.UUID
    device_id: uuid.UUID
    script_version_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    status: str
    priority: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    wave_index: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskDetailResponse(TaskResponse):
    """Расширенный ответ с результатом и ошибкой."""
    result: dict | None = None
    error_message: str | None = None
    input_params: dict | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Пагинация ─────────────────────────────────────────────────────────────────

class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    page: int
    per_page: int
    pages: int
