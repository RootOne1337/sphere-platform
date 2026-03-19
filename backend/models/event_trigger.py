# backend/models/event_trigger.py
# ВЛАДЕЛЕЦ: TZ-11+ Event Triggers — автоматический запуск pipeline по событиям.
#
# EventTrigger определяет правило: «когда событие X происходит → запустить pipeline Y».
# Это GENERIC механизм — работает для любых игр, любых типов событий.
# Примеры:
#   - event_type_pattern="account.banned"  → pipeline "Ротация и перерегистрация"
#   - event_type_pattern="game.crashed"    → pipeline "Перезапуск игры"
#   - event_type_pattern="task.failed"     → pipeline "Нотификация и retry"
#
# Паттерн event_type_pattern поддерживает простой glob:
#   - "account.banned"  → точное совпадение
#   - "account.*"       → все события аккаунтов
#   - "*"               → все события (осторожно!)
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
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


class EventTrigger(Base, UUIDMixin, TimestampMixin):
    """
    Правило автоматического запуска pipeline по событию.

    Когда EventReactor обрабатывает событие, он проверяет все активные
    EventTrigger'ы с совпадающим event_type_pattern и запускает
    соответствующий pipeline.

    Поля:
    - event_type_pattern: glob-паттерн для event_type (account.banned, account.*, *)
    - pipeline_id: какой pipeline запустить
    - input_params_template: шаблон параметров для pipeline run (JSONB)
    - is_active: вкл/выкл (сохраняется в БД, переживает рестарты)
    - cooldown_seconds: минимальный интервал между срабатываниями (анти-спам)
    - max_triggers_per_hour: лимит срабатываний в час
    - last_triggered_at: когда последний раз сработал
    - total_triggers: общее число срабатываний (статистика)
    """

    __tablename__ = "event_triggers"

    # --- Организационная принадлежность ---
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Идентификация ---
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Человекочитаемое имя триггера",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Описание что делает триггер и зачем",
    )

    # --- Паттерн события ---
    event_type_pattern: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
        comment="Glob-паттерн для event_type: account.banned, account.*, task.failed итд",
    )

    # --- Целевой pipeline ---
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Pipeline который запустить при срабатывании",
    )

    # --- Шаблон параметров ---
    input_params_template: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
        comment="Шаблон input_params для pipeline run. Поддерживает плейсхолдеры: "
                "{device_id}, {account_id}, {event_type}, {event_data}",
    )

    # --- Управление ---
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        index=True,
        comment="Включён/выключен. Сохраняется в БД, переживает рестарт сервера",
    )

    # --- Анти-спам ---
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60",
        comment="Минимальный интервал между срабатываниями (секунды)",
    )
    max_triggers_per_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100",
        comment="Максимум срабатываний в час (0 = без лимита)",
    )

    # --- Статистика ---
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Когда последний раз сработал триггер",
    )
    total_triggers: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Общее количество срабатываний",
    )

    # --- Relationships ---
    pipeline = relationship("Pipeline", foreign_keys=[pipeline_id], lazy="selectin")

    # --- Индексы ---
    __table_args__ = (
        # Быстрый поиск активных триггеров по организации
        Index(
            "ix_event_triggers_org_active",
            "org_id", "is_active",
            postgresql_where="is_active = true",
        ),
        # Поиск по паттерну
        Index(
            "ix_event_triggers_pattern",
            "event_type_pattern",
        ),
    )

    def __repr__(self) -> str:
        return f"<EventTrigger {self.name!r} [{self.event_type_pattern}] → pipeline={self.pipeline_id}>"
