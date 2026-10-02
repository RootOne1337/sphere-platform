"""One filter implementation for the audit table and its bounded export."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import timezone

from sqlalchemy import String, case, cast, func, or_, select

from backend.models.audit_log import AuditLog
from backend.schemas.audit import AuditFilters


def status_expression():
    value = func.lower(AuditLog.meta["status"].as_string())
    return case(
        (value.in_(["success", "succeeded", "ok", "completed"]), "SUCCESS"),
        (value.in_(["failed", "failure", "error", "rejected"]), "FAILED"),
        (value.in_(["warning", "degraded", "partial"]), "WARNING"),
        else_="UNKNOWN",
    )


def audit_statement(org_id: uuid.UUID, filters: AuditFilters):
    status = status_expression()
    stmt = select(AuditLog).where(AuditLog.org_id == org_id)
    if filters.action:
        stmt = stmt.where(AuditLog.action.icontains(filters.action, autoescape=True))
    if filters.resource_type:
        stmt = stmt.where(AuditLog.resource_type == filters.resource_type)
    if filters.user_id:
        stmt = stmt.where(AuditLog.user_id == filters.user_id)
    if filters.status:
        stmt = stmt.where(status == filters.status)
    if filters.from_dt:
        stmt = stmt.where(AuditLog.created_at >= filters.from_dt)
    if filters.to_dt:
        stmt = stmt.where(AuditLog.created_at <= filters.to_dt)
    searchable = [cast(AuditLog.id, String), cast(AuditLog.created_at, String),
                  func.coalesce(cast(AuditLog.user_id, String), "system"), AuditLog.action,
                  AuditLog.resource_type, AuditLog.resource_id, AuditLog.ip_address]
    for term in (filters.q or "").split():
        key, separator, value = term.partition(":")
        if separator and key.lower() == "status":
            stmt = stmt.where(status == value.upper())
        elif separator and key.lower() == "action":
            stmt = stmt.where(AuditLog.action.icontains(value, autoescape=True))
        elif separator and key.lower() == "user":
            actor = func.coalesce(cast(AuditLog.user_id, String), "system")
            stmt = stmt.where(actor.icontains(value, autoescape=True))
        else:
            stmt = stmt.where(or_(*(column.icontains(term, autoescape=True) for column in searchable)))
    return stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())


def csv_document(rows) -> str:
    """Export only bounded scalar fields; never old/new payloads or arbitrary meta."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")

    def safe(value):
        text = "" if value is None else str(value)
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    writer.writerow(["Время UTC", "Результат", "Действие", "Пользователь / UUID", "Ресурс", "IP", "ID события"])
    for row in rows:
        resource = " · ".join(part for part in [row.resource_type, row.resource_id] if part)
        writer.writerow(map(safe, [row.created_at.astimezone(timezone.utc).isoformat(), row.status, row.action,
                                  row.user_id or "system", resource, row.ip_address, row.id]))
    return "\ufeff" + output.getvalue()
