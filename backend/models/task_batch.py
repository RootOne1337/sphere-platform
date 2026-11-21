# backend/models/task_batch.py
# TZ-04 Script Engine SPLIT-4 Wave / Batch владеет — stub здесь
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class TaskBatchStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskBatch(Base, UUIDMixin, TimestampMixin):
    """
    Пакетный запуск скрипта на множестве устройств (wave/batch).
    Детальная логика: TZ-04 SPLIT-4.
    """
    __tablename__ = "task_batches"
    __table_args__ = (Index("ix_task_batches_admission", "admission_state", "next_wave_at"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(TaskBatchStatus, name="task_batch_status_enum", values_callable=lambda obj: [e.value for e in obj]),
        default=TaskBatchStatus.PENDING,
        nullable=False,
        index=True,
    )
    # волновая конфигурация (concurrency, delay, wave_size)
    wave_config: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    # NULL plan identifies old batches; their missing targets cannot be inferred.
    wave_plan: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("script_versions.id"), nullable=True)
    next_wave_index: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    next_wave_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admission_state: Mapped[str] = mapped_column(String(24), server_default="legacy_unknown", nullable=False)
    admission_receipts: Mapped[list] = mapped_column(JSONB, server_default="[]", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tasks: Mapped[list["Task"]] = relationship(back_populates="batch")
