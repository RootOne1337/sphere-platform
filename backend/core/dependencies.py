# backend/core/dependencies.py
# ВЛАДЕЛЕЦ: TZ-01. Полная реализация FastAPI dependencies: JWT-валидация, RBAC, service factories.
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.rbac import has_permission
from backend.core.security import decode_access_token
from backend.database.engine import get_db

if TYPE_CHECKING:
    from backend.models.api_key import APIKey
    from backend.models.user import User

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> "User":
    """
    FastAPI dependency: извлечь и проверить текущего пользователя из JWT Bearer token.
    Прокидывает user в request.state.principal для audit middleware (FIX-1.3).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Проверить blacklist в Redis
    from backend.services.cache_service import CacheService
    cache = CacheService()
    if await cache.is_token_blacklisted(payload["jti"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    # Загрузить пользователя из БД
    from backend.models.user import User
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # FIX-1.3: Прокидываем principal в request.state для audit middleware.
    # Без этого audit_middleware получает principal=None и не пишет логи!
    request.state.principal = user

    return user


async def get_tenant_db(
    db: AsyncSession = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
) -> AsyncSession:
    """
    Session with active tenant RLS context.
    Use instead of get_db for all endpoints with business data.
    """
    from sqlalchemy import text
    await db.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(current_user.org_id)},
    )
    return db


# ── Service factories ────────────────────────────────────────────────────────

def get_cache():
    """Dependency factory для CacheService."""
    from backend.services.cache_service import CacheService
    return CacheService()


def get_auth_service(db: AsyncSession = Depends(get_db)):
    """Dependency factory для AuthService."""
    from backend.services.auth_service import AuthService
    from backend.services.cache_service import CacheService
    return AuthService(db, CacheService())


def get_audit_service(db: AsyncSession = Depends(get_db)):
    """Dependency factory для AuditLogService."""
    from backend.services.audit_log_service import AuditLogService
    return AuditLogService(db)


# ── RBAC dependencies ────────────────────────────────────────────────────────

def require_roles(roles: list[str]):
    """
    Dependency-фабрика: требует одну из указанных ролей.

    Usage:
        @router.get("/admin")
        async def admin(user: User = require_roles(["org_admin", "org_owner"])):
    """
    async def dependency(current_user: "User" = Depends(get_current_user)) -> "User":
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required roles: {roles}. Your role: {current_user.role}",
            )
        return current_user
    return Depends(dependency)


def require_role(*roles: str):
    """
    Dependency-фабрика: ВОЗВРАЩАЕТ callable.
    Используется как: current_user = Depends(require_role("org_admin"))
                  или: current_user = Depends(require_role("org_admin", "device_manager"))
    """
    async def _check(current_user: "User" = Depends(get_current_user)) -> "User":
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role(s): {', '.join(roles)}. Your role: {current_user.role}",
            )
        return current_user
    return _check


def require_permission(permission: str):
    """
    Dependency-фабрика: требует право на действие из RBAC матрицы.

    Usage:
        @router.delete("/devices/{id}")
        async def delete_device(user: User = require_permission("device:delete")):
    """
    async def dependency(current_user: "User" = Depends(get_current_user)) -> "User":
        if not has_permission(current_user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}",
            )
        return current_user
    return Depends(dependency)


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> "User | APIKey":
    """
    Аутентификация: JWT Bearer ИЛИ X-API-Key header.
    Возвращает User или APIKey в зависимости от типа авторизации.
    Используется в endpoints, доступных как пользователям, так и сервисным аккаунтам.
    """
    if x_api_key:
        from backend.services.api_key_service import APIKeyService
        api_key_svc = APIKeyService(db)
        key = await api_key_svc.authenticate(x_api_key)
        if not key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        request.state.principal = key
        return key

    if credentials:
        return await get_current_user(request, credentials, db)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )

