# backend/api/v1/batches/router.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-4. Wave Batch Execution API.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# POST /batches     — 202 Accepted (немедленно, волны в фоне)
# GET  /batches/:id — прогресс батча
# DEL  /batches/:id — отменить батч
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import AsyncSessionLocal, get_db
from backend.models.user import User
from backend.schemas.batch import (
    BatchDetailResponse,
    BatchExecutionRequest,
    BatchResponse,
)
from backend.services.batch_service import BatchService

router = APIRouter(prefix="/batches", tags=["batches"])


def get_batch_service(db: AsyncSession = Depends(get_db)) -> BatchService:
    return BatchService(db, session_maker=AsyncSessionLocal)


# ── Start batch ────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=BatchResponse,
    status_code=202,
    summary="Запустить скрипт на N устройствах волнами (202 Accepted)",
)
async def start_batch(
    body: BatchExecutionRequest,
    current_user: User = require_permission("script:execute"),
    svc: BatchService = Depends(get_batch_service),
    db: AsyncSession = Depends(get_db),
) -> BatchResponse:
    """
    Асинхронный запуск батча.
    Возвращает batch_id немедленно — волны запускаются в фоне.
    Прогресс: GET /batches/{id} или Events WebSocket.
    """
    batch = await svc.start_batch(body, current_user.org_id, current_user.id)
    await db.commit()
    return BatchResponse.model_validate(batch)


# ── Get batch status ───────────────────────────────────────────────────────────

@router.get(
    "/{batch_id}",
    response_model=BatchDetailResponse,
    summary="Статус и прогресс батча",
)
async def get_batch_status(
    batch_id: uuid.UUID,
    current_user: User = require_permission("script:read"),
    svc: BatchService = Depends(get_batch_service),
) -> BatchDetailResponse:
    batch = await svc.get_batch(batch_id, current_user.org_id)
    return BatchDetailResponse.model_validate(batch)


# ── Cancel batch ───────────────────────────────────────────────────────────────

@router.delete(
    "/{batch_id}",
    status_code=204,
    response_model=None,
    summary="Отменить батч (незапущенные задачи → CANCELLED)",
)
async def cancel_batch(
    batch_id: uuid.UUID,
    current_user: User = require_permission("script:execute"),
    svc: BatchService = Depends(get_batch_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    await svc.cancel_batch(batch_id, current_user.org_id)
    await db.commit()
