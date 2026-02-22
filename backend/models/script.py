# backend/models/script.py
# TZ-04 Script Engine владеет детальной логикой
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class ScriptVersion(Base, UUIDMixin, TimestampMixin):
    """
    Неизменяемая версия скрипта (append-only).
    Структура DAG-шагов описана в TZ-04 SPLIT-1.
    """
    __tablename__ = "script_versions"

    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"), index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dag: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    script: Mapped["Script"] = relationship(back_populates="versions")


class Script(Base, UUIDMixin, TimestampMixin):
    """
    Скрипт (набор шагов DAG) для автоматизации устройств.
    Детальная логика: TZ-04 SPLIT-1,2.
    """
    __tablename__ = "scripts"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # FK на текущую активную версию (circular FK, допустим через nullable)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("script_versions.id", use_alter=True, name="fk_script_current_version"),
        nullable=True,
    )

    versions: Mapped[list["ScriptVersion"]] = relationship(
        back_populates="script",
        foreign_keys="ScriptVersion.script_id",
    )
    current_version: Mapped["ScriptVersion | None"] = relationship(
        foreign_keys=[current_version_id],
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="script")
