# backend/models/schedule.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-5. Модели системы расписаний.
# Schedule — шаблон расписания (cron / interval / one_shot).
# ScheduleExecution — лог срабатывания расписания.
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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

# ── Перечисления ──────────────────────────────────────────────────────────────


class ScheduleConflictPolicy(str, enum.Enum):
    """Политика при конфликте: предыдущий запуск ещё не завершён."""
    SKIP = "skip"              # Пропустить текущий тик
    QUEUE = "queue"            # Поставить в очередь (запустить всё равно)
    CANCEL_PREVIOUS = "cancel" # Отменить предыдущий, запустить новый


class ScheduleTargetType(str, enum.Enum):
    """Тип цели расписания."""
    SCRIPT = "script"          # Запуск одного скрипта
    PIPELINE = "pipeline"      # Запуск pipeline (TZ-12 SPLIT-4)


class ScheduleExecutionStatus(str, enum.Enum):
    """Статусы срабатывания расписания."""
    TRIGGERED = "triggered"    # Расписание сработало, запуск создан
    SKIPPED = "skipped"        # Пропущено (конфликт / устройства offline)
    COMPLETED = "completed"    # Все запущенные задачи завершены
    PARTIAL = "partial"        # Часть задач succeed, часть fail
    FAILED = "failed"          # Все задачи провалились


# ── Schedule — шаблон расписания ─────────────────────────────────────────────


class Schedule(Base, UUIDMixin, TimestampMixin):
    """
    Расписание запуска скрипта или pipeline.

    Поддерживает три режима:
    - cron_expression: стандартный cron (5 полей) — '5,25,45 * * * *'
    - interval_seconds: интервал в секундах (≥60)
    - one_shot_at: однократный запуск в заданное время

    Таргетирование:
    - device_ids: конкретные устройства
    - group_id: все устройства из группы
    - device_tags: все устройства с указанными тегами
    """
    __tablename__ = "schedules"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Триггеры (взаимоисключающие — CHECK constraint ниже)
    cron_expression: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="Cron (5 полей): '5,25,45 * * * *' = 5/25/45 мин каждого часа",
    )
    interval_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Интервал в секундах (≥60, альтернатива cron)",
    )
    one_shot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Однократный запуск в указанное время",
    )

    # Таймзона для cron-выражений (IANA формат: Europe/Moscow)
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", nullable=False,
        comment="Таймзона для cron (IANA: Europe/Moscow, America/New_York)",
    )

    # Цель запуска
    target_type: Mapped[str] = mapped_column(
        Enum(
            ScheduleTargetType,
            name="schedule_target_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    script_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scripts.id"), nullable=True,
    )
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipelines.id"), nullable=True,
    )

    # Входные параметры для скрипта / pipeline
    input_params: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False,
    )

    # Таргетирование устройств
    device_ids: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True,
        comment="Список UUID конкретных устройств",
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("device_groups.id"), nullable=True,
    )
    device_tags: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True,
        comment="Теги устройств — запуск на всех с этими тегами",
    )
    only_online: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="Запускать только на online устройствах",
    )

    # Конфликтная политика
    conflict_policy: Mapped[str] = mapped_column(
        Enum(
            ScheduleConflictPolicy,
            name="schedule_conflict_policy_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=ScheduleConflictPolicy.SKIP,
        nullable=False,
    )

    # Состояние
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True,
    )

    # Окно активности (опциональное)
    active_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    active_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Лимиты
    max_runs: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Макс. кол-во запусков (null = безлимит)",
    )
    total_runs: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )

    # Расчётное время следующего срабатывания (index для быстрого SELECT)
    next_fire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
        comment="Рассчитанное время следующего срабатывания (UTC)",
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Кто создал
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True,
    )

    # Связи
    executions: Mapped[list["ScheduleExecution"]] = relationship(back_populates="schedule")

    __table_args__ = (
        Index("ix_schedules_next_fire", "is_active", "next_fire_at"),
        Index("ix_schedules_org_active", "org_id", "is_active"),
        CheckConstraint(
            "("
            "  (CASE WHEN cron_expression IS NOT NULL THEN 1 ELSE 0 END) + "
            "  (CASE WHEN interval_seconds IS NOT NULL THEN 1 ELSE 0 END) + "
            "  (CASE WHEN one_shot_at IS NOT NULL THEN 1 ELSE 0 END)"
            ") = 1",
            name="ck_schedules_has_trigger",
        ),
    )


# ── ScheduleExecution — лог срабатывания ─────────────────────────────────────


class ScheduleExecution(Base, UUIDMixin, TimestampMixin):
    """
    Запись об одном срабатывании расписания.

    Хранит результат: сколько устройств затронуто,
    сколько задач создано, общий статус.
    """
    __tablename__ = "schedule_executions"

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            ScheduleExecutionStatus,
            name="schedule_execution_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=ScheduleExecutionStatus.TRIGGERED,
        nullable=False,
    )

    # Время срабатывания
    fire_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="Плановое время срабатывания",
    )
    actual_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="Фактическое время срабатывания",
    )

    # Статистика
    devices_targeted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ID пачки задач или pipeline runs
    batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    pipeline_batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Причина пропуска (если status = SKIPPED)
    skip_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Когда завершилось
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Связи
    schedule: Mapped["Schedule"] = relationship(back_populates="executions")

    __table_args__ = (
        Index("ix_schedule_executions_schedule_fire", "schedule_id", "fire_time"),
    )
