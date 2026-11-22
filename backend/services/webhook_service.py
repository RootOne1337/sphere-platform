"""Signed task/batch callbacks; the n8n registry has its own delivery service."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from uuid import UUID

import httpx
import structlog

logger = structlog.get_logger()

_RETRY_BACKOFF = [5, 30, 120]
_TIMEOUT = 10.0
_MAX_RETRY_AFTER = 120.0


def _subject_context(event_type: str, payload: dict) -> dict[str, str]:
    if event_type == "task.completed":
        key = "task_id"
    elif event_type == "batch.completed":
        key = "batch_id"
    else:
        return {}
    value = payload.get(key)
    if isinstance(value, UUID):
        return {key: str(value)}
    if isinstance(value, str) and len(value) == 36:
        try:
            return {key: str(UUID(value))}
        except ValueError:
            pass
    return {}


def _rate_limit_delay(response: httpx.Response, fallback: float) -> float:
    """Honor Retry-After seconds/HTTP dates within this callback's retry budget."""
    value = response.headers.get("Retry-After", "").strip()
    if not value or len(value) > 128:
        return fallback
    try:
        if value.isascii() and value.isdigit():
            delay = float(value)
        else:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                return fallback
            delay = (when - datetime.now(timezone.utc)).total_seconds()
        return min(_MAX_RETRY_AFTER, max(0.0, delay))
    except (ValueError, TypeError, OverflowError):
        return fallback


class WebhookService:
    """Deliver one callback, with at most three retries and no redirects.

    Only 2xx acknowledges delivery. 429, 5xx and transport failures may retry;
    other responses reject the callback immediately. The terminal log carries
    the delivery ID and bounded retry information. Individual attempts are
    available at DEBUG. Failure does not undo the completed task or batch.
    """

    async def deliver(
        self,
        url: str,
        payload: dict,
        secret: str | None = None,
    ) -> None:
        body = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
        delivery_id = secrets.token_hex(8)
        event_type = payload.get("event_type", "unknown")
        headers = {
            "Content-Type": "application/json",
            "X-Sphere-Event": event_type,
            "X-Sphere-Delivery": delivery_id,
        }

        if secret:
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Sphere-Signature"] = f"sha256={sig}"

        context = {"delivery_id": delivery_id, "event_type": event_type[:128], **_subject_context(event_type, payload)}
        # Pool connections within a delivery, without retaining a global client.
        delay = 0.0
        previous_retry = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT), follow_redirects=False) as client:
            for attempt in range(len(_RETRY_BACKOFF) + 1):
                if delay:
                    await asyncio.sleep(delay)
                status: int | None = None
                error_type: str | None = None
                delay = _RETRY_BACKOFF[attempt] if attempt < len(_RETRY_BACKOFF) else 0.0
                try:
                    response = await client.post(url, content=body, headers=headers)
                    status = response.status_code
                    if 200 <= status < 300:
                        logger.info(
                            "webhook.delivered", **context, status=status, outcome="delivered",
                            attempts=attempt + 1, previous_retry=previous_retry,
                        )
                        return
                    outcome = "rate_limited" if status == 429 else "server_error" if status >= 500 else "rejected"
                    retryable = status == 429 or status >= 500
                    if status == 429 and delay:
                        delay = _rate_limit_delay(response, delay)
                except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
                    outcome = "invalid_receiver"
                    retryable = False
                    error_type = type(exc).__name__
                except httpx.HTTPError as exc:
                    outcome = "transport_error"
                    retryable = True
                    # Exception messages can contain receiver URLs or query secrets.
                    error_type = type(exc).__name__
                result = {"status": status, "outcome": outcome, "error_type": error_type}
                if not retryable or attempt == len(_RETRY_BACKOFF):
                    logger.error(
                        "webhook.delivery_failed", **context, **result,
                        attempts=attempt + 1, previous_retry=previous_retry,
                    )
                    return
                retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                previous_retry = {**result, "retry_in_seconds": delay, "retry_at": retry_at.isoformat()}
                logger.debug("webhook.retry_scheduled", **context, attempt=attempt + 1, **previous_retry)
