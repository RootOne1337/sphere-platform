# backend/models/organization.py
from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="org")
    devices: Mapped[list["Device"]] = relationship(back_populates="org")
