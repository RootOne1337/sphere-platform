# backend/services/account_session_service.py
# ВЛАДЕЛЕЦ: TZ-11 Account Sessions — сервис истории использования аккаунтов.
# Отвечает за: создание/завершение сессий, аналитику, фильтрацию.
# НЕ делает commit() — это ответственность вызывающего (router или pipeline).
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account_session import AccountSession, SessionEndReason
from backend.models.game_account import GameAccount
from backend.schemas.account_sessions import (
    AccountSessionResponse,
    EndSessionRequest,
    SessionStatsResponse,
    StartSessionRequest,
)

logger = structlog.get_logger()


class AccountSessionService:
    """Сервис управления сессиями аккаунтов."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Helpers ──────────────────────────────────────────────────────────

    def _to_response(self, session: AccountSession) -> AccountSessionResponse:
        """ORM → Pydantic response."""
        account_login = None
        account_game = None
        if session.account:
            account_login = session.account.login
            account_game = session.account.game
        device_name = None
        if session.device:
            device_name = session.device.name

        # Вычислить длительность, если сессия завершена
        duration_seconds = None
        if session.ended_at and session.started_at:
            duration_seconds = int((session.ended_at - session.started_at).total_seconds())

        return AccountSessionResponse(
            id=session.id,
            org_id=session.org_id,
            account_id=session.account_id,
            account_login=account_login,
            account_game=account_game,
            device_id=session.device_id,
            device_name=device_name,
            started_at=session.started_at,
            ended_at=session.ended_at,
            end_reason=(
                session.end_reason.value
                if isinstance(session.end_reason, SessionEndReason)
                else session.end_reason
            ),
            error_message=session.error_message,
            script_id=session.script_id,
            task_id=session.task_id,
            pipeline_run_id=session.pipeline_run_id,
            nodes_executed=session.nodes_executed,
            errors_count=session.errors_count,
            level_before=session.level_before,
            level_after=session.level_after,
            balance_before=session.balance_before,
            balance_after=session.balance_after,
            duration_seconds=duration_seconds,
            meta=session.meta,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    # ── Создание / завершение ────────────────────────────────────────────

    async def start_session(
        self,
        org_id: uuid.UUID,
        data: StartSessionRequest,
    ) -> AccountSessionResponse:
        """Начать новую сессию аккаунта на устройстве."""
        # Получить текущие значения level/balance для фиксации before-снимка
        account = await self.db.get(GameAccount, data.account_id)
        level_before = account.level if account else None
        balance_before = account.balance_rub if account else None

        session = AccountSession(
            org_id=org_id,
            account_id=data.account_id,
            device_id=data.device_id,
            started_at=datetime.now(timezone.utc),
            script_id=data.script_id,
            task_id=data.task_id,
            pipeline_run_id=data.pipeline_run_id,
            level_before=level_before,
            balance_before=balance_before,
            meta=data.meta or {},
        )
        self.db.add(session)
        await self.db.flush()

        logger.info(
            "account_session.started",
            session_id=str(session.id),
            account_id=str(data.account_id),
            device_id=str(data.device_id),
        )
        return self._to_response(session)

    async def start_session_internal(
        self,
        org_id: uuid.UUID,
        account_id: uuid.UUID,
        device_id: uuid.UUID,
        script_id: uuid.UUID | None = None,
        pipeline_run_id: uuid.UUID | None = None,
    ) -> AccountSession:
        """Начать сессию из внутреннего кода. Возвращает ORM-объект."""
        account = await self.db.get(GameAccount, account_id)
        session = AccountSession(
            org_id=org_id,
            account_id=account_id,
            device_id=device_id,
            started_at=datetime.now(timezone.utc),
            script_id=script_id,
            pipeline_run_id=pipeline_run_id,
            level_before=account.level if account else None,
            balance_before=account.balance_rub if account else None,
            meta={},
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def end_session(
        self,
        session_id: uuid.UUID,
        org_id: uuid.UUID,
        data: EndSessionRequest,
    ) -> AccountSessionResponse:
        """Завершить сессию с указанием причины и метрик."""
        from fastapi import HTTPException

        stmt = select(AccountSession).where(
            AccountSession.id == session_id,
            AccountSession.org_id == org_id,
            AccountSession.ended_at.is_(None),
        )
        session = (await self.db.execute(stmt)).scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Активная сессия не найдена")

        session.ended_at = datetime.now(timezone.utc)
        session.end_reason = SessionEndReason(data.end_reason)
        session.error_message = data.error_message
        session.nodes_executed = data.nodes_executed
        session.errors_count = data.errors_count
        session.level_after = data.level_after
        session.balance_after = data.balance_after
        if data.meta:
            session.meta = {**session.meta, **data.meta}

        await self.db.flush()

        duration = 0
        _ended = session.ended_at
        _started = session.started_at
        if _ended is not None and _started is not None:
            duration = int((_ended - _started).total_seconds())
        logger.info(
            "account_session.ended",
            session_id=str(session.id),
            end_reason=data.end_reason,
            duration_seconds=duration,
        )
        return self._to_response(session)

    async def end_session_internal(
        self,
        session_id: uuid.UUID,
        end_reason: str,
        error_message: str | None = None,
        nodes_executed: int = 0,
        errors_count: int = 0,
    ) -> None:
        """Завершить сессию из внутреннего кода (EventReactor, pipeline)."""
        session = await self.db.get(AccountSession, session_id)
        if not session or session.ended_at is not None:
            return
        session.ended_at = datetime.now(timezone.utc)
        session.end_reason = SessionEndReason(end_reason)
        session.error_message = error_message
        session.nodes_executed = nodes_executed
        session.errors_count = errors_count

        # Обновить level_after / balance_after из текущего состояния аккаунта
        account = await self.db.get(GameAccount, session.account_id)
        if account:
            session.level_after = account.level
            session.balance_after = account.balance_rub

        await self.db.flush()

    async def get_active_session(
        self,
        account_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> AccountSession | None:
        """Получить активную (незавершённую) сессию аккаунта."""
        stmt = select(AccountSession).where(
            AccountSession.account_id == account_id,
            AccountSession.org_id == org_id,
            AccountSession.ended_at.is_(None),
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    # ── Чтение ───────────────────────────────────────────────────────────

    async def get_session(
        self,
        session_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> AccountSessionResponse:
        """Получить одну сессию по ID."""
        from fastapi import HTTPException

        stmt = select(AccountSession).where(
            AccountSession.id == session_id,
            AccountSession.org_id == org_id,
        )
        session = (await self.db.execute(stmt)).scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        return self._to_response(session)

    async def list_sessions(
        self,
        org_id: uuid.UUID,
        account_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        end_reason: str | None = None,
        active_only: bool = False,
        sort_by: str = "started_at",
        sort_dir: str = "desc",
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[AccountSessionResponse], int]:
        """Пагинированный список сессий с фильтрами."""
        conditions = [AccountSession.org_id == org_id]

        if account_id:
            conditions.append(AccountSession.account_id == account_id)
        if device_id:
            conditions.append(AccountSession.device_id == device_id)
        if end_reason:
            try:
                conditions.append(AccountSession.end_reason == SessionEndReason(end_reason))
            except ValueError:
                pass
        if active_only:
            conditions.append(AccountSession.ended_at.is_(None))

        # Сортировка (белый список)
        sort_columns = {
            "started_at": AccountSession.started_at,
            "ended_at": AccountSession.ended_at,
            "created_at": AccountSession.created_at,
        }
        sort_col = sort_columns.get(sort_by, AccountSession.started_at)
        order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

        # Count
        count_stmt = select(func.count()).select_from(AccountSession).where(*conditions)
        total = (await self.db.execute(count_stmt)).scalar_one()

        # Data
        stmt = (
            select(AccountSession)
            .where(*conditions)
            .order_by(order)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await self.db.execute(stmt)).scalars().all()

        return [self._to_response(s) for s in rows], total

    # ── Статистика ───────────────────────────────────────────────────────

    async def get_stats(
        self,
        org_id: uuid.UUID,
        account_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
    ) -> SessionStatsResponse:
        """Агрегированная статистика сессий."""
        conditions = [AccountSession.org_id == org_id]
        if account_id:
            conditions.append(AccountSession.account_id == account_id)
        if device_id:
            conditions.append(AccountSession.device_id == device_id)

        # Общее количество
        total = (await self.db.execute(
            select(func.count()).select_from(AccountSession).where(*conditions)
        )).scalar_one()

        # Активные
        active = (await self.db.execute(
            select(func.count()).select_from(AccountSession).where(
                *conditions, AccountSession.ended_at.is_(None),
            )
        )).scalar_one()

        # Средняя длительность завершённых сессий
        avg_duration = (await self.db.execute(
            select(
                func.avg(
                    func.extract("epoch", AccountSession.ended_at - AccountSession.started_at)
                )
            ).select_from(AccountSession).where(
                *conditions, AccountSession.ended_at.isnot(None),
            )
        )).scalar_one()

        # По причинам завершения
        reason_rows = (await self.db.execute(
            select(AccountSession.end_reason, func.count())
            .where(*conditions, AccountSession.end_reason.isnot(None))
            .group_by(AccountSession.end_reason)
        )).all()
        by_end_reason = {
            (row[0].value if isinstance(row[0], SessionEndReason) else str(row[0])): row[1]
            for row in reason_rows
        }

        # Суммарные метрики
        totals = (await self.db.execute(
            select(
                func.coalesce(func.sum(AccountSession.nodes_executed), 0),
                func.coalesce(func.sum(AccountSession.errors_count), 0),
            ).select_from(AccountSession).where(*conditions)
        )).one()

        return SessionStatsResponse(
            total_sessions=total,
            active_sessions=active,
            avg_duration_seconds=round(avg_duration, 1) if avg_duration else None,
            by_end_reason=by_end_reason,
            total_nodes_executed=totals[0],
            total_errors=totals[1],
        )
