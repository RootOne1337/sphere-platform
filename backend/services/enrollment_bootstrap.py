"""One enrollment identity contract for the explicit CLI and dev startup hook."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


class BootstrapOrganizationMissing(RuntimeError):
    """The operator must create the selected organization before enrollment."""


class EnrollmentKeyConflict(RuntimeError):
    """An existing key requires explicit operator intervention."""


class EnrollmentConfigurationError(ValueError):
    """Bootstrap configuration cannot identify a usable enrollment key."""


async def ensure_configured_enrollment_key() -> tuple[UUID, UUID]:
    from sqlalchemy import select

    from backend.core.config import settings
    from backend.database.engine import AsyncSessionLocal
    from backend.database.tenant import bind_tenant_context
    from backend.models.api_key import APIKey
    from backend.models.organization import Organization

    environment = settings.AGENT_CONFIG_ENV or settings.ENVIRONMENT
    root = Path(__file__).resolve().parents[2]
    config_file = root / settings.AGENT_CONFIG_DIR / "environments" / f"{environment}.json"
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EnrollmentConfigurationError("Cannot read enrollment bootstrap configuration") from exc
    raw_key = config.get("enrollment_api_key") if isinstance(config, dict) else None
    if not isinstance(raw_key, str) or not raw_key.strip():
        raise EnrollmentConfigurationError("Configured enrollment_api_key must be a non-empty string")
    org_slug = os.environ.get("SPHERE_BOOTSTRAP_ORG_SLUG", "default").strip()
    if not org_slug:
        raise EnrollmentConfigurationError("SPHERE_BOOTSTRAP_ORG_SLUG must not be empty")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    async with AsyncSessionLocal() as session:
        # Serialize CLI and all API workers before the read/insert decision.
        org = await session.scalar(select(Organization).where(
            Organization.slug == org_slug).with_for_update())
        if org is None:
            raise BootstrapOrganizationMissing(
                "Bootstrap organization missing; run scripts/create_admin.py first "
                "with the same SPHERE_BOOTSTRAP_ORG_SLUG")
        await bind_tenant_context(session, str(org.id))
        existing = await session.scalar(select(APIKey).where(APIKey.key_hash == key_hash)
            .with_for_update().execution_options(populate_existing=True))
        if existing is not None:
            if (existing.org_id != org.id or not existing.is_active
                    or "device:register" not in (existing.permissions or [])
                    or (existing.expires_at is not None
                        and existing.expires_at <= datetime.now(timezone.utc))):
                raise EnrollmentKeyConflict(
                    "Existing enrollment key conflicts with bootstrap organization or is disabled, "
                    "expired or lacks device:register; provision a new key explicitly")
            key_id = existing.id
        else:
            key = APIKey(org_id=org.id, user_id=None, name=f"Enrollment Key ({environment})",
                key_prefix=raw_key[:14], key_hash=key_hash, type="agent",
                permissions=["device:register"], is_active=True, expires_at=None)
            session.add(key)
            await session.flush()
            key_id = key.id
        await session.commit()
        return key_id, org.id
