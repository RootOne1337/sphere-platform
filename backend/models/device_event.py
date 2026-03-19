# backend/models/device_event.py
# ВЛАДЕЛЕЦ: TZ-11 Device Events — персистентное хранилище событий от агентов.
# Каждое событие (бан, капча, ошибка, онлайн/оффлайн) сохраняется
# для аналитики, аудита и EventReactor автореакций.
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class EventSeverity(str, enum.Enum):
    """Уровень серьёзности события."""

    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class DeviceEvent(Base, UUIDMixin, TimestampMixin):
    """
    Персистентное событие от устройства.

    Хранит тип события, уровень серьёзности, привязку к устройству,
    аккаунту, задаче и произвольные данные (JSONB).
    Используется EventReactor для автоматических реакций
    и Dashboard для аналитики/мониторинга.
    Все события изолированы по org_id (Row Level Security).
    """

    __tablename__ = "device_events"

    # --- Организационная принадлежность ---
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Привязка к устройству ---
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Тип и серьёзность ---
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Тип события: account.banned, account.captcha, game.crashed, device.error итд",
    )
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(
            EventSeverity,
            name="event_severity",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=EventSeverity.info,
        server_default="info",
        index=True,
    )

    # --- Описание ---
    message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Человекочитаемое описание события",
    )

    # --- Связи с аккаунтом и задачей (опциональные) ---
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("game_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Игровой аккаунт, связанный с событием",
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Задача, при выполнении которой произошло событие",
    )
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Pipeline run, при выполнении которого произошло событие",
    )

    # --- Данные события ---
    data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
        comment="Произвольные данные события: скриншот, xpath, error trace итд",
    )

    # --- Время события (может отличаться от created_at) ---
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Когда событие произошло на устройстве (не путать с created_at — временем записи в БД)",
    )

    # --- Флаг обработки ---
    processed: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False,
        comment="Обработано ли EventReactor'ом",
    )

    # --- Relationships ---
    device = relationship("Device", foreign_keys=[device_id], lazy="selectin")
    account = relationship("GameAccount", foreign_keys=[account_id], lazy="selectin")

    # --- Индексы ---
    __table_args__ = (
        # Быстрый поиск необработанных событий (для EventReactor)
        Index(
            "ix_device_events_unprocessed",
            "org_id", "processed",
            postgresql_where="processed = false",
        ),
        # Хронологический поиск по устройству
        Index(
            "ix_device_events_device_occurred",
            "device_id", "occurred_at",
        ),
        # Поиск по типу события по организации
        Index(
            "ix_device_events_org_type",
            "org_id", "event_type", "occurred_at",
        ),
        # Поиск по аккаунту (история событий аккаунта)
        Index(
            "ix_device_events_account",
            "account_id",
            postgresql_where="account_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<DeviceEvent {self.event_type} [{self.severity.value}] device={self.device_id}>"
