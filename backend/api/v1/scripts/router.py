# backend/api/v1/scripts/router.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-2. Scripts CRUD API.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.script import Script, ScriptVersion
from backend.models.user import User
from backend.schemas.script import (
    CreateScriptRequest,
    RollbackScriptRequest,
    ScriptCatalogResponse,
    ScriptDetailResponse,
    ScriptListResponse,
    ScriptResponse,
    ScriptValidationResponse,
    ScriptVersionResponse,
    UpdateScriptRequest,
    ValidateScriptRequest,
)
from backend.services.script_service import ScriptService, _compute_dag_hash

router = APIRouter(prefix="/scripts", tags=["scripts"])


def get_script_service(db: AsyncSession = Depends(get_db)) -> ScriptService:
    return ScriptService(db)


def _to_version_response(v: ScriptVersion, include_dag: bool = True) -> ScriptVersionResponse:
    return ScriptVersionResponse(
        id=v.id,
        script_id=v.script_id,
        version=v.version,
        dag=v.dag if include_dag else None,
        dag_hash=_compute_dag_hash(v.dag) if v.dag else None,
        notes=v.notes,
        created_by_id=v.created_by_id,
        created_at=v.created_at,
    )


def _to_script_response(script: Script) -> ScriptResponse:
    response = ScriptResponse.model_validate(script)
    if script.current_version:
        response.current_version = _to_version_response(script.current_version)
    return response


# ── List ──────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=ScriptListResponse,
    summary="Список скриптов с пагинацией",
)
async def list_scripts(
    query: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    state: Literal["active", "archived", "all"] = "active",
    current_user: User = require_permission("script:read"),
    svc: ScriptService = Depends(get_script_service),
) -> ScriptListResponse:
    scripts, total = await svc.list_scripts(
        org_id=current_user.org_id,
        query=query,
        page=page,
        per_page=per_page,
        state=state,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return ScriptListResponse(
        items=[
            _to_script_response(s) for s in scripts
        ],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.get(
    "/catalog", response_model=ScriptCatalogResponse,
    summary="Каталог скриптов без загрузки DAG",
    responses={503: {"description": "Script catalog metadata unavailable"}},
)
async def list_script_catalog(
    response: Response,
    query: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    state: Literal["active", "archived", "all"] = "active",
    current_user: User = require_permission("script:read"),
    svc: ScriptService = Depends(get_script_service),
) -> ScriptCatalogResponse:
    response.headers["Cache-Control"] = "no-store"
    items, total = await svc.list_script_catalog(
        org_id=current_user.org_id, query=query, page=page, per_page=per_page, state=state,
    )
    return ScriptCatalogResponse(
        items=items, total=total, page=page, per_page=per_page,
        pages=(total + per_page - 1) // per_page if total else 0,
    )

@router.post(
    "",
    response_model=ScriptResponse,
    status_code=201,
    summary="Создать скрипт с DAG",
)
async def create_script(
    body: CreateScriptRequest,
    current_user: User = require_permission("script:write"),
    svc: ScriptService = Depends(get_script_service),
    db: AsyncSession = Depends(get_db),
) -> ScriptResponse:
    script = await svc.create_script(current_user.org_id, current_user.id, body)
    await db.commit()
    await db.refresh(script)
    await db.refresh(script, attribute_names=["current_version"])
    return _to_script_response(script)


@router.post("/validate", response_model=ScriptValidationResponse,
    summary="Проверить черновик без сохранения и выполнения",
    responses={422: {"description": "Invalid DAG structure, references or Lua safety"}})
async def validate_script_draft(
    body: ValidateScriptRequest,
    current_user: User = require_permission("script:read"),
) -> ScriptValidationResponse:
    # Pure validation after ordinary identity/RBAC reads: no ScriptService,
    # database mutation or task/device admission.
    # Reuse the same normalizer as create/update, but never reflect input payloads
    # in errors (a draft can contain private text, headers or code).
    from pydantic import ValidationError

    from backend.schemas.dag import DAGScript

    try:
        dag = DAGScript.model_validate(body.dag).model_dump()
    except ValidationError as exc:
        details = [{"loc": row["loc"], "type": row["type"], "msg": row["msg"][:512]}
                   for row in exc.errors(include_input=False, include_context=False)]
        raise HTTPException(status_code=422, detail=details) from exc
    return ScriptValidationResponse(dag=dag, dag_hash=_compute_dag_hash(dag),
        node_count=len(dag["nodes"]), action_types=sorted({node["action"]["type"] for node in dag["nodes"]}))


# ── Get one ───────────────────────────────────────────────────────────────────

@router.get(
    "/{script_id}",
    response_model=ScriptDetailResponse,
    summary="Получить скрипт с историей версий",
)
async def get_script(
    script_id: uuid.UUID,
    include_dag: bool = Query(True, description="Включать тело DAG в ответ"),
    current_user: User = require_permission("script:read"),
    svc: ScriptService = Depends(get_script_service),
) -> ScriptDetailResponse:
    script = await svc.get_script(
        script_id, current_user.org_id, include_versions=True
    )
    versions = [_to_version_response(v, include_dag=include_dag) for v in script.versions]
    current = (
        _to_version_response(script.current_version, include_dag=include_dag)
        if script.current_version
        else None
    )
    response = ScriptDetailResponse.model_validate(script)
    response.versions = versions
    response.current_version = current
    return response


# ── Update ────────────────────────────────────────────────────────────────────

@router.put(
    "/{script_id}",
    response_model=ScriptResponse,
    summary="Обновить скрипт (создаёт новую версию при изменении DAG)",
)
async def update_script(
    script_id: uuid.UUID,
    body: UpdateScriptRequest,
    current_user: User = require_permission("script:write"),
    svc: ScriptService = Depends(get_script_service),
    db: AsyncSession = Depends(get_db),
) -> ScriptResponse:
    script = await svc.update_script(
        script_id, current_user.org_id, current_user.id, body
    )
    await db.commit()
    await db.refresh(script)
    return _to_script_response(script)


# ── Archive (soft delete) ─────────────────────────────────────────────────────

@router.delete(
    "/{script_id}",
    status_code=204,
    response_model=None,
    summary="Архивировать скрипт (soft delete, не удаляет версии)",
)
async def archive_script(
    script_id: uuid.UUID,
    expected_current_version_id: uuid.UUID | None = None,
    current_user: User = require_permission("script:write"),
    svc: ScriptService = Depends(get_script_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    await svc.archive_script(script_id, current_user.org_id, expected_current_version_id)
    await db.commit()


# ── Versions ──────────────────────────────────────────────────────────────────

@router.get(
    "/{script_id}/versions",
    response_model=list[ScriptVersionResponse],
    summary="История версий скрипта",
)
async def list_versions(
    script_id: uuid.UUID,
    include_dag: bool = Query(False, description="Включать тело DAG в каждую версию"),
    current_user: User = require_permission("script:read"),
    svc: ScriptService = Depends(get_script_service),
) -> list[ScriptVersionResponse]:
    versions = await svc.list_versions(script_id, current_user.org_id)
    return [_to_version_response(v, include_dag=include_dag) for v in versions]


@router.get("/{script_id}/versions/{version_id}", response_model=ScriptVersionResponse,
    summary="Прочитать одну неизменяемую версию с DAG и хешем")
async def get_version(
    script_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = require_permission("script:read"),
    svc: ScriptService = Depends(get_script_service),
) -> ScriptVersionResponse:
    version = await svc.get_version(script_id, version_id, current_user.org_id)
    return _to_version_response(version)


@router.post(
    "/{script_id}/versions/{version_id}/rollback",
    response_model=ScriptResponse,
    summary="Откатить скрипт к указанной версии (создаёт новую версию)",
)
async def rollback(
    script_id: uuid.UUID,
    version_id: uuid.UUID,
    body: RollbackScriptRequest | None = None,
    current_user: User = require_permission("script:write"),
    svc: ScriptService = Depends(get_script_service),
    db: AsyncSession = Depends(get_db),
) -> ScriptResponse:
    script = await svc.rollback_to_version(
        script_id, version_id, current_user.org_id, current_user.id,
        body.expected_current_version_id if body else None,
    )
    await db.commit()
    await db.refresh(script)
    return _to_script_response(script)
