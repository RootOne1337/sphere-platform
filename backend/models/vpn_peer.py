# backend/models/vpn_peer.py
# TZ-06 VPN AmneziaWG владеет детальной логикой
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class VPNPeer(Base, UUIDMixin, TimestampMixin):
    """
    WireGuard/AmneziaWG peer для устройства.
    Приватный ключ хранится зашифрованным (AES-256-GCM, ключ из HSM/Vault).
    Детальная логика: TZ-06 SPLIT-1,2.
    """
    __tablename__ = "vpn_peers"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), unique=True, index=True)

    # WireGuard keys
    public_key: Mapped[str] = mapped_column(String(44), nullable=False)
    # Encrypted private key: nonce(12) + ciphertext — хранится как bytea
    private_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    preshared_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # AmneziaWG obfuscation parameters
    awg_jc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_jmin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_jmax: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_s1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_s2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_h1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_h2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_h3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awg_h4: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Allocated tunnel IP
    tunnel_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv4 or IPv6
    allowed_ips: Mapped[str] = mapped_column(String(255), default="0.0.0.0/0", nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    listen_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_handshake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
