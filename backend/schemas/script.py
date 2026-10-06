# backend/schemas/script.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-2. Pydantic schemas для Script CRUD API.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    expected_current_version_id: uuid.UUID | None = None


class RollbackScriptRequest(BaseModel):
    """Opt-in optimistic precondition; legacy callers may omit the body."""
    expected_current_version_id: uuid.UUID


class ValidateScriptRequest(BaseModel):
    """Draft validation never creates a script, version or device command."""
    dag: dict


class ScriptValidationResponse(BaseModel):
    schema_version: Literal[1] = 1
    dag: dict
    dag_hash: str
    node_count: int
    action_types: list[str]
    scope: Literal["structure-routes-lua-safety"] = "structure-routes-lua-safety"
    # Additive receipt fields: old clients retain their narrower scope statement.
    action_contract_version: Literal["1.0"] = "1.0"
    action_parameters_verified: Literal[True] = True
    device_execution_verified: Literal[False] = False


class ScriptActionContractResponse(BaseModel):
    """Published parameter rules, independent of any installed APK capability."""
    version: Literal["1.0"] = "1.0"
    contract: dict
    device_execution_verified: Literal[False] = False
    installed_apk_capabilities_verified: Literal[False] = False


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


class ScriptCatalogVersionMetadata(BaseModel):
    """A version identity and persisted summary, never a source response."""
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    script_id: uuid.UUID
    version: int = Field(ge=1, strict=True)
    dag_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class ScriptCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    current_version_id: uuid.UUID | None
    node_count: int | None = Field(ge=0, strict=True)
    current_version: ScriptCatalogVersionMetadata | None

    @model_validator(mode="after")
    def validate_current_version(self) -> "ScriptCatalogItem":
        if self.current_version_id is None:
            if self.current_version is not None or self.node_count is not None:
                raise ValueError("An unpublished script has no version metadata")
        elif (
            self.current_version is None
            or self.node_count is None
            or self.current_version.id != self.current_version_id
            or self.current_version.script_id != self.id
        ):
            raise ValueError("Current version metadata must belong to the selected script")
        return self


class ScriptCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_schema: Literal[1] = 1
    items: list[ScriptCatalogItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=200)
    pages: int = Field(ge=0)
