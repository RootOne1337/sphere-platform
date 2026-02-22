# backend/models/webhook.py
# TZ-09 n8n Integration SPLIT-5 владеет детальной логикой
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class Webhook(Base, UUIDMixin, TimestampMixin):
    """
    Исходящий webhook для уведомлений (n8n, внешние системы).
    Детальная логика: TZ-09 SPLIT-5.
    """
    __tablename__ = "webhooks"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # HMAC-SHA256 подпись
    events: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Delivery tracking
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
