# backend/services/api_key_service.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-4. API Keys для машинных интеграций (n8n, PC Agent).
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.security import generate_api_key
from backend.database.credential_lookup import bind_credential_tenant
from backend.models.api_key import APIKey


class APIKeyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_api_key(
        self,
        org_id: uuid.UUID,
        name: str,
        permissions: list[str],
        created_by: uuid.UUID,
        expires_at: datetime | None = None,
        key_type: str = "user",
    ) -> tuple[APIKey, str]:
        """
        Создать новый API ключ.
        Возвращает (api_key_record, raw_key).
        raw_key показывается пользователю ОДИН РАЗ при создании.
        """
        env = settings.ENVIRONMENT[:4]  # prod, stag, deve
        raw_key, key_hash, key_prefix = generate_api_key(env)

        api_key = APIKey(
            org_id=org_id,
            user_id=created_by,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            type=key_type,
            permissions=permissions,
            expires_at=expires_at,
        )
        self.db.add(api_key)
        await self.db.flush()
        return api_key, raw_key

    async def authenticate(self, raw_key: str) -> APIKey | None:
        """
        Аутентифицировать по API ключу.
        Сериализует проверку с изменением/отзывом ключа и обновляет last_used_at.
        Возвращает None при неверном, истёкшем или деактивированном ключе.
        """
        if not raw_key.startswith("sphr_"):
            return None

        from backend.core.security import hash_token
        key_hash = hash_token(raw_key)
        org_id = await bind_credential_tenant(self.db, "api_key", key_hash)
        if org_id is None:
            return None

        stmt = select(APIKey).where(
            APIKey.org_id == org_id,
            APIKey.key_hash == key_hash,
        ).with_for_update().execution_options(populate_existing=True)
        result = await self.db.execute(stmt)
        api_key = result.scalar_one_or_none()
        # Re-check after the row owner commits, including already cached ORM rows
        # and expiry reached during the lock wait. The subsequent UPDATE already
        # needed this lock; do not authenticate using the earlier SELECT snapshot.
        if api_key is None or not api_key.is_active:
            return None
        now = datetime.now(timezone.utc)
        expiry = api_key.expires_at
        if expiry is not None:
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= now:
                return None

        await self.db.execute(
            update(APIKey)
            .where(APIKey.id == api_key.id, APIKey.org_id == org_id)
            .values(last_used_at=now)
        )
        return api_key

    async def revoke(self, key_id: uuid.UUID, org_id: uuid.UUID) -> bool:
        """Отозвать API ключ. Возвращает False если ключ не найден или чужой."""
        api_key = await self.db.get(APIKey, key_id)
        if not api_key or api_key.org_id != org_id:
            return False
        api_key.is_active = False
        await self.db.commit()
        return True

    async def list_for_org(self, org_id: uuid.UUID) -> list[APIKey]:
        """Список всех ключей организации (только активные)."""
        result = await self.db.execute(
            select(APIKey)
            .where(APIKey.org_id == org_id, APIKey.is_active.is_(True))
            .order_by(APIKey.created_at.desc())
        )
        return list(result.scalars().all())
