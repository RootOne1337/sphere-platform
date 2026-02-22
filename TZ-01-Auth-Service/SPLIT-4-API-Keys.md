# SPLIT-4 — API Keys для машинных интеграций

**ТЗ-родитель:** TZ-01-Auth-Service  
**Ветка:** `stage/1-auth`  
**Задача:** `SPHERE-009`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** TZ-01 SPLIT-5
**Интеграция при merge:** TZ-09 n8n работает с mock API key; при merge подключить реальную валидацию

---

## Цель Сплита

API Keys для сервисных аккаунтов (n8n, PC Agent). Ключ показывается один раз, хранится как SHA-256 хэш, легко отзывается.

---

## Шаг 1 — API Key формат и хранение

```
Формат: sphr_{env}_{random_32_hex}
Пример: sphr_prod_a1b2c3d4e5f67890abcdef1234567890

Алгоритм:
  1. Генерируем random_hex = secrets.token_hex(32)
  2. Полный ключ = f"sphr_{env}_{random_hex}"
  3. В БД храним SHA-256(полный ключ)
  4. Ключ показываем пользователю ОДИН РАЗ при создании
  5. При аутентификации: SHA-256(входящий ключ) → lookup в БД
```

---

## Шаг 2 — Сервис

```python
# backend/services/api_key_service.py
import hashlib, secrets
from backend.models import APIKey

class APIKeyService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_api_key(
        self,
        org_id: uuid.UUID,
        name: str,
        permissions: list[str],
        expires_at: datetime | None,
        created_by: uuid.UUID,
    ) -> tuple[APIKey, str]:
        """Возвращает (api_key_record, raw_key). raw_key показать ОДИН РАЗ."""
        env = settings.ENVIRONMENT[:4]  # prod, stag, dev
        random_part = secrets.token_hex(32)
        raw_key = f"sphr_{env}_{random_part}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:14]  # "sphr_prod_a1b2" — для отображения
        
        api_key = APIKey(
            org_id=org_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            permissions=permissions,
            expires_at=expires_at,
            created_by=created_by,
        )
        self.db.add(api_key)
        await self.db.flush()
        return api_key, raw_key
    
    async def authenticate(self, raw_key: str) -> APIKey | None:
        """Аутентифицировать по API ключу."""
        if not raw_key.startswith("sphr_"):
            return None
        
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        stmt = select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True,
            or_(APIKey.expires_at.is_(None), APIKey.expires_at > datetime.now(timezone.utc)),
        )
        result = await self.db.execute(stmt)
        api_key = result.scalar_one_or_none()
        
        if api_key:
            # Обновляем last_used_at без блокировки
            await self.db.execute(
                update(APIKey).where(APIKey.id == api_key.id)
                .values(last_used_at=datetime.now(timezone.utc))
            )
        return api_key
```

---

## Шаг 3 — Поддержка API Key в get_current_user

```python
# backend/core/dependencies.py — расширить

async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache),
) -> User | APIKey:
    """
    Аутентификация: JWT Bearer ИЛИ X-API-Key header.
    Возвращает User или APIKey в зависимости от типа авторизации.
    """
    if x_api_key:
        api_key_svc = APIKeyService(db)
        key = await api_key_svc.authenticate(x_api_key)
        if not key:
            raise HTTPException(401, "Invalid API key")
        return key
    
    if credentials:
        return await get_current_user(credentials, db, cache)
    
    raise HTTPException(401, "Authentication required")
```

---

## Критерии готовности

- [ ] `POST /auth/api-keys` → raw key показан ОДИН РАЗ
- [ ] `X-API-Key: sphr_prod_...` → защищённый endpoint работает
- [ ] Истёкший ключ → 401
- [ ] Отозванный ключ → 401
- [ ] Ключ НЕ отображается в логах (только prefix типа `sphr_prod_a1b2...`)
- [ ] Gitleaks детектирует `sphr_` паттерн в коде
