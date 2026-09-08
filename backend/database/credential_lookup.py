"""Resolve only a tenant UUID from a full credential hash, then use normal RLS."""

import re
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.tenant import bind_tenant_context

_LOOKUPS = {
    "api_key": text("SELECT sphere_auth.api_key_org(:credential_hash)"),
    "device_refresh": text("SELECT sphere_auth.device_refresh_org(:credential_hash)"),
}


async def bind_credential_tenant(
    db: AsyncSession, kind: Literal["api_key", "device_refresh"], credential_hash: str,
) -> UUID | None:
    if not re.fullmatch(r"[0-9a-f]{64}", credential_hash):
        raise ValueError("Expected a complete SHA-256 credential hash")
    org_id = await db.scalar(_LOOKUPS[kind], {"credential_hash": credential_hash})
    if org_id is None:
        return None
    tenant = UUID(str(org_id))
    await bind_tenant_context(db, str(tenant))
    return tenant
