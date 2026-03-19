# backend/services/game_account_service.py
# ВЛАДЕЛЕЦ: TZ-10 Game Account Management.
# Сервис управления игровыми аккаунтами: CRUD, назначение/освобождение,
# массовый импорт, статистика.
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.game_account import AccountStatus, GameAccount, GenderEnum, VipType
from backend.schemas.game_accounts import (
    AccountStatsResponse,
    AssignAccountRequest,
    CreateGameAccountRequest,
    GameAccountResponse,
    GameAccountWithPasswordResponse,
    ImportAccountItem,
    ImportAccountsResponse,
    ReleaseAccountRequest,
    UpdateGameAccountRequest,
)


class GameAccountService:
    """
    Сервис для операций с игровыми аккаунтами.

    Все методы НЕ делают commit — это ответственность роутера.
    flush используется для получения id до commit.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _get_account(self, account_id: uuid.UUID, org_id: uuid.UUID) -> GameAccount:
        """Загрузить аккаунт по id + org_id; 404 если не найден."""
        stmt = (
            select(GameAccount)
            .options(selectinload(GameAccount.device))
            .where(
                GameAccount.id == account_id,
                GameAccount.org_id == org_id,
            )
        )
        account = (await self.db.execute(stmt)).scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Аккаунт не найден")
        return account

    def _to_response(self, account: GameAccount) -> GameAccountResponse:
        """Конвертировать ORM-объект в Pydantic-ответ."""
        device_name = None
        if account.device:
            device_name = account.device.name

        return GameAccountResponse(
            id=account.id,
            org_id=account.org_id,
            game=account.game,
            login=account.login,
            status=account.status.value if isinstance(account.status, AccountStatus) else str(account.status),
            status_reason=account.status_reason,
            status_changed_at=account.status_changed_at,
            device_id=account.device_id,
            device_name=device_name,
            assigned_at=account.assigned_at,
            # Игровой сервер и персонаж
            server_name=account.server_name,
            nickname=account.nickname,
            gender=account.gender.value if account.gender and hasattr(account.gender, 'value') else account.gender,
            # Игровая статистика
            level=account.level,
            target_level=account.target_level,
            experience=account.experience,
            balance_rub=account.balance_rub,
            balance_bc=account.balance_bc,
            last_balance_update=account.last_balance_update,
            is_leveled=account.is_leveled,
            # VIP и законопослушность
            vip_type=account.vip_type.value if account.vip_type and hasattr(account.vip_type, 'value') else account.vip_type,
            vip_expires_at=account.vip_expires_at,
            lawfulness=account.lawfulness,
            # Статистика
            total_bans=account.total_bans,
            last_ban_at=account.last_ban_at,
            ban_reason=account.ban_reason,
            total_sessions=account.total_sessions,
            last_session_end=account.last_session_end,
            cooldown_until=account.cooldown_until,
            # Регистрационные данные
            registered_at=account.registered_at,
            registration_provider=account.registration_provider,
            meta=account.meta or {},
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    def _to_response_with_password(self, account: GameAccount) -> GameAccountWithPasswordResponse:
        """Конвертировать ORM-объект в Pydantic-ответ С паролем."""
        base = self._to_response(account)
        return GameAccountWithPasswordResponse(
            **base.model_dump(),
            password=account.password_encrypted,
        )

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_account(
        self, org_id: uuid.UUID, data: CreateGameAccountRequest,
    ) -> GameAccountResponse:
        """Создать новый игровой аккаунт. Проверяет уникальность login+game в org."""
        # Проверка уникальности
        dup = (
            await self.db.execute(
                select(GameAccount).where(
                    GameAccount.org_id == org_id,
                    GameAccount.game == data.game,
                    GameAccount.login == data.login,
                )
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"Аккаунт '{data.login}' для игры '{data.game}' уже существует",
            )

        account = GameAccount(
            org_id=org_id,
            game=data.game,
            login=data.login,
            password_encrypted=data.password,
            status=AccountStatus.free,
            status_changed_at=datetime.now(timezone.utc),
            # Сервер и персонаж
            server_name=data.server_name,
            nickname=data.nickname,
            gender=GenderEnum(data.gender) if data.gender else None,
            # Игровая статистика
            level=data.level,
            target_level=data.target_level,
            experience=data.experience,
            balance_rub=data.balance_rub,
            balance_bc=data.balance_bc,
            last_balance_update=datetime.now(timezone.utc) if data.balance_rub is not None else None,
            # VIP и законопослушность
            vip_type=VipType(data.vip_type) if data.vip_type else None,
            vip_expires_at=data.vip_expires_at,
            lawfulness=data.lawfulness,
            # Регистрационные данные
            registered_at=data.registered_at,
            registration_ip=data.registration_ip,
            registration_location=data.registration_location,
            registration_provider=data.registration_provider,
            meta=data.meta or {},
        )
        self.db.add(account)
        await self.db.flush()
        await self.db.refresh(account)

        return self._to_response(account)

    # ── List ─────────────────────────────────────────────────────────────────

    async def list_accounts(
        self,
        org_id: uuid.UUID,
        game: str | None = None,
        status: str | None = None,
        device_id: uuid.UUID | None = None,
        server_name: str | None = None,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[GameAccountResponse], int]:
        """Пагинированный список с фильтрами и сортировкой."""
        conditions = [GameAccount.org_id == org_id]

        if game:
            conditions.append(GameAccount.game == game)

        if status:
            try:
                conditions.append(GameAccount.status == AccountStatus(status))
            except ValueError:
                pass  # Неизвестный статус — forward compat

        if device_id:
            conditions.append(GameAccount.device_id == device_id)

        if server_name:
            conditions.append(GameAccount.server_name == server_name)

        if search:
            like = f"%{search}%"
            conditions.append(
                or_(
                    GameAccount.login.ilike(like),
                    GameAccount.game.ilike(like),
                    GameAccount.nickname.ilike(like),
                    GameAccount.server_name.ilike(like),
                    GameAccount.status_reason.ilike(like),
                )
            )

        # Сортировка (белый список полей)
        sort_columns = {
            "created_at": GameAccount.created_at,
            "login": GameAccount.login,
            "game": GameAccount.game,
            "status": GameAccount.status,
            "level": GameAccount.level,
            "balance_rub": GameAccount.balance_rub,
            "balance_bc": GameAccount.balance_bc,
            "total_bans": GameAccount.total_bans,
            "total_sessions": GameAccount.total_sessions,
            "assigned_at": GameAccount.assigned_at,
            "server_name": GameAccount.server_name,
            "nickname": GameAccount.nickname,
            "experience": GameAccount.experience,
            "lawfulness": GameAccount.lawfulness,
            "registered_at": GameAccount.registered_at,
        }
        sort_col = sort_columns.get(sort_by, GameAccount.created_at)
        order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

        # Count
        count_stmt = select(func.count()).select_from(GameAccount).where(*conditions)
        total = (await self.db.execute(count_stmt)).scalar_one()

        # Data
        stmt = (
            select(GameAccount)
            .options(selectinload(GameAccount.device))
            .where(*conditions)
            .order_by(order)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(stmt)).scalars().all()

        return [self._to_response(a) for a in rows], total

    # ── Get one ──────────────────────────────────────────────────────────────

    async def get_account(
        self, account_id: uuid.UUID, org_id: uuid.UUID, show_password: bool = False,
    ) -> GameAccountResponse | GameAccountWithPasswordResponse:
        """Получить один аккаунт. С паролем — только по явному флагу."""
        account = await self._get_account(account_id, org_id)
        if show_password:
            return self._to_response_with_password(account)
        return self._to_response(account)

    # ── Update ───────────────────────────────────────────────────────────────

    async def update_account(
        self,
        account_id: uuid.UUID,
        org_id: uuid.UUID,
        data: UpdateGameAccountRequest,
    ) -> GameAccountResponse:
        """Обновить поля аккаунта (PATCH-семантика)."""
        account = await self._get_account(account_id, org_id)

        if data.login is not None and data.login != account.login:
            # Проверка уникальности нового логина
            dup = (
                await self.db.execute(
                    select(GameAccount).where(
                        GameAccount.org_id == org_id,
                        GameAccount.game == account.game,
                        GameAccount.login == data.login,
                        GameAccount.id != account_id,
                    )
                )
            ).scalar_one_or_none()
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail=f"Аккаунт '{data.login}' для игры '{account.game}' уже существует",
                )
            account.login = data.login

        if data.password is not None:
            account.password_encrypted = data.password

        if data.status is not None:
            new_status = AccountStatus(data.status)
            if new_status != account.status:
                account.status = new_status
                account.status_changed_at = datetime.now(timezone.utc)
                account.status_reason = data.status_reason

                # Если ставим free — снять привязку к устройству
                if new_status == AccountStatus.free:
                    account.device_id = None
                    account.assigned_at = None
                    account.cooldown_until = None

        if data.status_reason is not None and data.status is None:
            account.status_reason = data.status_reason

        if data.server_name is not None:
            account.server_name = data.server_name

        if data.nickname is not None:
            account.nickname = data.nickname

        if data.level is not None:
            account.level = data.level

        if data.target_level is not None:
            account.target_level = data.target_level

        if data.experience is not None:
            account.experience = data.experience

        if data.balance_rub is not None:
            account.balance_rub = data.balance_rub
            account.last_balance_update = datetime.now(timezone.utc)

        if data.balance_bc is not None:
            account.balance_bc = data.balance_bc
            account.last_balance_update = datetime.now(timezone.utc)

        if data.vip_type is not None:
            account.vip_type = VipType(data.vip_type)

        if data.vip_expires_at is not None:
            account.vip_expires_at = data.vip_expires_at

        if data.lawfulness is not None:
            account.lawfulness = data.lawfulness

        if data.meta is not None:
            account.meta = data.meta

        await self.db.flush()
        await self.db.refresh(account)
        return self._to_response(account)

    # ── Delete ───────────────────────────────────────────────────────────────

    async def delete_account(self, account_id: uuid.UUID, org_id: uuid.UUID) -> None:
        """Безвозвратное удаление аккаунта."""
        account = await self._get_account(account_id, org_id)
        await self.db.delete(account)
        await self.db.flush()

    # ── Assign / Release ─────────────────────────────────────────────────────

    async def assign_account(
        self,
        account_id: uuid.UUID,
        org_id: uuid.UUID,
        data: AssignAccountRequest,
    ) -> GameAccountResponse:
        """Назначить аккаунт на устройство."""
        account = await self._get_account(account_id, org_id)

        if account.status not in (AccountStatus.free,):
            raise HTTPException(
                status_code=409,
                detail=f"Нельзя назначить аккаунт в статусе '{account.status.value}'. Требуется статус 'free'.",
            )

        # Проверить, что устройство принадлежит той же организации
        from backend.models.device import Device
        device = (
            await self.db.execute(
                select(Device).where(
                    Device.id == data.device_id,
                    Device.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Устройство не найдено")

        now = datetime.now(timezone.utc)
        account.device_id = data.device_id
        account.assigned_at = now
        account.status = AccountStatus.in_use
        account.status_changed_at = now
        account.status_reason = f"Назначен на устройство {device.name}"

        await self.db.flush()
        # Полный refresh объекта после flush — иначе скалярные атрибуты expire (greenlet crash в async)
        await self.db.refresh(account)
        return self._to_response(account)

    async def release_account(
        self,
        account_id: uuid.UUID,
        org_id: uuid.UUID,
        data: ReleaseAccountRequest,
    ) -> GameAccountResponse:
        """Освободить аккаунт (снять с устройства). Опционально — кулдаун."""
        account = await self._get_account(account_id, org_id)

        if account.status != AccountStatus.in_use:
            raise HTTPException(
                status_code=409,
                detail=f"Аккаунт не используется (статус: '{account.status.value}')",
            )

        now = datetime.now(timezone.utc)
        account.total_sessions += 1
        account.last_session_end = now
        account.device_id = None
        account.assigned_at = None

        if data.cooldown_minutes and data.cooldown_minutes > 0:
            account.status = AccountStatus.cooldown
            account.cooldown_until = now + timedelta(minutes=data.cooldown_minutes)
            account.status_reason = f"Кулдаун {data.cooldown_minutes} мин."
        else:
            account.status = AccountStatus.free
            account.cooldown_until = None
            account.status_reason = None

        account.status_changed_at = now
        await self.db.flush()
        await self.db.refresh(account)
        return self._to_response(account)

    # ── Import ───────────────────────────────────────────────────────────────

    async def import_accounts(
        self, org_id: uuid.UUID, items: list[ImportAccountItem],
    ) -> ImportAccountsResponse:
        """Массовый импорт аккаунтов. Дубли (game+login) пропускаются."""
        created = 0
        skipped = 0
        errors: list[str] = []

        for idx, item in enumerate(items):
            try:
                # Проверка дубля
                dup = (
                    await self.db.execute(
                        select(GameAccount.id).where(
                            GameAccount.org_id == org_id,
                            GameAccount.game == item.game,
                            GameAccount.login == item.login,
                        )
                    )
                ).scalar_one_or_none()

                if dup:
                    skipped += 1
                    continue

                account = GameAccount(
                    org_id=org_id,
                    game=item.game,
                    login=item.login,
                    password_encrypted=item.password,
                    status=AccountStatus.free,
                    status_changed_at=datetime.now(timezone.utc),
                    server_name=item.server_name,
                    nickname=item.nickname,
                    level=item.level,
                    balance_rub=item.balance_rub,
                    balance_bc=item.balance_bc,
                    last_balance_update=datetime.now(timezone.utc) if item.balance_rub is not None else None,
                    meta=item.meta or {},
                )
                self.db.add(account)
                created += 1

            except Exception as e:
                errors.append(f"Строка {idx + 1}: {str(e)}")

        if created > 0:
            await self.db.flush()

        return ImportAccountsResponse(created=created, skipped=skipped, errors=errors)

    # ── Stats ────────────────────────────────────────────────────────────────

    async def get_stats(self, org_id: uuid.UUID) -> AccountStatsResponse:
        """Агрегированная статистика: количество по статусам + список уникальных игр."""
        # Количество по статусам
        stmt = (
            select(
                func.count().label("total"),
                func.count().filter(GameAccount.status == AccountStatus.free).label("free"),
                func.count().filter(GameAccount.status == AccountStatus.in_use).label("in_use"),
                func.count().filter(GameAccount.status == AccountStatus.cooldown).label("cooldown"),
                func.count().filter(GameAccount.status == AccountStatus.banned).label("banned"),
                func.count().filter(GameAccount.status == AccountStatus.captcha).label("captcha"),
                func.count().filter(GameAccount.status == AccountStatus.phone_verify).label("phone_verify"),
                func.count().filter(GameAccount.status == AccountStatus.disabled).label("disabled"),
                func.count().filter(GameAccount.status == AccountStatus.archived).label("archived"),
                func.count().filter(GameAccount.status == AccountStatus.pending_registration).label("pending_registration"),
                func.count().filter(
                    GameAccount.target_level.isnot(None),
                    GameAccount.level >= GameAccount.target_level,
                ).label("leveled"),
            )
            .select_from(GameAccount)
            .where(GameAccount.org_id == org_id)
        )
        row = (await self.db.execute(stmt)).one()

        # Уникальные игры
        games_stmt = (
            select(distinct(GameAccount.game))
            .where(GameAccount.org_id == org_id)
            .order_by(GameAccount.game)
        )
        games = (await self.db.execute(games_stmt)).scalars().all()

        # Уникальные серверы
        servers_stmt = (
            select(distinct(GameAccount.server_name))
            .where(
                GameAccount.org_id == org_id,
                GameAccount.server_name.isnot(None),
            )
            .order_by(GameAccount.server_name)
        )
        servers = (await self.db.execute(servers_stmt)).scalars().all()

        return AccountStatsResponse(
            total=row.total,
            free=row.free,
            in_use=row.in_use,
            cooldown=row.cooldown,
            banned=row.banned,
            captcha=row.captcha,
            phone_verify=row.phone_verify,
            disabled=row.disabled,
            archived=row.archived,
            pending_registration=row.pending_registration,
            leveled=row.leveled,
            games=list(games),
            servers=[s for s in servers if s is not None],
        )
