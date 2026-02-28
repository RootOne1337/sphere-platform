# backend/api/v1/pipelines/router.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. Pipeline REST API.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# ARCH-3: register_startup регистрирует PipelineExecutor.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.core.lifespan_registry import register_startup
from backend.database.engine import get_db
from backend.models.pipeline import PipelineRunStatus
from backend.models.user import User
from backend.schemas.pipeline import (
    CreatePipelineRequest,
    PipelineBatchResponse,
    PipelineListResponse,
    PipelineResponse,
    PipelineRunListResponse,
    PipelineRunResponse,
    RunPipelineBatchRequest,
    RunPipelineRequest,
    UpdatePipelineRequest,
)
from backend.services.orchestrator.pipeline_service import PipelineService

logger = structlog.get_logger()

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


# ── DI фабрики ────────────────────────────────────────────────────────────────


def get_pipeline_service(db: AsyncSession = Depends(get_db)) -> PipelineService:
    return PipelineService(db)


# ── Startup: запустить PipelineExecutor ──────────────────────────────────────


async def _startup_pipeline_executor() -> None:
    """Запуск фонового loop исполнения pipeline."""
    import asyncio
    from backend.services.orchestrator.pipeline_executor import PipelineExecutor

    executor = PipelineExecutor()
    asyncio.create_task(executor.start())
    logger.info("pipeline_executor.registered")


register_startup("pipeline_executor", _startup_pipeline_executor)


# ══════════════════════════════════════════════════════════════════════════════
#  Pipeline CRUD
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "",
    response_model=PipelineListResponse,
    summary="Список pipeline с фильтрацией",
)
async def list_pipelines(
    is_active: bool | None = None,
    tag: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: User = require_permission("pipeline:read"),
    svc: PipelineService = Depends(get_pipeline_service),
) -> PipelineListResponse:
    items, total = await svc.list_pipelines(
        org_id=current_user.org_id,
        is_active=is_active,
        tag=tag,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return PipelineListResponse(
        items=[PipelineResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=PipelineResponse,
    status_code=201,
    summary="Создать pipeline",
)
async def create_pipeline(
    body: CreatePipelineRequest,
    current_user: User = require_permission("pipeline:write"),
    svc: PipelineService = Depends(get_pipeline_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineResponse:
    pipeline = await svc.create(
        org_id=current_user.org_id,
        created_by_id=current_user.id,
        name=body.name,
        description=body.description,
        steps=[s.model_dump() for s in body.steps],
        input_schema=body.input_schema,
        global_timeout_ms=body.global_timeout_ms,
        max_retries=body.max_retries,
        tags=body.tags,
    )
    await db.commit()
    return PipelineResponse.model_validate(pipeline)


@router.get(
    "/{pipeline_id}",
    response_model=PipelineResponse,
    summary="Получить pipeline по ID",
)
async def get_pipeline(
    pipeline_id: uuid.UUID,
    current_user: User = require_permission("pipeline:read"),
    svc: PipelineService = Depends(get_pipeline_service),
) -> PipelineResponse:
    pipeline = await svc.get(pipeline_id, current_user.org_id)
    return PipelineResponse.model_validate(pipeline)


@router.patch(
    "/{pipeline_id}",
    response_model=PipelineResponse,
    summary="Обновить pipeline",
)
async def update_pipeline(
    pipeline_id: uuid.UUID,
    body: UpdatePipelineRequest,
    current_user: User = require_permission("pipeline:write"),
    svc: PipelineService = Depends(get_pipeline_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineResponse:
    update_data = body.model_dump(exclude_unset=True)
    if "steps" in update_data and update_data["steps"] is not None:
        update_data["steps"] = [s.model_dump() if hasattr(s, "model_dump") else s for s in update_data["steps"]]
    pipeline = await svc.update(pipeline_id, current_user.org_id, **update_data)
    await db.commit()
    return PipelineResponse.model_validate(pipeline)


@router.delete(
    "/{pipeline_id}",
    status_code=204,
    summary="Деактивировать pipeline",
)
async def delete_pipeline(
    pipeline_id: uuid.UUID,
    current_user: User = require_permission("pipeline:write"),
    svc: PipelineService = Depends(get_pipeline_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    await svc.delete(pipeline_id, current_user.org_id)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  Pipeline Run — запуск и управление
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/{pipeline_id}/run",
    response_model=PipelineRunResponse,
    status_code=201,
    summary="Запустить pipeline на одном устройстве",
)
async def run_pipeline(
    pipeline_id: uuid.UUID,
    body: RunPipelineRequest,
    current_user: User = require_permission("pipeline:execute"),
    svc: PipelineService = Depends(get_pipeline_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineRunResponse:
    run = await svc.run(
        pipeline_id=pipeline_id,
        device_id=body.device_id,
        org_id=current_user.org_id,
        input_params=body.input_params,
    )
    await db.commit()
    return PipelineRunResponse.model_validate(run)


@router.post(
    "/{pipeline_id}/run-batch",
    response_model=PipelineBatchResponse,
    status_code=201,
    summary="Массовый запуск pipeline на нескольких устройствах",
)
async def run_pipeline_batch(
    pipeline_id: uuid.UUID,
    body: RunPipelineBatchRequest,
    current_user: User = require_permission("pipeline:execute"),
    svc: PipelineService = Depends(get_pipeline_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineBatchResponse:
    batch = await svc.run_batch(
        pipeline_id=pipeline_id,
        org_id=current_user.org_id,
        created_by_id=current_user.id,
        device_ids=body.device_ids,
        group_id=body.group_id,
        device_tags=body.device_tags,
        input_params=body.input_params,
        wave_size=body.wave_size,
        wave_delay_seconds=body.wave_delay_seconds,
    )
    await db.commit()
    return PipelineBatchResponse.model_validate(batch)


@router.get(
    "/runs",
    response_model=PipelineRunListResponse,
    summary="Список pipeline runs с фильтрацией",
)
async def list_pipeline_runs(
    pipeline_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    status: PipelineRunStatus | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: User = require_permission("pipeline:read"),
    svc: PipelineService = Depends(get_pipeline_service),
) -> PipelineRunListResponse:
    items, total = await svc.list_runs(
        org_id=current_user.org_id,
        pipeline_id=pipeline_id,
        device_id=device_id,
        status=status,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return PipelineRunListResponse(
        items=[PipelineRunResponse.model_validate(r) for r in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get(
    "/runs/{run_id}",
    response_model=PipelineRunResponse,
    summary="Получить pipeline run по ID",
)
async def get_pipeline_run(
    run_id: uuid.UUID,
    current_user: User = require_permission("pipeline:read"),
    svc: PipelineService = Depends(get_pipeline_service),
) -> PipelineRunResponse:
    run = await svc.get_run(run_id, current_user.org_id)
    return PipelineRunResponse.model_validate(run)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=PipelineRunResponse,
    summary="Отменить pipeline run",
)
async def cancel_pipeline_run(
    run_id: uuid.UUID,
    current_user: User = require_permission("pipeline:execute"),
    svc: PipelineService = Depends(get_pipeline_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineRunResponse:
    run = await svc.cancel_run(run_id, current_user.org_id)
    await db.commit()
    return PipelineRunResponse.model_validate(run)


@router.post(
    "/runs/{run_id}/pause",
    response_model=PipelineRunResponse,
    summary="Приостановить pipeline run",
)
async def pause_pipeline_run(
    run_id: uuid.UUID,
    current_user: User = require_permission("pipeline:execute"),
    svc: PipelineService = Depends(get_pipeline_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineRunResponse:
    run = await svc.pause_run(run_id, current_user.org_id)
    await db.commit()
    return PipelineRunResponse.model_validate(run)


@router.post(
    "/runs/{run_id}/resume",
    response_model=PipelineRunResponse,
    summary="Возобновить pipeline run",
)
async def resume_pipeline_run(
    run_id: uuid.UUID,
    current_user: User = require_permission("pipeline:execute"),
    svc: PipelineService = Depends(get_pipeline_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineRunResponse:
    run = await svc.resume_run(run_id, current_user.org_id)
    await db.commit()
    return PipelineRunResponse.model_validate(run)
