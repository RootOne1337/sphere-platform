"""Signed task/batch callbacks; the n8n registry has its own delivery service."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
import structlog

logger = structlog.get_logger()

_RETRY_BACKOFF = [5, 30, 120]
_TIMEOUT = 10.0
_MAX_RETRY_AFTER = 120.0


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
    other responses reject the callback immediately. Logs share a delivery ID
    across attempts. Failure does not undo the completed task or batch.
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

        # Pool connections within a delivery, without retaining a global client.
        delay = 0.0
        outcome = "transport_error"
        status: int | None = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT), follow_redirects=False) as client:
            for attempt in range(len(_RETRY_BACKOFF) + 1):
                if delay:
                    await asyncio.sleep(delay)
                context = {"delivery_id": delivery_id, "event_type": event_type, "attempt": attempt}
                try:
                    response = await client.post(url, content=body, headers=headers)
                    status = response.status_code
                    if 200 <= status < 300:
                        logger.info(
                            "webhook.delivered", **context, status=status, outcome="delivered",
                        )
                        return
                    outcome = "rate_limited" if status == 429 else "server_error" if status >= 500 else "rejected"
                    retryable = status == 429 or status >= 500
                    delay = _RETRY_BACKOFF[attempt] if attempt < len(_RETRY_BACKOFF) else 0.0
                    if status == 429 and delay:
                        delay = _rate_limit_delay(response, delay)
                    logger.warning(
                        f"webhook.{outcome}", **context, status=status,
                        retryable=retryable,
                        retry_in_seconds=delay if retryable and attempt < len(_RETRY_BACKOFF) else None,
                    )
                    if not retryable:
                        break
                except httpx.HTTPError as exc:
                    status = None
                    outcome = "transport_error"
                    delay = _RETRY_BACKOFF[attempt] if attempt < len(_RETRY_BACKOFF) else 0.0
                    # Exception messages can contain receiver URLs or query secrets.
                    logger.warning(
                        "webhook.network_error", **context, error_type=type(exc).__name__,
                        retryable=True,
                        retry_in_seconds=delay if attempt < len(_RETRY_BACKOFF) else None,
                    )
        logger.error(
            "webhook.delivery_failed", delivery_id=delivery_id, event_type=event_type,
            attempts=attempt + 1, status=status, outcome=outcome,
        )
