# backend/models/audit_log.py
# TZ-01 SPLIT-5 Audit Log — IMMUTABLE (INSERT ONLY, RLS blocks UPDATE/DELETE)
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.engine import Base


class AuditLog(Base):
    """
    Иммутабельный журнал аудита.
    НЕ наследует TimestampMixin (нет updated_at — immutable by design).
    НЕ наследует UUIDMixin — id задаётся явно для разделения ответственности.
    RLS-политика (audit_log_policies.sql) запрещает UPDATE и DELETE.
    Детальная логика: TZ-01 SPLIT-5.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
