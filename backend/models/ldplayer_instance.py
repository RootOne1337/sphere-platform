# backend/models/ldplayer_instance.py
# TZ-08 PC-Agent SPLIT-2 владеет — stub для Alembic + RLS
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class LDPlayerInstance(Base, UUIDMixin, TimestampMixin):
    """
    Инстанс LDPlayer, запущенный на Workstation.
    Детальная логика: TZ-08 SPLIT-2.
    """
    __tablename__ = "ldplayer_instances"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workstation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workstations.id"), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    instance_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based LDPlayer index
    android_serial: Mapped[str | None] = mapped_column(String(100), nullable=True)  # ADB serial
    status: Mapped[str] = mapped_column(String(50), default="stopped", nullable=False)  # running|stopped|error
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)

    workstation: Mapped["Workstation"] = relationship(back_populates="ldplayer_instances")
    device: Mapped["Device | None"] = relationship(back_populates="ldplayer_instance")
