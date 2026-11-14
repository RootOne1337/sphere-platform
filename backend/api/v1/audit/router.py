# backend/api/v1/audit/router.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-5. Чтение audit logs (иммутабельный журнал).
from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.audit_log import AuditLog
from backend.models.user import User
from backend.schemas.audit import (
    CURSOR_MAX_LENGTH,
    EXPORT_LIMIT,
    AuditFilters,
    AuditLogCursorPage,
    AuditLogPage,
    investigation_filters,
)
from backend.schemas.auth import AuditLogResponse
from backend.services.audit_cursor import decode_audit_cursor, encode_audit_cursor
from backend.services.audit_query import audit_statement, csv_document, status_expression

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "/logs",
    response_model=AuditLogPage,
    summary="SPLIT-5: Журнал аудита",
)
async def list_audit_logs(
    filters: AuditFilters = Depends(investigation_filters),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    current_user: User = require_permission("audit:read"),
    db: AsyncSession = Depends(get_db),
):
    """
    Запросить журнал аудита с фильтрацией.
    Доступно: org_admin, org_owner, super_admin (требуется permission 'audit:read').
    Всегда фильтрует по org_id текущего пользователя (tenant isolation).
    """
    stmt = audit_statement(current_user.org_id, filters)

    # Count
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Paginate
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    logs = list((await db.execute(stmt)).scalars().all())

    return AuditLogPage(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total else 0,
    )


@router.get(
    "/logs/cursor",
    response_model=AuditLogCursorPage,
    summary="Chronological audit entries with a stable continuation cursor",
)
async def list_audit_logs_by_cursor(
    response: Response,
    filters: AuditFilters = Depends(investigation_filters),
    cursor: str | None = Query(None, min_length=1, max_length=CURSOR_MAX_LENGTH),
    per_page: int = Query(50, ge=1, le=100),
    current_user: User = require_permission("audit:read"),
    db: AsyncSession = Depends(get_db),
) -> AuditLogCursorPage:
    org_id = current_user.org_id
    stmt = audit_statement(org_id, filters)
    if cursor is not None:
        try:
            created_at, row_id = decode_audit_cursor(cursor, org_id, filters, per_page)
        except ValueError:
            raise HTTPException(422, detail="Invalid audit cursor. Restart from the newest entries.") from None
        stmt = stmt.where(tuple_(AuditLog.created_at, AuditLog.id) < (created_at, row_id))
    rows = list(await db.scalars(stmt.limit(per_page + 1)))
    entries = rows[:per_page]
    next_cursor = None
    if len(rows) > per_page:
        tail = entries[-1]
        next_cursor = encode_audit_cursor(org_id, filters, per_page, tail.created_at, tail.id)
    response.headers["Cache-Control"] = "private, no-store"
    return AuditLogCursorPage(
        items=[AuditLogResponse.model_validate(entry) for entry in entries],
        next_cursor=next_cursor,
    )


@router.get(
    "/logs/export",
    response_class=Response,
    summary="Bounded organization-wide audit CSV",
    responses={200: {"content": {"text/csv": {}}, "description": "At most 5000 rows; X-Audit-Truncated declares omitted matches"}},
)
async def export_audit_logs(
    filters: AuditFilters = Depends(investigation_filters),
    limit: int = Query(EXPORT_LIMIT, ge=1, le=EXPORT_LIMIT),
    current_user: User = require_permission("audit:read"),
    db: AsyncSession = Depends(get_db),
):
    # A single SELECT has a PostgreSQL statement snapshot, unlike walking offset
    # pages during concurrent inserts. Fetch one extra row solely to detect the cap.
    stmt = audit_statement(current_user.org_id, filters).with_only_columns(
        AuditLog.id, AuditLog.created_at, AuditLog.user_id, AuditLog.action,
        AuditLog.resource_type, AuditLog.resource_id, AuditLog.ip_address,
        AuditLog.meta["request_id"].as_string().label("request_id"),
        status_expression().label("status"),
    ).limit(limit + 1)
    rows = list((await db.execute(stmt)).all())
    observed = datetime.now(timezone.utc).isoformat()
    content = csv_document(rows[:limit])
    return Response(content, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="sphere-audit-{observed[:10]}.csv"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Audit-Rows": str(min(len(rows), limit)),
        "X-Audit-Limit": str(limit),
        "X-Audit-Truncated": str(len(rows) > limit).lower(),
        "X-Audit-Observed-At": observed,
    })
