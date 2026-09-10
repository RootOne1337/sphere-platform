#!/usr/bin/env python3
"""Seed the configured enrollment key in the administrator's organization.

Run migrations and scripts/create_admin.py first. Both bootstrap commands use
SPHERE_BOOTSTRAP_ORG_SLUG (default: default). Existing keys are verified, never
reactivated, transferred or silently granted permissions by a repeated seed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    from sqlalchemy import select

    from backend.core.config import settings
    from backend.database.engine import AsyncSessionLocal
    from backend.database.tenant import bind_tenant_context
    from backend.models.api_key import APIKey
    from backend.models.organization import Organization

    env = settings.AGENT_CONFIG_ENV or settings.ENVIRONMENT
    config_file = PROJECT_ROOT / settings.AGENT_CONFIG_DIR / "environments" / f"{env}.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    raw_key = config.get("enrollment_api_key")
    if not isinstance(raw_key, str) or not raw_key.strip():
        raise ValueError("Configured enrollment_api_key must be a non-empty string")
    org_slug = os.environ.get("SPHERE_BOOTSTRAP_ORG_SLUG", "default").strip()
    if not org_slug:
        raise ValueError("SPHERE_BOOTSTRAP_ORG_SLUG must not be empty")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    async with AsyncSessionLocal() as session:
        org = await session.scalar(select(Organization).where(Organization.slug == org_slug).with_for_update())
        if org is None:
            raise RuntimeError("Bootstrap organization missing; run scripts/create_admin.py first with the same SPHERE_BOOTSTRAP_ORG_SLUG")
        await bind_tenant_context(session, str(org.id))
        existing = await session.scalar(select(APIKey).where(APIKey.key_hash == key_hash).with_for_update().execution_options(populate_existing=True))
        if existing is not None:
            if (existing.org_id != org.id or not existing.is_active
                    or "device:register" not in (existing.permissions or [])
                    or (existing.expires_at is not None and existing.expires_at <= datetime.now(timezone.utc))):
                raise RuntimeError("Existing enrollment key conflicts with bootstrap organization or is disabled, expired or lacks device:register; provision a new key explicitly")
            key_id = existing.id
        else:
            key = APIKey(org_id=org.id, user_id=None, name=f"Enrollment Key ({env})",
                key_prefix=raw_key[:14], key_hash=key_hash, type="agent",
                permissions=["device:register"], is_active=True, expires_at=None)
            session.add(key)
            await session.flush()
            key_id = key.id
        await session.commit()
        print(f"Enrollment key ready: id={key_id}, org_id={org.id}")


if __name__ == "__main__":
    asyncio.run(main())
