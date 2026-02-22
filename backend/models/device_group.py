# backend/models/device_group.py
# TZ-02 SPLIT-2 владеет — Device Groups с иерархией и цветами.
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class DeviceGroup(Base, UUIDMixin, TimestampMixin):
    """
    Группа устройств для массовых операций (TZ-02 SPLIT-2).
    Один device может быть в нескольких группах через M2M.
    Поддерживает иерархию (parent → children) и цветовую маркировку.
    """
    __tablename__ = "device_groups"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_device_group_name"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)   # #RRGGBB
    parent_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("device_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    # dynamic filter для auto-discovery (TZ-02 SPLIT-5)
    filter_criteria: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)

    devices: Mapped[list["Device"]] = relationship(
        secondary="device_group_members",
        back_populates="groups",
    )
    parent: Mapped["DeviceGroup | None"] = relationship(
        "DeviceGroup",
        foreign_keys=[parent_group_id],
        back_populates="children",
        remote_side="DeviceGroup.id",
    )
    children: Mapped[list["DeviceGroup"]] = relationship(
        "DeviceGroup",
        foreign_keys="DeviceGroup.parent_group_id",
        back_populates="parent",
    )
