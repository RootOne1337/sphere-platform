"""Create and inspect durable webhook jobs inside the caller's transaction."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.webhook import Webhook
from backend.models.webhook_delivery import WebhookDelivery

logger = structlog.get_logger()
SUBSCRIPTION_EVENTS = ("task.completed", "task.failed")
ACTIVE_STATUSES = ("pending", "sending")
TERMINAL_STATUSES = ("delivered", "dead")
MAX_SUBSCRIPTIONS = 32
MAX_PENDING = 2_000
MAX_HISTORY = 10_000
MAX_BODY = 256 * 1024
MAX_TENANT_BODY_BYTES = 64 * 1024 * 1024
MAX_DESTINATION = 2_048
ATTEMPTS_PER_GENERATION = 4


def _origin(value: str, *, configuration: bool = False) -> tuple[str, str, int] | None:
    if not isinstance(value, str) or len(value) > MAX_DESTINATION:
        return None
    try:
        url = httpx.URL(value)
    except (httpx.InvalidURL, TypeError, ValueError):
        return None
    if url.scheme not in ("http", "https") or not url.host or url.userinfo or url.fragment:
        return None
    if configuration and (url.path not in ("", "/") or url.query):
        return None
    return url.scheme, url.host, url.port or (443 if url.scheme == "https" else 80)


def subscription_receiver_allowed(value: str) -> bool:
    receiver = _origin(value)
    return receiver is not None and any(
        receiver == _origin(origin, configuration=True) for origin in settings.WEBHOOK_ALLOWED_ORIGINS
    )


async def lock_webhook_tenant(db: AsyncSession, org_id: uuid.UUID) -> None:
    if db.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(f"sphere:webhooks:v1:{org_id}".encode()).digest()[:8], "big", signed=True)
        await db.execute(select(func.pg_advisory_xact_lock(key)))


async def enforce_active_subscription_limit(db: AsyncSession, org_id: uuid.UUID) -> None:
    await lock_webhook_tenant(db, org_id)
    count = await db.scalar(select(func.count()).select_from(Webhook).where(
        Webhook.org_id == org_id, Webhook.is_active.is_(True),
    ))
    if count is not None and count >= MAX_SUBSCRIPTIONS:
        raise HTTPException(409, "webhook_active_subscription_limit")


async def _pending_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    count = await db.scalar(select(func.count()).select_from(WebhookDelivery).where(
        WebhookDelivery.org_id == org_id, WebhookDelivery.status.in_(ACTIVE_STATUSES),
    ))
    return count or 0


async def _make_history_room(db: AsyncSession, org_id: uuid.UUID, count: int) -> None:
    retained = await db.scalar(select(func.count()).select_from(WebhookDelivery).where(
        WebhookDelivery.org_id == org_id,
    ))
    remove = (retained or 0) + count - MAX_HISTORY
    if remove > 0:
        victims = select(WebhookDelivery.id).where(
            WebhookDelivery.org_id == org_id, WebhookDelivery.status.in_(TERMINAL_STATUSES),
        ).order_by(WebhookDelivery.updated_at, WebhookDelivery.id).limit(remove)
        await db.execute(delete(WebhookDelivery).where(
            WebhookDelivery.org_id == org_id, WebhookDelivery.id.in_(victims),
        ).execution_options(synchronize_session=False))


def _encode_callback(payload: dict[str, Any]) -> bytes:
    # Keep the body bytes of the established callback contract.
    return json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")


def _delivery(
    org_id: uuid.UUID, subject_id: uuid.UUID, event_type: str, source: str, now: datetime,
    *, destination: str | None = None, body: bytes | None = None,
    subscription: Webhook | None = None, subscription_payload: dict[str, Any] | None = None,
    error: str | None = None, remaining_bytes: int = MAX_TENANT_BODY_BYTES,
) -> WebhookDelivery:
    delivery_id = uuid.uuid4()
    if subscription is not None:
        envelope = {
            "event": event_type, "data": subscription_payload,
            "timestamp": int(now.timestamp()), "delivery_id": str(delivery_id),
        }
        body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if body is not None and len(body) > MAX_BODY:
        error = "payload_too_large"
        body = None
    if error in (None, "delivery_capacity_reached") and body is not None and len(body) > remaining_bytes:
        error = "delivery_storage_capacity"
    if error is not None and error != "delivery_capacity_reached":
        destination = None
        body = None
    signature = None
    if subscription is not None and body is not None:
        signature = "sha256=" + hmac.new((subscription.secret_hash or "").encode(), body, hashlib.sha256).hexdigest()
    return WebhookDelivery(
        id=delivery_id, org_id=org_id, webhook_id=subscription.id if subscription else None, subject_id=subject_id,
        source=source, event_type=event_type, destination=destination, body=body,
        body_bytes=len(body) if body is not None else 0, signature=signature,
        status="dead" if error else "pending", attempts_count=0, max_attempts=ATTEMPTS_PER_GENERATION,
        replay_count=0, attempts=[], next_attempt_at=None if error else now, last_error=error,
    )


async def enqueue_task_webhooks(
    db: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, callback_url: str | None,
    callback_payload: dict[str, Any], event_type: str, subscription_payload: dict[str, Any],
    tags: list[str],
) -> None:
    """Record terminal task delivery intent. Call before committing the terminal result."""
    if not callback_url and not settings.WEBHOOK_SUBSCRIPTIONS_ENABLED:
        return
    await lock_webhook_tenant(db, org_id)
    now = datetime.now(timezone.utc)
    pending = await _pending_count(db, org_id)
    stored_bytes = await db.scalar(select(func.sum(WebhookDelivery.body_bytes)).where(WebhookDelivery.org_id == org_id))
    remaining_bytes = MAX_TENANT_BODY_BYTES - (stored_bytes or 0)
    deliveries: list[WebhookDelivery] = []
    if callback_url:
        deliveries.append(_delivery(
            org_id, task_id, "task.completed", "task_callback", now,
            destination=callback_url, body=_encode_callback(callback_payload),
            error=("invalid_receiver" if _origin(callback_url) is None
                   else "delivery_capacity_reached" if pending >= MAX_PENDING else None),
            remaining_bytes=remaining_bytes,
        ))
        pending += deliveries[-1].status == "pending"
        remaining_bytes -= deliveries[-1].body_bytes
    if settings.WEBHOOK_SUBSCRIPTIONS_ENABLED and event_type in SUBSCRIPTION_EVENTS:
        subscriptions = list(await db.scalars(select(Webhook).where(
            Webhook.org_id == org_id, Webhook.is_active.is_(True),
        ).order_by(Webhook.id).limit(MAX_SUBSCRIPTIONS + 1)))
        if len(subscriptions) > MAX_SUBSCRIPTIONS:
            deliveries.append(_delivery(
                org_id, task_id, event_type, "subscription", now, error="subscription_fanout_limit",
            ))
        else:
            for subscription in subscriptions:
                if event_type not in subscription.events and "*" not in subscription.events:
                    continue
                if subscription.tags and not set(subscription.tags).intersection(tags):
                    continue
                error = None
                if not subscription_receiver_allowed(subscription.url):
                    error = "receiver_not_allowed"
                elif pending >= MAX_PENDING:
                    error = "delivery_capacity_reached"
                deliveries.append(_delivery(
                    org_id, task_id, event_type, "subscription", now,
                    destination=subscription.url, subscription=subscription, subscription_payload=subscription_payload,
                    error=error, remaining_bytes=remaining_bytes,
                ))
                pending += deliveries[-1].status == "pending"
                remaining_bytes -= deliveries[-1].body_bytes
    if deliveries:
        await _make_history_room(db, org_id, len(deliveries))
        db.add_all(deliveries)
        await db.flush()


def may_replay(
    delivery: WebhookDelivery, subscription: Webhook | None, *, has_body: bool | None = None,
) -> bool:
    if has_body is None:
        has_body = delivery.body is not None
    if (delivery.status != "dead" or delivery.replay_count
            or not has_body or delivery.destination is None):
        return False
    return delivery.source == "task_callback" or (
        settings.WEBHOOK_SUBSCRIPTIONS_ENABLED and subscription is not None and subscription.is_active
        and subscription_receiver_allowed(delivery.destination)
    )


async def replay_delivery(db: AsyncSession, org_id: uuid.UUID, delivery_id: uuid.UUID) -> WebhookDelivery:
    await lock_webhook_tenant(db, org_id)
    delivery = await db.scalar(select(WebhookDelivery).where(
        WebhookDelivery.org_id == org_id, WebhookDelivery.id == delivery_id,
    ).with_for_update())
    if delivery is None:
        raise HTTPException(404, "Webhook delivery not found")
    subscription = await db.scalar(select(Webhook).where(
        Webhook.org_id == org_id, Webhook.id == delivery.webhook_id,
    )) if delivery.webhook_id is not None else None
    if not may_replay(delivery, subscription):
        raise HTTPException(409, "webhook_replay_unavailable")
    if await _pending_count(db, org_id) >= MAX_PENDING:
        raise HTTPException(409, "webhook_delivery_capacity_reached")
    delivery.replay_count = 1
    delivery.max_attempts = delivery.attempts_count + ATTEMPTS_PER_GENERATION
    delivery.status = "pending"
    delivery.next_attempt_at = datetime.now(timezone.utc)
    delivery.claim_token = None
    await db.flush()
    return delivery
