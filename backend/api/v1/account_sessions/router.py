# backend/api/v1/account_sessions/router.py
# ВЛАДЕЛЕЦ: TZ-11 Account Sessions — REST API для истории сессий аккаунтов.
# AUTO-DISCOVERY: main.py автоматически подхватит этот роутер.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status as http_status

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.account_sessions import (
    AccountSessionListResponse,
    AccountSessionResponse,
    EndSessionRequest,
    SessionStatsResponse,
    StartSessionRequest,
)
from backend.services.account_session_service import AccountSessionService

router = APIRouter(prefix="/account-sessions", tags=["account-sessions"])


# ── DI фабрика ───────────────────────────────────────────────────────────
def get_account_session_service(
    db: AsyncSession = Depends(get_db),
) -> AccountSessionService:
    return AccountSessionService(db)


# ══════════════════════════════════════════════════════════════════════════
#  Endpoints
# ══════════════════════════════════════════════════════════════════════════


@router.get("/stats", response_model=SessionStatsResponse)
async def get_session_stats(
    account_id: uuid.UUID | None = Query(None),
    device_id: uuid.UUID | None = Query(None),
    current_user: User = require_permission("session:read"),
    svc: AccountSessionService = Depends(get_account_session_service),
) -> SessionStatsResponse:
    """Агрегированная статистика сессий."""
    return await svc.get_stats(
        org_id=current_user.org_id,
        account_id=account_id,
        device_id=device_id,
    )


@router.get("", response_model=AccountSessionListResponse)
async def list_account_sessions(
    account_id: uuid.UUID | None = Query(None),
    device_id: uuid.UUID | None = Query(None),
    end_reason: str | None = Query(None),
    active_only: bool = Query(False),
    sort_by: str = Query("started_at"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=5000),
    current_user: User = require_permission("session:read"),
    svc: AccountSessionService = Depends(get_account_session_service),
    db: AsyncSession = Depends(get_db),
) -> AccountSessionListResponse:
    """Пагинированный список сессий с фильтрами."""
    items, total = await svc.list_sessions(
        org_id=current_user.org_id,
        account_id=account_id,
        device_id=device_id,
        end_reason=end_reason,
        active_only=active_only,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    await db.commit()
    return AccountSessionListResponse(
        items=items, total=total, page=page, per_page=per_page, pages=pages,
    )


@router.post("", response_model=AccountSessionResponse, status_code=http_status.HTTP_201_CREATED)
async def start_session(
    body: StartSessionRequest,
    current_user: User = require_permission("session:write"),
    svc: AccountSessionService = Depends(get_account_session_service),
    db: AsyncSession = Depends(get_db),
) -> AccountSessionResponse:
    """Начать новую сессию аккаунта."""
    result = await svc.start_session(org_id=current_user.org_id, data=body)
    await db.commit()
    return result


@router.get("/{session_id}", response_model=AccountSessionResponse)
async def get_session(
    session_id: uuid.UUID,
    current_user: User = require_permission("session:read"),
    svc: AccountSessionService = Depends(get_account_session_service),
) -> AccountSessionResponse:
    """Получить сессию по ID."""
    return await svc.get_session(session_id=session_id, org_id=current_user.org_id)


@router.post("/{session_id}/end", response_model=AccountSessionResponse)
async def end_session(
    session_id: uuid.UUID,
    body: EndSessionRequest,
    current_user: User = require_permission("session:write"),
    svc: AccountSessionService = Depends(get_account_session_service),
    db: AsyncSession = Depends(get_db),
) -> AccountSessionResponse:
    """Завершить активную сессию."""
    result = await svc.end_session(
        session_id=session_id,
        org_id=current_user.org_id,
        data=body,
    )
    await db.commit()
    return result
