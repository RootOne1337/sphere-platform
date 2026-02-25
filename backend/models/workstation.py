# backend/models/workstation.py
# TZ-08 PC-Agent SPLIT-1 владеет — stub для Alembic + RLS
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class Workstation(Base, UUIDMixin, TimestampMixin):
    """
    Физическая машина-воркстанция (PC Agent host).
    Детальная логика: TZ-08 SPLIT-1.
    """
    __tablename__ = "workstations"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_heartbeat_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)

    ldplayer_instances: Mapped[list["LDPlayerInstance"]] = relationship(back_populates="workstation")
