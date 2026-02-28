# backend/models/pipeline.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. Модели оркестратора: Pipeline (шаблон) + PipelineRun (инстанс).
# Pipeline — переиспользуемый граф шагов (аналог Docker Image).
# PipelineRun — конкретный запуск на устройстве (аналог Docker Container).
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class PipelineRunStatus(str, enum.Enum):
    """Статусы исполнения pipeline run."""
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"       # Ожидание события / завершения скрипта
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class StepType(str, enum.Enum):
    """Типы шагов pipeline."""
    EXECUTE_SCRIPT = "execute_script"
    CONDITION = "condition"
    ACTION = "action"
    WAIT_FOR_EVENT = "wait_for_event"
    PARALLEL = "parallel"
    DELAY = "delay"
    N8N_WORKFLOW = "n8n_workflow"
    LOOP = "loop"
    SUB_PIPELINE = "sub_pipeline"


# ── Pipeline — шаблон оркестрации ────────────────────────────────────────────


class Pipeline(Base, UUIDMixin, TimestampMixin):
    """
    Шаблон оркестрации — граф шагов для исполнения.

    Pipeline — это переиспользуемый шаблон. Для запуска создаётся PipelineRun.
    Шаги хранятся как JSONB массив PipelineStep (валидируются через Pydantic).
    """
    __tablename__ = "pipelines"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Граф шагов — JSONB массив PipelineStep (валидация на уровне Pydantic)
    steps: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]",
        comment="Массив PipelineStep: [{id, name, type, params, on_success, on_failure, ...}]",
    )

    # JSON Schema входных параметров pipeline (для UI и валидации)
    input_schema: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False,
        comment="JSON Schema входных параметров: game_id, credentials, etc.",
    )

    # Глобальные настройки
    global_timeout_ms: Mapped[int] = mapped_column(
        Integer, default=86_400_000, nullable=False,
        comment="Максимальное время исполнения (мс), дефолт 24 часа",
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Глобальный ретрай всего pipeline (0 = без ретрая)",
    )

    # Версионирование
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Теги для фильтрации и группировки
    tags: Mapped[list[str]] = mapped_column(
        JSONB, server_default="[]", nullable=False,
    )

    # Кто создал
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True,
    )

    # Связи
    runs: Mapped[list["PipelineRun"]] = relationship(back_populates="pipeline")

    __table_args__ = (
        Index("ix_pipelines_org_active", "org_id", "is_active"),
    )


# ── PipelineRun — запущенный инстанс ────────────────────────────────────────


class PipelineRun(Base, UUIDMixin, TimestampMixin):
    """
    Запущенный инстанс Pipeline на конкретном устройстве.

    Хранит:
    - Текущий шаг (current_step_id) для возобновления после рестарта
    - Иммутабельный снимок шагов (steps_snapshot) — не зависит от изменений шаблона
    - Мутабельный контекст (context) — переменные, результаты, аккаунт
    - Полный лог шагов с таймингами (step_logs)
    """
    __tablename__ = "pipeline_runs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True,
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id"), nullable=False, index=True,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            PipelineRunStatus,
            name="pipeline_run_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=PipelineRunStatus.QUEUED,
        nullable=False,
        index=True,
    )

    # Текущая позиция исполнения (для resume после рестарта бэкенда)
    current_step_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="ID текущего шага в steps_snapshot",
    )

    # Мутабельный контекст исполнения (аккаунт, логин, результаты скриптов)
    context: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False,
        comment="Мутабельный контекст: переменные, результаты, аккаунт",
    )

    # Входные параметры (копия на момент запуска)
    input_params: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False,
    )

    # Иммутабельный снимок pipeline.steps на момент запуска
    steps_snapshot: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]",
        comment="Копия pipeline.steps — не меняется при обновлении шаблона",
    )

    # Лог шагов: [{step_id, type, status, started_at, finished_at, duration_ms, output, error}]
    step_logs: Mapped[list[dict]] = mapped_column(
        JSONB, server_default="[]", nullable=False,
    )

    # Связь с текущим task (только если шаг execute_script в процессе)
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id"), nullable=True,
    )

    # Тайминги
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Retry
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Связи
    pipeline: Mapped["Pipeline"] = relationship(back_populates="runs")
    device: Mapped["Device"] = relationship()

    __table_args__ = (
        Index("ix_pipeline_runs_device_status", "device_id", "status"),
        Index("ix_pipeline_runs_org_status", "org_id", "status"),
    )


# ── PipelineBatch — массовый запуск ──────────────────────────────────────────


class PipelineBatch(Base, UUIDMixin, TimestampMixin):
    """
    Массовый запуск одного Pipeline на N устройств.

    Аналог TaskBatch, но для pipeline-ов.
    Используется при запуске pipeline на группу/теги устройств.
    """
    __tablename__ = "pipeline_batches"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True,
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), default="running", nullable=False, index=True,
    )
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wave_config: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True,
    )
