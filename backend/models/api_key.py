# backend/models/api_key.py
# TZ-01 SPLIT-4 владеет, stub здесь для Alembic + TZ-03 agent auth
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class APIKey(Base, UUIDMixin, TimestampMixin):
    """
    API-ключи для сервисных аккаунтов (n8n, PC Agent, внешние интеграции).
    Полная логика создания/отзыва — TZ-01 SPLIT-4.

    ВАЖНО: поле `type` различает:
      - "user"  — обычный API-ключ пользователя (n8n, внешние интеграции)
      - "agent" — долгоживущий токен PC Agent (TZ-08)
                  проверяется в backend/api/ws/agent/router.py через authenticate_agent_token()
    """
    __tablename__ = "api_keys"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)   # "sphr_prod_a1b2" — для отображения
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # SHA-256
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # "user" | "agent"
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys", foreign_keys=[user_id])
