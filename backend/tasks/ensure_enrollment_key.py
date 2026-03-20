# backend/tasks/ensure_enrollment_key.py
# Гарантирует существование dev enrollment API-ключа при запуске в development-среде.
# Без этого ключа агенты не могут пройти auto-registration (POST /api/v1/devices/register).
from __future__ import annotations

import structlog

from backend.core.lifespan_registry import register_startup

logger = structlog.get_logger()

# Хардкодированный enrollment ключ из agent-config/environments/development.json
# и android/app/build.gradle.kts (DEFAULT_API_KEY для dev flavor).
DEV_ENROLLMENT_KEY = "sphr_dev_enrollment_key_2025"


async def _ensure_enrollment_key() -> None:
    from backend.core.config import settings

    if settings.ENVIRONMENT not in ("development", "dev", "local"):
        logger.debug("ensure_enrollment_key: skipped (env=%s)", settings.ENVIRONMENT)
        return

    from hashlib import sha256

    from sqlalchemy import select

    from backend.database.engine import AsyncSessionLocal
    from backend.models.api_key import APIKey

    key_hash = sha256(DEV_ENROLLMENT_KEY.encode()).hexdigest()

    async with AsyncSessionLocal() as db:
        # Проверяем есть ли уже ключ с таким хэшем
        existing = await db.execute(
            select(APIKey).where(APIKey.key_hash == key_hash)
        )
        if existing.scalar_one_or_none():
            logger.debug("ensure_enrollment_key: already exists")
            return

        # Находим первую организацию для привязки ключа
        from backend.models.organization import Organization

        org_result = await db.execute(select(Organization).limit(1))
        org = org_result.scalar_one_or_none()
        if not org:
            logger.warning("ensure_enrollment_key: no organization found — skipping")
            return

        # Создаём enrollment API ключ
        enrollment_key = APIKey(
            org_id=org.id,
            user_id=None,
            name="Dev Enrollment Key (auto-created)",
            key_prefix=DEV_ENROLLMENT_KEY[:14],
            key_hash=key_hash,
            type="user",
            permissions=["device:register"],
            is_active=True,
            expires_at=None,
        )
        db.add(enrollment_key)
        await db.commit()
        logger.info(
            "ensure_enrollment_key: created dev enrollment key",
            org_id=str(org.id),
            prefix=DEV_ENROLLMENT_KEY[:14],
        )


register_startup("ensure_enrollment_key", _ensure_enrollment_key)
