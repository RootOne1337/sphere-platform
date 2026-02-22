# backend/models/refresh_token.py
# TZ-01 SPLIT-1 JWT Login владеет детальной логикой
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class RefreshToken(Base, UUIDMixin, TimestampMixin):
    """
    Refresh-токен для ротации JWT пары.
    Ротация: при использовании старый токен помечается revoked=True,
    выпускается новая пара. Blacklist revoked токенов — Redis.
    Детальная логика: TZ-01 SPLIT-1.
    """
    __tablename__ = "refresh_tokens"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # SHA-256
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
