# backend/models/task.py
# TZ-04 Script Engine SPLIT-3 Task Queue владеет детальной логикой
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Task(Base, UUIDMixin, TimestampMixin):
    """
    Запуск скрипта на конкретном устройстве.
    Поддерживает 7 статусов жизненного цикла.
    Детальная логика: TZ-04 SPLIT-3.
    """
    __tablename__ = "tasks"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), index=True)
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"), index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_batches.id"), nullable=True, index=True)
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("script_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(TaskStatus, name="task_status_enum"),
        default=TaskStatus.QUEUED,
        nullable=False,
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    input_params: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    wave_index: Mapped[int | None] = mapped_column(Integer, nullable=True)  # TZ-04 SPLIT-4 wave position

    device: Mapped["Device"] = relationship()
    script: Mapped["Script"] = relationship(back_populates="tasks")
    batch: Mapped["TaskBatch | None"] = relationship(back_populates="tasks")
