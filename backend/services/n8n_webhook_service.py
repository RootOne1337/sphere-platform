# backend/services/n8n_webhook_service.py
# TZ-09 SPLIT-5 — WebhookService: delivery, HMAC signing, retry
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import TYPE_CHECKING

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.webhook import Webhook

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()

# Background task registry — prevents GC of fire-and-forget tasks
_background_tasks: set[asyncio.Task] = set()

# Retry delays in seconds: attempt 1→5s, 2→30s, 3→120s
RETRY_DELAYS = [5, 30, 120]


class N8nWebhookService:
    """
    Handles registration and delivery of outbound webhooks to n8n
    (or any HTTP endpoint) on behalf of Sphere Platform events.
    """

    # ── Registration ──────────────────────────────────────────────────────────

    async def create_webhook(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        name: str,
        url: str,
        events: list[str],
        tags: list[str] | None = None,
        secret: str | None = None,
    ) -> tuple[Webhook, str]:
        """
        Create and persist a new webhook registration.
        Returns (Webhook model instance, plain-text secret).
        The plain secret is returned ONCE here; only its hash is stored.
        """
        plain_secret = secret or secrets.token_hex(32)
        secret_hash = hashlib.sha256(plain_secret.encode()).hexdigest()

        webhook = Webhook(
            org_id=org_id,
            name=name,
            url=url,
            events=events,
            tags=tags or [],
            secret_hash=secret_hash,
            is_active=True,
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)
        return webhook, plain_secret

    async def delete_webhook(
        self,
        db: AsyncSession,
        webhook_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> bool:
        result = await db.get(Webhook, webhook_id)
        if result is None or result.org_id != org_id:
            return False
        await db.delete(result)
        await db.commit()
        return True

    async def get_org_webhooks(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
    ) -> list[Webhook]:
        stmt = select(Webhook).where(
            Webhook.org_id == org_id,
            Webhook.is_active == True,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ── Delivery ──────────────────────────────────────────────────────────────

    async def dispatch_event(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        event_type: str,
        payload: dict,
    ) -> None:
        """
        Fire-and-forget: find matching webhooks and schedule delivery tasks.
        Safe to call from sync or async context.
        """
        webhooks = await self.get_org_webhooks(db, org_id)
        for webhook in webhooks:
            if not self._matches(webhook, event_type, payload):
                continue
            # FIX 9.2: fire-and-forget with GC protection
            task = asyncio.create_task(
                self._deliver_with_retry(webhook, event_type, payload, db)
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    async def deliver(
        self,
        webhook: Webhook,
        event_type: str,
        payload: dict,
    ) -> bool:
        """Direct delivery (for synchronous call paths). Returns True on success."""
        if not self._matches(webhook, event_type, payload):
            return True
        return await self._attempt_delivery(webhook, event_type, payload)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _matches(self, webhook: Webhook, event_type: str, payload: dict) -> bool:
        """Check event type and optional tag filter."""
        events = webhook.events or []
        if "*" not in events and event_type not in events:
            return False
        if webhook.tags:
            return self._tags_match(webhook.tags, payload)
        return True

    def _tags_match(self, filter_tags: list[str], payload: dict) -> bool:
        """OR logic: at least one filter tag must appear in device tags."""
        device_tags: list[str] = payload.get("device", {}).get("tags", [])
        return any(t in device_tags for t in filter_tags)

    def _sign(self, body: str, secret_hash: str) -> str:
        """HMAC-SHA256 signature for outbound payload."""
        return hmac.new(
            secret_hash.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def _deliver_with_retry(
        self,
        webhook: Webhook,
        event_type: str,
        payload: dict,
        db: AsyncSession,
    ) -> None:
        success = await self._attempt_delivery(webhook, event_type, payload)
        if success:
            return

        for delay in RETRY_DELAYS:
            await asyncio.sleep(delay)
            if await self._attempt_delivery(webhook, event_type, payload):
                await self._reset_failure_count(webhook, db)
                return

        logger.error(
            f"Webhook {webhook.id} delivery failed after {len(RETRY_DELAYS) + 1} attempts "
            f"(event={event_type}, url={webhook.url})"
        )
        await self._record_failure(webhook, db, f"Exhausted {len(RETRY_DELAYS) + 1} delivery attempts")

    async def _attempt_delivery(
        self,
        webhook: Webhook,
        event_type: str,
        payload: dict,
    ) -> bool:
        body = {
            "event": event_type,
            "data": payload,
            "timestamp": int(time.time()),
        }
        body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        signature = self._sign(body_json, webhook.secret_hash or "")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    webhook.url,
                    content=body_json.encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-Sphere-Signature": f"sha256={signature}",
                        "X-Sphere-Event": event_type,
                    },
                )
            if resp.status_code < 300:
                logger.info(f"Webhook delivered: {event_type} → {webhook.url} [{resp.status_code}]")
                return True
            logger.warning(
                f"Webhook {webhook.id} HTTP {resp.status_code} for event={event_type}"
            )
        except Exception as exc:
            logger.warning(f"Webhook {webhook.id} delivery exception: {exc}")
        return False

    async def _record_failure(
        self, webhook: Webhook, db: AsyncSession, error: str
    ) -> None:
        webhook.failure_count = (webhook.failure_count or 0) + 1
        webhook.last_error = error
        db.add(webhook)
        await db.commit()

    async def _reset_failure_count(self, webhook: Webhook, db: AsyncSession) -> None:
        from datetime import datetime, timezone
        webhook.failure_count = 0
        webhook.last_error = None
        webhook.last_triggered_at = datetime.now(timezone.utc)
        db.add(webhook)
        await db.commit()


# Singleton
n8n_webhook_service = N8nWebhookService()
