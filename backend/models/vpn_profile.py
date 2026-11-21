"""Tenant-scoped VPN catalog. Revision payloads are encrypted and append-only."""
from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class VPNProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "vpn_profiles"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_vpn_profile_org_id"),
        CheckConstraint("current_revision >= 1", name="ck_vpn_profile_revision"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class VPNProfileRevision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "vpn_profile_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "profile_id"], ["vpn_profiles.org_id", "vpn_profiles.id"],
                             name="fk_vpn_revision_owned_profile"),
        UniqueConstraint("org_id", "profile_id", "revision", name="uq_vpn_profile_revision"),
        UniqueConstraint("org_id", "request_id", name="uq_vpn_profile_request"),
        CheckConstraint("revision >= 1", name="ck_vpn_revision_number"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(40), nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(12), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_policy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(300), nullable=False)
    features: Mapped[list] = mapped_column(JSONB, nullable=False)
    config_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
