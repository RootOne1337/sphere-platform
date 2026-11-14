"""Claim and deliver webhook jobs without holding a database transaction over HTTP."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.lifespan_registry import register_shutdown, register_startup
from backend.database.engine import AsyncSessionLocal
from backend.database.tenant import bind_tenant_context
from backend.models.webhook import Webhook
from backend.models.webhook_delivery import WebhookDelivery
from backend.services.webhook_outbox import (
    ACTIVE_STATUSES,
    ATTEMPTS_PER_GENERATION,
    TERMINAL_STATUSES,
    subscription_receiver_allowed,
)
from backend.services.webhook_service import _rate_limit_delay

logger = structlog.get_logger()
_RETRY_DELAYS = (5, 30, 120)
_HTTP_DEADLINE = 12
_LEASE_SECONDS = 45
_SQL_TIMEOUT_SECONDS = 5
_POLL_SECONDS = 2
_PRUNE_SECONDS = 60
_CONCURRENCY = 4


@dataclass(frozen=True)
class Claim:
    id: uuid.UUID
    org_id: uuid.UUID
    token: uuid.UUID
    destination: str
    body: bytes
    signature: str | None
    event_type: str
    generation_attempt: int


@dataclass(frozen=True)
class Attempt:
    http_status: int | None
    error: str | None
    retry_delay: float | None = None


def _finish_attempt(delivery: WebhookDelivery, status: str, result: Attempt, now: datetime) -> None:
    previous = delivery.attempts[-1]
    delivery.attempts = [*delivery.attempts[:-1], {
        **previous,
        "status": status,
        "http_status": result.http_status,
        "error": result.error,
        "finished_at": now.isoformat(),
    }]
    delivery.last_http_status = result.http_status
    delivery.last_error = result.error


async def _finish_terminal(
    db: AsyncSession, delivery: WebhookDelivery, status: str, now: datetime,
) -> None:
    delivery.status = status
    delivery.claim_token = None
    delivery.next_attempt_at = None
    if status == "delivered" or delivery.replay_count or delivery.last_error == "invalid_receiver":
        # Operators inspect metadata, and only dead jobs need payloads for replay.
        delivery.body = delivery.destination = delivery.signature = None
        delivery.body_bytes = 0
    if delivery.webhook_id is None:
        return
    statement = update(Webhook).where(
        Webhook.org_id == delivery.org_id, Webhook.id == delivery.webhook_id,
    )
    if status == "delivered":
        statement = statement.values(failure_count=0, last_error=None, last_triggered_at=now)
    else:
        statement = statement.values(failure_count=Webhook.failure_count + 1, last_error=delivery.last_error)
    await db.execute(statement)


async def _claim_job(delivery_id: uuid.UUID, org_id: uuid.UUID) -> Claim | None:
    async with asyncio.timeout(_SQL_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
        await bind_tenant_context(db, str(org_id))
        delivery = await db.scalar(select(WebhookDelivery).where(
            WebhookDelivery.id == delivery_id, WebhookDelivery.org_id == org_id,
            WebhookDelivery.status.in_(ACTIVE_STATUSES),
            WebhookDelivery.next_attempt_at <= func.clock_timestamp(),
        ).with_for_update(skip_locked=True))
        if delivery is None:
            return None
        now = datetime.now(timezone.utc)
        if delivery.status == "sending":
            _finish_attempt(delivery, "unknown", Attempt(None, "worker_interrupted"), now)
        blocked = None
        if delivery.source == "subscription":
            enabled = await db.scalar(select(Webhook.is_active).where(
                Webhook.org_id == org_id, Webhook.id == delivery.webhook_id,
            ))
            if not settings.WEBHOOK_SUBSCRIPTIONS_ENABLED or not enabled:
                blocked = "subscription_disabled"
            elif not delivery.destination or not subscription_receiver_allowed(delivery.destination):
                blocked = "receiver_not_allowed"
        if delivery.body is None or delivery.destination is None:
            blocked = blocked or "invalid_receiver"
        if blocked or delivery.attempts_count >= delivery.max_attempts:
            delivery.last_error = blocked or "retry_exhausted"
            delivery.last_http_status = None
            await _finish_terminal(db, delivery, "dead", now)
            await db.commit()
            logger.info(
                "webhook.outbox_terminal", delivery_id=str(delivery.id), status=delivery.status,
                attempts=delivery.attempts_count, reason=delivery.last_error,
            )
            return None
        assert delivery.destination is not None and delivery.body is not None
        delivery.status = "sending"
        delivery.claim_token = uuid.uuid4()
        delivery.attempts_count += 1
        delivery.next_attempt_at = now + timedelta(seconds=_LEASE_SECONDS)
        delivery.attempts = [*delivery.attempts, {
            "number": delivery.attempts_count, "status": "sending", "http_status": None, "error": None,
            "started_at": now.isoformat(), "finished_at": None,
        }]
        claim = Claim(
            delivery.id, org_id, delivery.claim_token, delivery.destination, delivery.body, delivery.signature,
            delivery.event_type, delivery.attempts_count - delivery.max_attempts + ATTEMPTS_PER_GENERATION,
        )
        await db.commit()
        return claim


async def _send(claim: Claim, client: httpx.AsyncClient) -> Attempt:
    headers = {
        "Content-Type": "application/json", "X-Sphere-Event": claim.event_type, "X-Sphere-Delivery": str(claim.id),
    }
    if claim.signature:
        headers["X-Sphere-Signature"] = claim.signature
    fallback = _RETRY_DELAYS[min(claim.generation_attempt - 1, len(_RETRY_DELAYS) - 1)]
    try:
        # The status is sufficient. Never buffer or retain an untrusted response body.
        async with asyncio.timeout(_HTTP_DEADLINE), client.stream(
            "POST", claim.destination, content=claim.body, headers=headers,
        ) as response:
            status = response.status_code
            if 200 <= status < 300:
                return Attempt(status, None)
            if status == 429:
                return Attempt(status, "rate_limited", _rate_limit_delay(response, fallback))
            if 500 <= status < 600:
                return Attempt(status, "server_error", fallback)
            return Attempt(status, "rejected")
    except (httpx.InvalidURL, httpx.UnsupportedProtocol):
        return Attempt(None, "invalid_receiver")
    except (TimeoutError, httpx.TimeoutException):
        return Attempt(None, "timeout", fallback)
    except httpx.HTTPError:
        return Attempt(None, "transport_error", fallback)


async def _complete(claim: Claim, result: Attempt) -> None:
    async with asyncio.timeout(_SQL_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
        await bind_tenant_context(db, str(claim.org_id))
        delivery = await db.scalar(select(WebhookDelivery).where(
            WebhookDelivery.id == claim.id, WebhookDelivery.org_id == claim.org_id,
            WebhookDelivery.status == "sending", WebhookDelivery.claim_token == claim.token,
        ).with_for_update())
        if delivery is None:
            return
        now = datetime.now(timezone.utc)
        terminal = "delivered" if result.error is None else "dead"
        if result.retry_delay is not None and delivery.attempts_count < delivery.max_attempts:
            _finish_attempt(delivery, "retry", result, now)
            delivery.status = "pending"
            delivery.claim_token = None
            delivery.next_attempt_at = now + timedelta(seconds=result.retry_delay)
        else:
            _finish_attempt(delivery, terminal, result, now)
            await _finish_terminal(db, delivery, terminal, now)
        await db.commit()
        if delivery.status in TERMINAL_STATUSES:
            logger.info(
                "webhook.outbox_terminal", delivery_id=str(claim.id), status=delivery.status,
                attempts=delivery.attempts_count, http_status=result.http_status, reason=result.error,
            )


async def _discover(expired: bool) -> list[tuple[uuid.UUID, uuid.UUID]]:
    async with asyncio.timeout(_SQL_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
        rows = (await db.execute(text("SELECT * FROM sphere_auth.webhook_work(:expired)"), {"expired": expired})).all()
        return [(row[0], row[1]) for row in rows]


async def _prune(delivery_id: uuid.UUID, org_id: uuid.UUID) -> None:
    async with asyncio.timeout(_SQL_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
        await bind_tenant_context(db, str(org_id))
        await db.execute(delete(WebhookDelivery).where(
            WebhookDelivery.id == delivery_id, WebhookDelivery.org_id == org_id,
            WebhookDelivery.status.in_(TERMINAL_STATUSES),
            WebhookDelivery.updated_at <= datetime.now(timezone.utc) - timedelta(days=30),
        ))
        await db.commit()


async def _process(delivery_id: uuid.UUID, org_id: uuid.UUID, client: httpx.AsyncClient) -> None:
    try:
        claim = await _claim_job(delivery_id, org_id)
        if claim:
            await _complete(claim, await _send(claim, client))
    except Exception as exc:
        logger.debug("webhook.outbox_job_retry", delivery_id=str(delivery_id), error_type=type(exc).__name__)


async def _worker() -> None:
    next_prune = next_error_log = 0.0
    loop = asyncio.get_running_loop()
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        while True:
            try:
                candidates = await _discover(False)
                for offset in range(0, len(candidates), _CONCURRENCY):
                    await asyncio.gather(*(_process(*pair, client) for pair in candidates[offset:offset + _CONCURRENCY]))
                if loop.time() >= next_prune:
                    next_prune = loop.time() + _PRUNE_SECONDS
                    for pair in await _discover(True):
                        await _prune(*pair)
            except Exception as exc:
                if loop.time() >= next_error_log:
                    next_error_log = loop.time() + 60
                    logger.warning("webhook.outbox_worker_unavailable", error_type=type(exc).__name__)
            await asyncio.sleep(_POLL_SECONDS)


async def _startup() -> None:
    task = asyncio.create_task(_worker(), name="webhook-outbox")

    async def shutdown() -> None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    register_shutdown("webhook_outbox", shutdown)


register_startup("webhook_outbox", _startup)
