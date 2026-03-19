# backend/models/location.py
# TZ-02: Локации устройств. M2M связь — одно устройство может быть в нескольких локациях.
from __future__ import annotations

import uuid

from sqlalchemy import Column, ForeignKey, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin

# M2M association table: device <-> location
device_location_members = Table(
    "device_location_members",
    Base.metadata,
    Column("device_id", ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
    Column("location_id", ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
)


class Location(Base, UUIDMixin, TimestampMixin):
    """
    Локация — физическое или логическое размещение устройств.
    Поддерживает иерархию (parent → children), цветовую маркировку,
    адрес и GPS-координаты. M2M через device_location_members.
    """
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_location_name"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)       # #RRGGBB
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)    # Адрес / описание размещения
    # GPS-координаты (nullable — не обязательны)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    # Иерархия: Дата-центр → Этаж → Комната
    parent_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Произвольные метаданные (контакты, ёмкость, комментарии)
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)

    devices: Mapped[list["Device"]] = relationship(
        secondary="device_location_members",
        back_populates="locations",
    )
    parent: Mapped["Location | None"] = relationship(
        "Location",
        foreign_keys=[parent_location_id],
        back_populates="children",
        remote_side="Location.id",
    )
    children: Mapped[list["Location"]] = relationship(
        "Location",
        foreign_keys="Location.parent_location_id",
        back_populates="parent",
    )
