# backend/services/webhook_service.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-5. Webhook delivery с HMAC-SHA256 подписью и retry.
#
# ⚠️ MERGE CONFLICT WARNING (TZ-04 + TZ-09):
# TZ-09 SPLIT-5 (Telemetry Pipeline) также определяет backend/services/webhook_service.py
# для n8n suspend/resume интеграции.
#
# РЕШЕНИЕ при merge TZ-04 + TZ-09:
#   — Объединить в единый WebhookService (рекомендуется httpx)
#   — Сохранить оба метода: task completions (этот файл) + n8n suspend/resume (TZ-09)
#   — Канонический файл: backend/services/webhook_service.py (один на всё приложение)
#
# Механизм retry:
#   Attempt 0: сразу
#   Attempt 1: +5s
#   Attempt 2: +30s
#   Attempt 3: +120s
#   После 3 retry — логируем failure, не кидаем исключение.
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

import httpx
import structlog

logger = structlog.get_logger()

_RETRY_BACKOFF = [5, 30, 120]   # секунды между попытками
_TIMEOUT = 10.0                  # таймаут HTTP запроса


class WebhookService:
    """
    Доставляет webhook с HMAC-SHA256 подписью.
    Retry с exponential backoff при 5xx или сетевой ошибке.
    """

    async def deliver(
        self,
        url: str,
        payload: dict,
        secret: str | None = None,
    ) -> None:
        """
        Доставить webhook payload на указанный URL.

        Заголовки:
            X-Sphere-Event      — тип события (из payload["event_type"])
            X-Sphere-Delivery   — уникальный ID доставки (hex)
            X-Sphere-Signature  — sha256=<hmac> (только при secret)
        """
        body = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "X-Sphere-Event": payload.get("event_type", "unknown"),
            "X-Sphere-Delivery": secrets.token_hex(8),
        }

        if secret:
            # HMAC-SHA256 для верификации на стороне получателя
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Sphere-Signature"] = f"sha256={sig}"

        for attempt, delay in enumerate([0] + _RETRY_BACKOFF):
            if delay:
                import asyncio
                await asyncio.sleep(delay)

            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(_TIMEOUT)
                ) as client:
                    resp = await client.post(url, content=body, headers=headers)

                    if resp.status_code < 500:
                        logger.info(
                            "webhook.delivered",
                            url=url,
                            status=resp.status_code,
                            attempt=attempt,
                        )
                        return

                    logger.warning(
                        "webhook.server_error",
                        url=url,
                        status=resp.status_code,
                        attempt=attempt,
                    )

            except httpx.HTTPError as exc:
                logger.warning(
                    "webhook.network_error",
                    url=url,
                    error=str(exc),
                    attempt=attempt,
                )

        logger.error(
            "webhook.delivery_failed",
            url=url,
            attempts=len(_RETRY_BACKOFF) + 1,
        )
