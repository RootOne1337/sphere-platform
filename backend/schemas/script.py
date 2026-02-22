# backend/schemas/script.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-2. Pydantic schemas для Script CRUD API.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Запросы ──────────────────────────────────────────────────────────────────

class CreateScriptRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    dag: dict                       # Сырой DAG JSON — будет валидирован в сервисе
    changelog: str | None = Field(None, max_length=1000, description="Описание первой версии")


class UpdateScriptRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    dag: dict | None = None         # None = только метаданные, без новой версии
    changelog: str | None = Field(None, max_length=1000)


# ── Ответы ───────────────────────────────────────────────────────────────────

class ScriptVersionResponse(BaseModel):
    id: uuid.UUID
    script_id: uuid.UUID
    version: int
    dag: dict | None = None         # None если include_dag=False
    dag_hash: str | None = None     # SHA256 DAG в hex
    notes: str | None = None        # Changelog/описание версии
    created_by_id: uuid.UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScriptResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None = None
    is_archived: bool
    current_version_id: uuid.UUID | None = None
    current_version: ScriptVersionResponse | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScriptDetailResponse(ScriptResponse):
    """Расширенный ответ для GET /scripts/{id} — включает все версии."""
    versions: list[ScriptVersionResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ── Пагинация ─────────────────────────────────────────────────────────────────

class ScriptListResponse(BaseModel):
    items: list[ScriptResponse]
    total: int
    page: int
    per_page: int
    pages: int
