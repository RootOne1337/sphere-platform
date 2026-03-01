# backend/models/device.py
# TZ-02 Device Registry владеет детальной логикой
from __future__ import annotations

import enum
import uuid

from sqlalchemy import ARRAY, Boolean, Column, Enum, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class DeviceStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"
    MAINTENANCE = "maintenance"


# M2M association table: device <-> device_group
device_group_members = Table(
    "device_group_members",
    Base.metadata,
    Column("device_id", ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("device_groups.id", ondelete="CASCADE"), primary_key=True),
)


class Device(Base, UUIDMixin, TimestampMixin):
    """
    Устройство (Android эмулятор/реальное устройство).
    Статус хранится в Redis (TTL), в БД — неизменяемая анкета.
    Детальная логика: TZ-02.
    """
    __tablename__ = "devices"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    serial: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)   # ADB serial
    android_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Last known status — source of truth is Redis; this column updated async via WebSocket events
    last_status: Mapped[str] = mapped_column(
        Enum(DeviceStatus, name="device_status_enum", values_callable=lambda x: [e.value for e in x]),
        default=DeviceStatus.OFFLINE,
        nullable=False,
    )
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    org: Mapped["Organization"] = relationship(back_populates="devices")
    groups: Mapped[list["DeviceGroup"]] = relationship(
        secondary="device_group_members",
        back_populates="devices",
    )
    locations: Mapped[list["Location"]] = relationship(
        secondary="device_location_members",
        back_populates="devices",
    )
    ldplayer_instance: Mapped["LDPlayerInstance | None"] = relationship(back_populates="device")
