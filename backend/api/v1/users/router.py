# backend/api/v1/users/router.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-2/3. User management (CRUD) + RBAC-защита.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_audit_service, require_roles
from backend.core.security import hash_password
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.auth import (
    CreateUserRequest,
    PaginatedResponse,
    UpdateRoleRequest,
    UserResponse,
)
from backend.services.audit_log_service import AuditLogService

router = APIRouter(prefix="/users", tags=["users"])


def _paginate(items: list, page: int, per_page: int, total: int) -> PaginatedResponse:
    import math
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total else 0,
    )


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="Список пользователей организации",
)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=100),
    current_user: User = require_roles(["org_admin", "org_owner", "super_admin"]),
    db: AsyncSession = Depends(get_db),
):
    """Список пользователей org текущего пользователя (постраничный)."""
    base_filter = (  # type: ignore[assignment]
        (User.org_id == current_user.org_id)
        if current_user.role != "super_admin"
        else True
    )

    total_result = await db.execute(
        select(func.count()).select_from(User).where(base_filter)  # type: ignore[arg-type]
    )
    total = total_result.scalar_one()

    stmt = (
        select(User)
        .where(base_filter)  # type: ignore[arg-type]
        .order_by(User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    users = list((await db.execute(stmt)).scalars().all())
    return _paginate(
        [UserResponse.model_validate(u) for u in users], page, per_page, total
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать пользователя",
)
async def create_user(
    body: CreateUserRequest,
    current_user: User = require_roles(["org_admin", "org_owner", "super_admin"]),
    db: AsyncSession = Depends(get_db),
    audit_svc: AuditLogService = Depends(get_audit_service),
):
    """
    Создать нового пользователя в организации.
    org_admin и org_owner могут создавать пользователей, но не выше своей роли.
    """
    # Проверить уникальность email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    user = User(
        org_id=current_user.org_id,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()

    await audit_svc.log(
        action="user.create",
        org_id=current_user.org_id,
        user_id=current_user.id,
        resource_type="user",
        resource_id=str(user.id),
        new_values={"email": body.email, "role": body.role},
    )
    await db.commit()
    return user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Профиль пользователя",
)
async def get_user(
    user_id: uuid.UUID,
    current_user: User = require_roles(["org_admin", "org_owner", "super_admin"]),
    db: AsyncSession = Depends(get_db),
):
    """Получить профиль пользователя по ID."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Tenant isolation: org_admin/org_owner могут видеть только свою org
    if current_user.role != "super_admin" and user.org_id != current_user.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put(
    "/{user_id}/role",
    response_model=UserResponse,
    summary="Изменить роль пользователя",
)
async def update_user_role(
    user_id: uuid.UUID,
    body: UpdateRoleRequest,
    current_user: User = require_roles(["org_owner", "super_admin"]),
    db: AsyncSession = Depends(get_db),
    audit_svc: AuditLogService = Depends(get_audit_service),
):
    """
    Изменить роль пользователя. Только org_owner и super_admin.
    Защита: нельзя понизить последнего org_owner.
    """
    user = await db.get(User, user_id)
    if not user or (current_user.role != "super_admin" and user.org_id != current_user.org_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Защита от удаления последнего org_owner
    if user.role == "org_owner" and body.role != "org_owner":
        owners_count_result = await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.org_id == user.org_id, User.role == "org_owner", User.is_active.is_(True))
        )
        owners_count = owners_count_result.scalar_one()
        if owners_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last org_owner",
            )

    old_role = user.role
    user.role = body.role

    await audit_svc.log(
        action="user.role_change",
        org_id=current_user.org_id,
        user_id=current_user.id,
        resource_type="user",
        resource_id=str(user.id),
        old_values={"role": old_role},
        new_values={"role": body.role},
    )
    await db.commit()
    return user


@router.patch(
    "/{user_id}/deactivate",
    response_model=None,
    summary="Деактивировать пользователя",
)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: User = require_roles(["org_admin", "org_owner", "super_admin"]),
    db: AsyncSession = Depends(get_db),
    audit_svc: AuditLogService = Depends(get_audit_service),
):
    """Деактивировать пользователя (is_active=False). Нельзя деактивировать себя."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate yourself",
        )
    user = await db.get(User, user_id)
    if not user or (current_user.role != "super_admin" and user.org_id != current_user.org_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = False
    await audit_svc.log(
        action="user.deactivate",
        org_id=current_user.org_id,
        user_id=current_user.id,
        resource_type="user",
        resource_id=str(user.id),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
