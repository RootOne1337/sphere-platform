# backend/models/account_session.py
# ВЛАДЕЛЕЦ: TZ-11 Account Sessions — история использования игровых аккаунтов.
# Каждая привязка аккаунт↔устройство фиксируется как сессия
# для аналитики (средний lifetime, успешность, причины завершения).
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class SessionEndReason(str, enum.Enum):
    """Причина завершения сессии аккаунта."""

    completed = "completed"           # Нормальное завершение (фарм закончен)
    banned = "banned"                 # Аккаунт забанен в игре
    captcha = "captcha"               # Капча не решена / таймаут
    error = "error"                   # Ошибка скрипта / устройства
    manual = "manual"                 # Ручной release оператором
    rotation = "rotation"             # Автоматическая ротация
    timeout = "timeout"               # Превышено время сессии
    device_offline = "device_offline"  # Устройство ушло в оффлайн


class AccountSession(Base, UUIDMixin, TimestampMixin):
    """
    Сессия использования игрового аккаунта на устройстве.

    Фиксирует период: assign → release/бан/ошибка.
    Содержит метрики: количество выполненных нод, ошибки, прогресс.
    Все сессии изолированы по org_id (Row Level Security).
    """

    __tablename__ = "account_sessions"

    # --- Организационная принадлежность ---
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Привязки ---
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Игровой аккаунт",
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Устройство, на котором использовался аккаунт",
    )

    # --- Время жизни сессии ---
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="Время начала сессии (assign)",
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Время окончания сессии (release/бан/ошибка). NULL = активная сессия",
    )

    # --- Результат ---
    end_reason: Mapped[SessionEndReason | None] = mapped_column(
        Enum(
            SessionEndReason,
            name="session_end_reason",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
        comment="Причина завершения сессии",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Описание ошибки при неудачном завершении",
    )

    # --- Связь со скриптом / задачей ---
    script_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scripts.id", ondelete="SET NULL"),
        nullable=True,
        comment="Скрипт, запущенный в рамках сессии",
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        comment="Последняя задача сессии",
    )
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"),
        nullable=True,
        comment="Pipeline run, в рамках которого проходила сессия",
    )

    # --- Метрики ---
    nodes_executed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Количество выполненных нод DAG за сессию",
    )
    errors_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Количество ошибок за сессию",
    )

    # --- Игровой прогресс за сессию ---
    level_before: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Уровень аккаунта на начало сессии",
    )
    level_after: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Уровень аккаунта на конец сессии",
    )
    balance_before: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="Баланс на начало сессии",
    )
    balance_after: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="Баланс на конец сессии",
    )

    # --- Мета-данные ---
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
        comment="Произвольные данные: логи, скриншоты, дополнительная телеметрия",
    )

    # --- Relationships ---
    account = relationship("GameAccount", foreign_keys=[account_id], lazy="selectin")
    device = relationship("Device", foreign_keys=[device_id], lazy="selectin")

    # --- Индексы ---
    __table_args__ = (
        # История сессий аккаунта (хронологическая)
        Index(
            "ix_account_sessions_account_started",
            "account_id", "started_at",
        ),
        # Активные сессии (ended_at IS NULL)
        Index(
            "ix_account_sessions_active",
            "org_id", "ended_at",
            postgresql_where="ended_at IS NULL",
        ),
        # Фильтрация по устройству
        Index(
            "ix_account_sessions_device_started",
            "device_id", "started_at",
        ),
        # Аналитика по причинам завершения
        Index(
            "ix_account_sessions_org_reason",
            "org_id", "end_reason",
        ),
    )

    def __repr__(self) -> str:
        status = "active" if self.ended_at is None else self.end_reason
        return f"<AccountSession account={self.account_id} device={self.device_id} [{status}]>"
