# backend/api/v1/game_accounts/router.py
# ВЛАДЕЛЕЦ: TZ-10 Game Account Management.
# API-эндпоинты для управления игровыми аккаунтами.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.game_accounts import (
    AccountStatsResponse,
    AssignAccountRequest,
    CreateGameAccountRequest,
    GameAccountListResponse,
    GameAccountResponse,
    GameAccountWithPasswordResponse,
    ImportAccountsRequest,
    ImportAccountsResponse,
    ReleaseAccountRequest,
    ServerInfo,
    ServerListResponse,
    UpdateGameAccountRequest,
)
from backend.services.game_account_service import GameAccountService

router = APIRouter(prefix="/game-accounts", tags=["game-accounts"])


# ── DI-фабрика ──────────────────────────────────────────────────────────────


def get_game_account_service(db: AsyncSession = Depends(get_db)) -> GameAccountService:
    """
    DI-фабрика для GameAccountService.
    FastAPI дедуплицирует Depends(get_db) — один запрос = одна сессия.
    """
    return GameAccountService(db)


# ── Stats (до /{account_id} чтобы FastAPI не парсил "stats" как UUID) ────────


@router.get(
    "/stats",
    response_model=AccountStatsResponse,
    summary="Статистика аккаунтов: количество по статусам + список игр",
)
async def get_account_stats(
    current_user: User = require_permission("account:read"),
    svc: GameAccountService = Depends(get_game_account_service),
) -> AccountStatsResponse:
    return await svc.get_stats(org_id=current_user.org_id)

# ── Servers (list доступных серверов Black Russia) ─────────────────


@router.get(
    "/servers",
    response_model=ServerListResponse,
    summary="Список всех игровых серверов (90 серверов Black Russia)",
)
async def list_servers(
    current_user: User = require_permission("account:read"),
) -> ServerListResponse:
    import json
    from pathlib import Path

    servers_path = Path(__file__).resolve().parents[3] / "core" / "servers.json"
    data = json.loads(servers_path.read_text(encoding="utf-8"))
    servers = [ServerInfo(**s) for s in data]
    return ServerListResponse(servers=servers, total=len(servers))

# ── List ─────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=GameAccountListResponse,
    summary="Список игровых аккаунтов с пагинацией, фильтрацией и сортировкой",
)
async def list_game_accounts(
    game: str | None = Query(None, description="Фильтр по игре"),
    status: str | None = Query(None, description="Фильтр по статусу"),
    device_id: uuid.UUID | None = Query(None, description="Фильтр по устройству"),
    server_name: str | None = Query(None, description="Фильтр по серверу (RED, MOSCOW, KAZAN...)"),
    search: str | None = Query(None, description="Поиск по логину / игре / никнейму / серверу"),
    sort_by: str = Query("created_at", description="Поле сортировки"),
    sort_dir: str = Query("desc", regex="^(asc|desc)$", description="Направление сортировки"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=5000),
    current_user: User = require_permission("account:read"),
    svc: GameAccountService = Depends(get_game_account_service),
    db: AsyncSession = Depends(get_db),
) -> GameAccountListResponse:
    accounts, total = await svc.list_accounts(
        org_id=current_user.org_id,
        game=game,
        status=status,
        device_id=device_id,
        server_name=server_name,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    await db.commit()
    return GameAccountListResponse(
        items=accounts, total=total, page=page, per_page=per_page, pages=pages,
    )


# ── Create ───────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=GameAccountResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Создать игровой аккаунт",
)
async def create_game_account(
    body: CreateGameAccountRequest,
    current_user: User = require_permission("account:write"),
    svc: GameAccountService = Depends(get_game_account_service),
    db: AsyncSession = Depends(get_db),
) -> GameAccountResponse:
    result = await svc.create_account(org_id=current_user.org_id, data=body)
    await db.commit()
    return result


# ── Import ───────────────────────────────────────────────────────────────────


@router.post(
    "/import",
    response_model=ImportAccountsResponse,
    summary="Массовый импорт аккаунтов (до 1000 за раз)",
)
async def import_game_accounts(
    body: ImportAccountsRequest,
    current_user: User = require_permission("account:write"),
    svc: GameAccountService = Depends(get_game_account_service),
    db: AsyncSession = Depends(get_db),
) -> ImportAccountsResponse:
    result = await svc.import_accounts(org_id=current_user.org_id, items=body.accounts)
    await db.commit()
    return result


# ── Get one ──────────────────────────────────────────────────────────────────


@router.get(
    "/{account_id}",
    response_model=GameAccountResponse | GameAccountWithPasswordResponse,
    summary="Получить аккаунт по ID",
)
async def get_game_account(
    account_id: uuid.UUID,
    show_password: bool = Query(False, description="Показать пароль в ответе"),
    current_user: User = require_permission("account:read"),
    svc: GameAccountService = Depends(get_game_account_service),
) -> GameAccountResponse | GameAccountWithPasswordResponse:
    return await svc.get_account(
        account_id=account_id,
        org_id=current_user.org_id,
        show_password=show_password,
    )


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch(
    "/{account_id}",
    response_model=GameAccountResponse,
    summary="Обновить поля аккаунта (PATCH-семантика)",
)
async def update_game_account(
    account_id: uuid.UUID,
    body: UpdateGameAccountRequest,
    current_user: User = require_permission("account:write"),
    svc: GameAccountService = Depends(get_game_account_service),
    db: AsyncSession = Depends(get_db),
) -> GameAccountResponse:
    result = await svc.update_account(
        account_id=account_id,
        org_id=current_user.org_id,
        data=body,
    )
    await db.commit()
    return result


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete(
    "/{account_id}",
    summary="Удалить аккаунт",
)
async def delete_game_account(
    account_id: uuid.UUID,
    current_user: User = require_permission("account:write"),
    svc: GameAccountService = Depends(get_game_account_service),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await svc.delete_account(account_id=account_id, org_id=current_user.org_id)
    await db.commit()
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


# ── Assign ───────────────────────────────────────────────────────────────────


@router.post(
    "/{account_id}/assign",
    response_model=GameAccountResponse,
    summary="Назначить аккаунт на устройство",
)
async def assign_game_account(
    account_id: uuid.UUID,
    body: AssignAccountRequest,
    current_user: User = require_permission("account:write"),
    svc: GameAccountService = Depends(get_game_account_service),
    db: AsyncSession = Depends(get_db),
) -> GameAccountResponse:
    result = await svc.assign_account(
        account_id=account_id,
        org_id=current_user.org_id,
        data=body,
    )
    await db.commit()
    return result


# ── Release ──────────────────────────────────────────────────────────────────


@router.post(
    "/{account_id}/release",
    response_model=GameAccountResponse,
    summary="Освободить аккаунт (снять с устройства)",
)
async def release_game_account(
    account_id: uuid.UUID,
    body: ReleaseAccountRequest,
    current_user: User = require_permission("account:write"),
    svc: GameAccountService = Depends(get_game_account_service),
    db: AsyncSession = Depends(get_db),
) -> GameAccountResponse:
    result = await svc.release_account(
        account_id=account_id,
        org_id=current_user.org_id,
        data=body,
    )
    await db.commit()
    return result
