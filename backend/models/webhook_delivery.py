"""Tenant-owned webhook jobs and their bounded delivery attempts."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class WebhookDelivery(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sending', 'delivered', 'dead')", name="ck_webhook_delivery_status"),
        CheckConstraint(
            "source IN ('task_callback', 'subscription')", name="ck_webhook_delivery_source",
        ),
        CheckConstraint(
            "replay_count BETWEEN 0 AND 1 AND attempts_count BETWEEN 0 AND max_attempts "
            "AND max_attempts BETWEEN 4 AND 8", name="ck_webhook_delivery_budget",
        ),
        CheckConstraint("body_bytes BETWEEN 0 AND 262144", name="ck_webhook_delivery_body_size"),
        Index("ix_webhook_deliveries_org_history", "org_id", "created_at", "id"),
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at", "id"),
        Index("ix_webhook_deliveries_expiry", "status", "updated_at", "id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    # Keep the original subscription ID in history if the operator deletes it.
    webhook_id: Mapped[uuid.UUID | None]
    subject_id: Mapped[uuid.UUID | None]
    source: Mapped[str] = mapped_column(String(24))
    event_type: Mapped[str] = mapped_column(String(100))
    destination: Mapped[str | None] = mapped_column(Text)
    body: Mapped[bytes | None] = mapped_column(LargeBinary)
    body_bytes: Mapped[int] = mapped_column(Integer, default=0)
    signature: Mapped[str | None] = mapped_column(String(71))
    status: Mapped[str] = mapped_column(String(12))
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    replay_count: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[uuid.UUID | None]
    last_http_status: Mapped[int | None]
    last_error: Mapped[str | None] = mapped_column(String(40))
