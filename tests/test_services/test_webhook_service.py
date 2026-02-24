# tests/test_services/test_webhook_service.py
# TZ-04 SPLIT-5: Unit-тесты для WebhookService (HTTP delivery с HMAC и retry).
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.webhook_service import WebhookService


def _mock_response(status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    return resp


def _make_client(responses: list):
    """Возвращает мок httpx.AsyncClient.post с заданными ответами."""
    client_mock = AsyncMock()
    client_mock.post = AsyncMock(side_effect=responses)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=client_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client_mock


class TestDeliver:
    @pytest.mark.asyncio
    async def test_deliver_2xx_success(self):
        """200 ответ — доставлено с первой попытки, без retry."""
        ctx, client = _make_client([_mock_response(200)])
        svc = WebhookService()

        with patch("httpx.AsyncClient", return_value=ctx):
            await svc.deliver("https://example.com/hook", {"event_type": "task.done"})

        client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_with_hmac_signature(self):
        """При наличии secret — заголовок X-Sphere-Signature содержит sha256=<hmac>."""
        ctx, client = _make_client([_mock_response(200)])
        svc = WebhookService()
        secret = "my-webhook-secret"
        payload = {"event_type": "device.online", "device_id": "abc"}

        with patch("httpx.AsyncClient", return_value=ctx):
            await svc.deliver("https://example.com/hook", payload, secret=secret)

        call_kwargs = client.post.call_args[1]
        headers = call_kwargs["headers"]
        assert "X-Sphere-Signature" in headers
        sig_header = headers["X-Sphere-Signature"]
        assert sig_header.startswith("sha256=")

        # Верифицируем HMAC
        body = json.dumps(payload, default=str, ensure_ascii=False).encode()
        expected_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert sig_header == f"sha256={expected_sig}"

    @pytest.mark.asyncio
    async def test_deliver_without_secret_no_signature_header(self):
        ctx, client = _make_client([_mock_response(200)])
        svc = WebhookService()

        with patch("httpx.AsyncClient", return_value=ctx):
            await svc.deliver("https://example.com/hook", {"event_type": "ping"})

        headers = client.post.call_args[1]["headers"]
        assert "X-Sphere-Signature" not in headers

    @pytest.mark.asyncio
    async def test_deliver_4xx_no_retry(self):
        """4xx — клиентская ошибка, не ретраить (status < 500)."""
        ctx, client = _make_client([_mock_response(404)])
        svc = WebhookService()

        with patch("httpx.AsyncClient", return_value=ctx):
            await svc.deliver("https://example.com/hook", {"event_type": "x"})

        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_deliver_5xx_then_success(self):
        """5xx на первой попытке, потом 200 — доставлено."""

        ctx1, client1 = _make_client([_mock_response(503)])
        ctx2, client2 = _make_client([_mock_response(200)])

        call_count = 0
        clients = [ctx1, ctx2]

        def make_client(*a, **kw):
            nonlocal call_count
            c = clients[call_count]
            call_count += 1
            return c

        svc = WebhookService()
        with patch("httpx.AsyncClient", side_effect=make_client), \
             patch("asyncio.sleep", AsyncMock()):
            await svc.deliver("https://example.com/hook", {"event_type": "retry_test"})

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_deliver_network_error_retries(self):
        """Сетевая ошибка → retry; если все попытки провалились, не кидает исключение."""
        import httpx

        ctx, client = _make_client([
            httpx.NetworkError("timeout"),
            httpx.NetworkError("timeout"),
            httpx.NetworkError("timeout"),
            httpx.NetworkError("timeout"),  # 4 попытки всего (0+3 retry)
        ])

        svc = WebhookService()

        with patch("httpx.AsyncClient", return_value=ctx), \
             patch("asyncio.sleep", AsyncMock()):
            # Не должен выбросить исключение
            await svc.deliver("https://example.com/hook", {"event_type": "fail"})

    @pytest.mark.asyncio
    async def test_event_type_header_set(self):
        ctx, client = _make_client([_mock_response(200)])
        svc = WebhookService()

        with patch("httpx.AsyncClient", return_value=ctx):
            await svc.deliver("https://h.com", {"event_type": "script.completed"})

        headers = client.post.call_args[1]["headers"]
        assert headers["X-Sphere-Event"] == "script.completed"

    @pytest.mark.asyncio
    async def test_delivery_id_header_set(self):
        ctx, client = _make_client([_mock_response(200)])
        svc = WebhookService()

        with patch("httpx.AsyncClient", return_value=ctx):
            await svc.deliver("https://h.com", {"event_type": "ping"})

        headers = client.post.call_args[1]["headers"]
        assert "X-Sphere-Delivery" in headers
        assert len(headers["X-Sphere-Delivery"]) == 16  # hex(8 bytes)
