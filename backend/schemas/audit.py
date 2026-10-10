"""Audit investigation is a tenant-scoped, read-only operation."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, Query

from backend.schemas.auth import AuditLogResponse, PaginatedResponse

AuditStatus = Literal["SUCCESS", "FAILED", "WARNING", "UNKNOWN"]
EXPORT_LIMIT = 5000


class AuditLogPage(PaginatedResponse):
    items: list[AuditLogResponse]


@dataclass(frozen=True)
class AuditFilters:
    action: str | None
    resource_type: str | None
    user_id: uuid.UUID | None
    status: AuditStatus | None
    q: str | None
    from_dt: datetime | None
    to_dt: datetime | None


def investigation_filters(
    action: str | None = Query(None, max_length=255, description="Literal case-insensitive action substring"),
    resource_type: str | None = Query(None, max_length=100),
    user_id: uuid.UUID | None = Query(None),
    status: AuditStatus | None = Query(None),
    q: str | None = Query(None, max_length=500, description="AND terms; status:, action:, user: and literal text"),
    from_dt: datetime | None = Query(None, alias="from", description="Inclusive timestamp with UTC offset"),
    to_dt: datetime | None = Query(None, alias="to", description="Inclusive timestamp with UTC offset"),
) -> AuditFilters:
    errors = []
    for name, value in [("from", from_dt), ("to", to_dt)]:
        if value is not None and value.utcoffset() is None:
            errors.append({"loc": ["query", name], "msg": "Timestamp requires a UTC offset", "type": "value_error"})
    if not errors and from_dt is not None and to_dt is not None and from_dt > to_dt:
        errors.append({"loc": ["query", "to"], "msg": "End must not precede start", "type": "value_error"})
    terms = (q or "").split()
    if len(terms) > 20:
        errors.append({"loc": ["query", "q"], "msg": "At most 20 search terms", "type": "value_error"})
    for term in terms:
        key, separator, term_value = term.partition(":")
        if separator and key.lower() in {"status", "action", "user"}:
            if not term_value or (key.lower() == "status" and term_value.upper() not in {"SUCCESS", "FAILED", "WARNING", "UNKNOWN"}):
                errors.append({"loc": ["query", "q"], "msg": "Invalid structured search term", "type": "value_error"})
                break
    if errors:
        raise HTTPException(422, detail=errors)
    return AuditFilters(action, resource_type, user_id, status, q, from_dt, to_dt)
