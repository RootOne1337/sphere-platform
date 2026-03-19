# backend/models/pipeline_settings.py
# ВЛАДЕЛЕЦ: TZ-13 Orchestration Pipeline.
# Персистентные настройки оркестрации и планировщика задач.
# Выживают после перезагрузки сервера — хранятся в PostgreSQL.
# Одна запись на организацию (singleton per org).
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class PipelineSettings(Base, UUIDMixin, TimestampMixin):
    """
    Персистентные настройки оркестрационного пайплайна.

    Singleton на организацию: одна запись per org_id.
    Используется OrchestrationEngine и SchedulerEngine для определения,
    нужно ли запускать автоматические процессы (регистрация, фарм, уровни).
    Все настройки сохраняются в БД и выживают после рестарта сервера.
    """

    __tablename__ = "pipeline_settings"

    # --- Привязка к организации (singleton per org) ---
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="Организация (одна запись на org)",
    )

    # ── Главные переключатели ──────────────────────────────────────────────

    orchestration_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="Глобальный переключатель оркестрации (регистрация, фарм, мониторинг)",
    )
    scheduler_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="Глобальный переключатель планировщика задач (cron/interval расписания)",
    )

    # ── Настройки регистрации ──────────────────────────────────────────────

    registration_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="Автоматическая регистрация новых аккаунтов",
    )
    max_concurrent_registrations: Mapped[int] = mapped_column(
        Integer, default=3, server_default="3", nullable=False,
        comment="Максимум одновременных регистраций",
    )
    registration_script_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scripts.id", ondelete="SET NULL"),
        nullable=True,
        comment="ID скрипта регистрации (DAG)",
    )
    registration_timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=600, server_default="600", nullable=False,
        comment="Таймаут одной регистрации (секунды)",
    )

    # ── Настройки фарма ───────────────────────────────────────────────────

    farming_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="Автоматический фарм (прокачка уровня)",
    )
    max_concurrent_farming: Mapped[int] = mapped_column(
        Integer, default=10, server_default="10", nullable=False,
        comment="Максимум одновременных фарм-сессий",
    )
    farming_script_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scripts.id", ondelete="SET NULL"),
        nullable=True,
        comment="ID скрипта фарма (DAG)",
    )
    farming_session_duration_seconds: Mapped[int] = mapped_column(
        Integer, default=3600, server_default="3600", nullable=False,
        comment="Длительность одной фарм-сессии (секунды)",
    )

    # ── Уровни и цели ────────────────────────────────────────────────────

    default_target_level: Mapped[int] = mapped_column(
        Integer, default=3, server_default="3", nullable=False,
        comment="Целевой уровень по умолчанию для новых аккаунтов",
    )
    cooldown_between_sessions_minutes: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30", nullable=False,
        comment="Пауза между фарм-сессиями одного аккаунта (минуты)",
    )

    # ── Генерация ников ──────────────────────────────────────────────────

    nick_generation_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False,
        comment="Автоматическая генерация никнеймов (Имя_Фамилия)",
    )
    nick_pattern: Mapped[str] = mapped_column(
        String(100), default="{first_name}_{last_name}", server_default="{first_name}_{last_name}",
        nullable=False,
        comment="Шаблон генерации никнейма: {first_name}_{last_name}, {first_name}{digits} и т.д.",
    )

    # ── Мониторинг и оповещения ──────────────────────────────────────────

    ban_detection_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False,
        comment="Автоматическое обнаружение банов",
    )
    auto_replace_banned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="Автоматически заменять забаненные аккаунты новыми",
    )

    # ── Метаданные ───────────────────────────────────────────────────────

    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Заметки администратора",
    )
    meta: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False,
        comment="Произвольные метаданные (расширяемость)",
    )

    # --- Связи ---
    org: Mapped["Organization"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<PipelineSettings org={self.org_id} "
            f"orch={self.orchestration_enabled} sched={self.scheduler_enabled}>"
        )
