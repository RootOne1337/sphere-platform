# SPLIT-1 — JWT Login / Refresh / Logout

**ТЗ-родитель:** TZ-01-Auth-Service  
**Ветка:** `stage/1-auth`  
**Задача:** `SPHERE-006`  
**Исполнитель:** Backend  
**Оценка:** 1 рабочий день  
**Блокирует:** TZ-01 SPLIT-2, SPLIT-3, SPLIT-4, SPLIT-5 (все защищённые endpoints)
**Интеграция при merge:** При объединении с TZ-10 Frontend подключить auth interceptors к реальному API

> [!NOTE]
> **MERGE-6/7/8: Auth интеграция при merge:**
>
> | # | При merge с | Действие |
> |---|-----------|---------|
> | MERGE-6 | TZ-10 Frontend | Заменить mock `/auth/refresh` на реальный endpoint; проверить `useInitAuth()` cookie flow |
> | MERGE-7 | TZ-02, TZ-04 | Заменить mock `@require_permission()` декораторы на реальные из `backend/core/auth/rbac.py` |
> | MERGE-8 | TZ-09 n8n | Заменить mock API Key валидацию на реальную `api_key_service.validate()` в n8n webhook auth |

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-1` — НЕ в `sphere-platform`.
> Ветка `stage/1-auth` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-1
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/1-auth
pwd                          # ОБЯЗАНА содержать: sphere-stage-1
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-1 stage/1-auth
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/1-auth` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/1-auth` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `backend/api/v1/auth/` | `backend/main.py` 🔴 |
| `backend/services/auth_*`, `backend/services/mfa_*` | `backend/core/config.py` 🔴 |
| `backend/schemas/auth*`, `backend/schemas/mfa*` | `backend/core/database.py` 🔴 |
| `backend/models/refresh_token.py`, `backend/models/api_key.py` | `backend/models/` (только TZ-00 создаёт!) 🔴 |
| `backend/core/security.py`, `backend/core/dependencies.py` | `backend/database/` 🔴 |
| `backend/middleware/audit.py` | `docker-compose*.yml` 🔴 |
| `backend/services/audit_log_service.py`, `backend/core/exceptions.py` | Файлы других этапов 🔴 |
| `tests/test_auth*` | `backend/main.py` 🔴 |

---

## Цель Сплита

Реализовать полный auth flow: login → access token + refresh token, обновление токена, logout с инвалидацией. Refresh token хранится в HTTPOnly cookie, access token — в памяти браузера. Исправлена P0 уязвимость (JWT не в URL).

---

## Предусловия

- [ ] TZ-00 выполнен (DB + Redis)
- [ ] Таблицы `users`, `organizations`, `refresh_tokens` в БД

---

## Шаг 1 — JWT функции

```python
# backend/core/security.py
from datetime import datetime, timedelta, timezone
import uuid
import bcrypt
import jwt
from backend.core.config import settings

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def create_access_token(user_id: str, org_id: str, role: str) -> tuple[str, str]:
    """Возвращает (token, jti)."""
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "role": role,
        "jti": jti,
        "type": "access",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        ),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti

def decode_access_token(token: str) -> dict:
    """Декодирует и валидирует access token. Поднимает исключение при проблемах."""
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["sub", "jti", "type", "exp"]},
    )

def decode_expired_access_token(token: str) -> dict:
    """
    FIX-1.4: Декодировать токен БЕЗ проверки срока действия.
    Используется ИСКЛЮЧИТЕЛЬНО для logout — пользователь с протухшим
    access token должен мочь удалить refresh cookie и отозвать токен.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False, "require": ["sub", "jti", "type"]},
    )

def create_refresh_token() -> str:
    """Opaque random refresh token — хранится в БД как SHA-256 хэш."""
    import secrets
    return secrets.token_urlsafe(64)
```

---

## Шаг 2 — Auth Service

```python
# backend/services/auth_service.py
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.models import User, RefreshToken
from backend.core.security import (
    verify_password, hash_password,
    create_access_token, decode_access_token,
    create_refresh_token,
)
from backend.core.config import settings
from backend.services.cache_service import CacheService

class AuthService:
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache
    
    async def login(self, email: str, password: str, ip: str) -> dict:
        # Rate limit: 5 попыток с IP за 60 секунд
        allowed = await self.cache.check_rate_limit(f"login:{ip}", 5, 60)
        if not allowed:
            raise TooManyAttemptsError("Too many login attempts. Try again in 60 seconds.")
        
        # Найти пользователя
        user = await self._get_user_by_email(email)
        if not user or not user.is_active:
            raise InvalidCredentialsError()
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        
        # FIX-1.1: Проверка MFA ПЕРЕД выдачей токенов.
        # Если MFA включен — НЕ выдавать JWT! Вместо этого создать
        # временный state_token в Redis и попросить TOTP-код.
        if getattr(user, "mfa_enabled", False):
            state_token = secrets.token_urlsafe(32)
            await self.cache.set(
                f"mfa:state:{state_token}",
                str(user.id),
                ttl=300,  # 5 минут на ввод TOTP
            )
            return {
                "mfa_required": True,
                "state_token": state_token,
            }
        
        # Создать токены (только если MFA отключен)
        access_token, jti = create_access_token(
            str(user.id), str(user.org_id), user.role
        )
        refresh_token_raw = create_refresh_token()
        refresh_token_hash = hashlib.sha256(refresh_token_raw.encode()).hexdigest()
        
        # Сохранить refresh token в БД
        rt = RefreshToken(
            user_id=user.id,
            token_hash=refresh_token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(
                days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
            ),
        )
        self.db.add(rt)
        
        # Обновить last_login_at
        user.last_login_at = datetime.now(timezone.utc)
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "refresh_token": refresh_token_raw,  # отправляем RAW, в куку
        }
    
    async def refresh(self, refresh_token_raw: str) -> dict:
        token_hash = hashlib.sha256(refresh_token_raw.encode()).hexdigest()
        
        rt = await self._get_refresh_token(token_hash)
        if not rt or rt.expires_at < datetime.now(timezone.utc) or rt.is_revoked:
            raise InvalidTokenError("Refresh token expired or revoked")
        
        user = await self._get_user(rt.user_id)
        if not user or not user.is_active:
            raise InvalidTokenError()
        
        # Rotate refresh token (каждое обновление → новый refresh token)
        rt.is_revoked = True
        new_refresh_raw = create_refresh_token()
        new_refresh_hash = hashlib.sha256(new_refresh_raw.encode()).hexdigest()
        new_rt = RefreshToken(
            user_id=user.id,
            token_hash=new_refresh_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(
                days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
            ),
        )
        self.db.add(new_rt)
        
        access_token, _ = create_access_token(
            str(user.id), str(user.org_id), user.role
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "refresh_token": new_refresh_raw,
        }
    
    async def logout(self, jti: str, token_exp: int, refresh_token_raw: str | None):
        # Blacklist access token в Redis (до истечения)
        expires_in = timedelta(seconds=token_exp - int(datetime.now(timezone.utc).timestamp()))
        if expires_in.total_seconds() > 0:
            await self.cache.blacklist_token(jti, expires_in)
        
        # Отозвать refresh token если передан
        if refresh_token_raw:
            token_hash = hashlib.sha256(refresh_token_raw.encode()).hexdigest()
            rt = await self._get_refresh_token(token_hash)
            if rt:
                rt.is_revoked = True
```

---

## Шаг 3 — Auth Router

```python
# backend/api/v1/auth.py
from fastapi import APIRouter, Depends, Response, Cookie, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.services.auth_service import AuthService
from backend.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)

REFRESH_COOKIE_NAME = "refresh_token"
COOKIE_SETTINGS = {
    "httponly": True,
    "secure": True,
    "samesite": "strict",
    "max_age": 7 * 24 * 3600,  # 7 дней
}

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
):
    ip = request.client.host
    result = await auth_svc.login(body.email, body.password, ip)
    
    # Refresh token — HTTPOnly Secure cookie (НЕ в теле ответа для безопасности)
    response.set_cookie(REFRESH_COOKIE_NAME, result["refresh_token"], **COOKIE_SETTINGS)
    
    return TokenResponse(
        access_token=result["access_token"],
        token_type="bearer",
        expires_in=result["expires_in"],
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    auth_svc: AuthService = Depends(get_auth_service),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    
    result = await auth_svc.refresh(refresh_token)
    response.set_cookie(REFRESH_COOKIE_NAME, result["refresh_token"], **COOKIE_SETTINGS)
    
    return TokenResponse(access_token=result["access_token"], token_type="bearer")

@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    auth_svc: AuthService = Depends(get_auth_service),
):
    if credentials:
        # FIX-1.4: Использовать decode_expired_access_token для logout.
        # Пользователь с протухшим токеном ДОЛЖЕН мочь логаутиться!
        payload = decode_expired_access_token(credentials.credentials)
        await auth_svc.logout(
            jti=payload["jti"],
            token_exp=payload["exp"],
            refresh_token_raw=refresh_token,
        )
    response.delete_cookie(REFRESH_COOKIE_NAME)

@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
```

---

## Шаг 4 — Dependency: get_current_user

```python
# backend/core/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.core.security import decode_access_token
from backend.services.cache_service import CacheService

bearer_scheme = HTTPBearer()

async def get_current_user(
    request: Request,  # FIX-1.3: нужен для request.state.principal
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache),
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Проверить blacklist
    if await cache.is_token_blacklisted(payload["jti"]):
        raise HTTPException(status_code=401, detail="Token revoked")
    
    user = await get_user_by_id(payload["sub"], db)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    
    # FIX-1.3: Прокидываем principal в request.state для audit middleware.
    # Без этого audit_middleware получает principal=None и не пишет логи!
    request.state.principal = user
    
    return user
```

---

## Шаг 5 — Exceptions + Dependency Factories

```python
# backend/core/exceptions.py  (создать новый файл)
class TooManyAttemptsError(Exception):
    def __init__(self, msg: str = "Too many attempts"):
        super().__init__(msg)

class InvalidCredentialsError(Exception):
    pass

class InvalidTokenError(Exception):
    pass
```

```python
# backend/core/dependencies.py  (добавить фабрики сервисов после get_current_user)
from backend.services.auth_service import AuthService
from backend.services.cache_service import CacheService

def get_cache(request: Request) -> CacheService:
    return CacheService(request.app.state.redis)

def get_auth_service(
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache),
) -> AuthService:
    return AuthService(db, cache)
```

```python
# backend/api/v1/auth.py  (добавить импорты + exception handlers в /login)
from backend.core.dependencies import get_auth_service, get_current_user
from backend.core.exceptions import TooManyAttemptsError, InvalidCredentialsError, InvalidTokenError

# В роутере /login заменить:
    try:
        result = await auth_svc.login(body.email, body.password, ip)
    except TooManyAttemptsError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid email or password")

# В /refresh:
    try:
        result = await auth_svc.refresh(refresh_token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
```

---

## Критерии готовности

- [ ] `POST /auth/login` → access_token + refresh_token cookie
- [ ] `POST /auth/refresh` → новый access_token + новый refresh cookie (rotation)
- [ ] `POST /auth/logout` → cookie удалена, access token в blacklist Redis
- [ ] После logout старый access token возвращает 401
- [ ] 6-я попытка логина с одного IP → 429 Too Many Requests
- [ ] JWT НЕ передаётся в URL ни при каких обстоятельствах
- [ ] Тесты покрывают все случаи (login ok, bad pass, expired, blacklisted, rate limit)
