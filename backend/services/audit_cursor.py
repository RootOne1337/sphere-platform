"""Signed continuation for one tenant and one audit query."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from backend.core.config import settings
from backend.schemas.audit import AuditFilters

_TOKEN = re.compile(r"([A-Za-z0-9_-]+)\.([0-9a-f]{64})")
_DOMAIN = b"sphere:audit-cursor:v1:"


def _query_binding(org_id: uuid.UUID, filters: AuditFilters, per_page: int) -> str:
    values = asdict(filters)
    for field in ("from_dt", "to_dt"):
        if values[field] is not None:
            values[field] = values[field].astimezone(timezone.utc).isoformat()
    query = json.dumps([str(org_id), values, per_page], default=str, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(query.encode()).hexdigest()


def _signature(body: str) -> str:
    return hmac.new(settings.JWT_SECRET_KEY.encode(), _DOMAIN + body.encode(), hashlib.sha256).hexdigest()


def encode_audit_cursor(
    org_id: uuid.UUID, filters: AuditFilters, per_page: int, created_at: datetime, row_id: uuid.UUID,
) -> str:
    payload = json.dumps([
        _query_binding(org_id, filters, per_page),
        created_at.astimezone(timezone.utc).isoformat(),
        str(row_id),
    ], separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{body}.{_signature(body)}"


def decode_audit_cursor(
    token: str, org_id: uuid.UUID, filters: AuditFilters, per_page: int,
) -> tuple[datetime, uuid.UUID]:
    match = _TOKEN.fullmatch(token)
    if match is None:
        raise ValueError("Invalid audit cursor")
    body, signature = match.groups()
    if not hmac.compare_digest(signature, _signature(body)):
        raise ValueError("Invalid audit cursor")
    binding, time_value, id_value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if not hmac.compare_digest(binding, _query_binding(org_id, filters, per_page)):
        raise ValueError("Invalid audit cursor")
    return datetime.fromisoformat(time_value), uuid.UUID(id_value)
