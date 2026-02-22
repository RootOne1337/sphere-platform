# backend/core/dependencies.py
# ВЛАДЕЛЕЦ: TZ-01. Stub в TZ-00 для FastAPI dependencies.
# Полная реализация JWT-валидации — TZ-01 SPLIT-1.
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
    FastAPI dependency: извлечь и проверить текущего пользователя из JWT.
    Полная реализация — TZ-01 SPLIT-1.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # TZ-01 SPLIT-1 реализует полную JWT-валидацию здесь
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not implemented yet — TZ-01 SPLIT-1",
    )


async def get_tenant_db(
    db: AsyncSession = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
) -> AsyncSession:
    """
    Session с активным RLS-контекстом арендатора.
    Используй вместо get_db во всех endpoints с бизнес-данными.
    """
    from sqlalchemy import text
    await db.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(current_user.org_id)},
    )
    return db
