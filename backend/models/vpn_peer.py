# backend/models/vpn_peer.py
# TZ-06 VPN AmneziaWG  SPLIT-2: added VPNPeerStatus, status column, nullable device_id
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class VPNIPAddress(TypeDecorator):
    """Keep the public model's string contract with asyncpg's native INET type."""

    impl = INET
    cache_ok = True

    def process_result_value(self, value, dialect):
        return str(value) if value is not None else None


class VPNPeerStatus(str, enum.Enum):
    FREE = "free"          # IP returned to pool, not assigned to any device
    ASSIGNED = "assigned"  # Active peer assigned to a device
    ERROR = "error"        # Assignment in error state
    PROVISIONING = "provisioning"  # Committed intent; provider outcome may be unknown
    REVOKING = "revoking"          # Address held until deletion and SQL commit


class VPNPeer(Base, UUIDMixin, TimestampMixin):
    """
    WireGuard/AmneziaWG peer.
    Private key stored encrypted (Fernet AES-128-CBC+HMAC).
    """
    __tablename__ = "vpn_peers"
    __table_args__ = (
        Index("uq_vpn_held_ip", "tunnel_ip", unique=True,
              postgresql_where=text("status <> 'FREE'"), sqlite_where=text("status <> 'FREE'")),
        CheckConstraint(
            "tunnel_ip IS NULL OR masklen(tunnel_ip) = CASE WHEN family(tunnel_ip) = 4 THEN 32 ELSE 128 END",
            name="ck_vpn_ip_is_host",
        ).ddl_if(dialect="postgresql"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id"), unique=True, index=True, nullable=True
    )

    public_key: Mapped[str] = mapped_column(String(64), nullable=False)
    private_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    preshared_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    awg_jc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_jmin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_jmax: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_s1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_s2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_h1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_h2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_h3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_h4: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tunnel_ip: Mapped[str | None] = mapped_column(VPNIPAddress().with_variant(String(45), "sqlite"), nullable=True)
    operation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    split_tunnel: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    allowed_ips: Mapped[str] = mapped_column(String(255), default="0.0.0.0/0", nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    listen_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[VPNPeerStatus] = mapped_column(
        Enum(VPNPeerStatus, name="vpn_peer_status", native_enum=False, length=32),
        default=VPNPeerStatus.ASSIGNED,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_handshake_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
