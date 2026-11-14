"""Tenant application metadata for the operator catalog."""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class ApplicationProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "application_profiles"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_application_profile_org_key"),
        UniqueConstraint("org_id", "id", name="uq_application_profile_org_id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    android_package: Mapped[str | None] = mapped_column(String(255), nullable=True)
    servers: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
