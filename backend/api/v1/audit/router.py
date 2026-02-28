# backend/api/v1/audit/router.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-5. Чтение audit logs (иммутабельный журнал).
from __future__ import annotations

import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.audit_log import AuditLog
from backend.models.user import User
from backend.schemas.auth import AuditLogResponse, PaginatedResponse

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "/logs",
    response_model=PaginatedResponse,
    summary="SPLIT-5: Журнал аудита",
)
async def list_audit_logs(
    action: str | None = Query(default=None, description="Фильтр по action (ILIKE)"),
    resource_type: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=100),
    current_user: User = require_permission("audit:read"),
    db: AsyncSession = Depends(get_db),
):
    """
    Запросить журнал аудита с фильтрацией.
    Доступно: org_admin, org_owner, super_admin (требуется permission 'audit:read').
    Всегда фильтрует по org_id текущего пользователя (tenant isolation).
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.org_id == current_user.org_id)
        .order_by(AuditLog.created_at.desc())
    )

    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if from_dt:
        stmt = stmt.where(AuditLog.created_at >= from_dt)
    if to_dt:
        stmt = stmt.where(AuditLog.created_at <= to_dt)

    # Count
    from sqlalchemy import func
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Paginate
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    logs = list((await db.execute(stmt)).scalars().all())

    return PaginatedResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total else 0,
    )
