# backend/core/dependencies.py
# ВЛАДЕЛЕЦ: TZ-01. Stub в TZ-00 для FastAPI dependencies.
# Полная реализация JWT-валидации  TZ-01 SPLIT-1.
from typing import TYPE_CHECKING
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import get_db

if TYPE_CHECKING:
    from backend.models.user import User

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> "User":
    """
    FastAPI dependency: extract and validate current user from JWT.
    Full implementation: TZ-01 SPLIT-1.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # TZ-01 SPLIT-1 implements full JWT validation here
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not implemented yet  TZ-01 SPLIT-1",
    )


def require_role(*roles: str):
    """
    Dependency factory: ensure the current user has one of the required roles.

    Usage:
        current_user = Depends(require_role("org_admin"))
        current_user = Depends(require_role("org_admin", "device_manager"))
    """
    async def _check_role(user=Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role(s): {', '.join(roles)}",
            )
        return user
    return _check_role


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
