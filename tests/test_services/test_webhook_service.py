# tests/test_services/test_webhook_service.py
# TZ-04 SPLIT-5: Unit-тесты для WebhookService (HTTP delivery с HMAC и retry).
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.services.webhook_service import WebhookService, _rate_limit_delay


def _mock_response(status_code: int = 200):
    return httpx.Response(status_code)


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
        """Terminal client errors stop after one attempt."""
        ctx, client = _make_client([_mock_response(404)])
        svc = WebhookService()

        with patch("httpx.AsyncClient", return_value=ctx):
            await svc.deliver("https://example.com/hook", {"event_type": "x"})

        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_deliver_5xx_then_success(self):
        """5xx на первой попытке, потом 200 — доставлено."""

        ctx, client = _make_client([_mock_response(503), _mock_response(200)])
        svc = WebhookService()
        with patch("httpx.AsyncClient", return_value=ctx) as factory, \
             patch("asyncio.sleep", AsyncMock()):
            await svc.deliver("https://example.com/hook", {"event_type": "retry_test"})

        factory.assert_called_once()
        assert client.post.call_count == 2

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
        assert client.post.call_count == 4

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


@pytest.mark.parametrize("status", [200, 201, 204, 299, 301, 302, 400, 401, 403, 404, 422])
async def test_only_2xx_is_acknowledged_and_terminal_responses_do_not_retry(status):
    ctx, client = _make_client([httpx.Response(status)])
    with patch("httpx.AsyncClient", return_value=ctx), \
         patch("backend.services.webhook_service.logger") as log, \
         patch("asyncio.sleep", AsyncMock()) as sleep:
        await WebhookService().deliver("https://receiver.test/hook", {"event_type": "task.done"})
    client.post.assert_awaited_once()
    sleep.assert_not_awaited()
    if 200 <= status < 300:
        log.info.assert_called_once()
        assert log.info.call_args.args == ("webhook.delivered",)
        log.error.assert_not_called()
    else:
        log.info.assert_not_called()
        assert log.warning.call_args.args == ("webhook.rejected",)
        assert log.error.call_args.kwargs["outcome"] == "rejected"
        assert log.error.call_args.kwargs["attempts"] == 1
        assert log.error.call_args.kwargs["status"] == status


@pytest.mark.parametrize("status,outcome", [(429, "rate_limited"), (500, "server_error"), (503, "server_error")])
async def test_retry_exhaustion_has_one_correlated_failure_receipt(status, outcome):
    ctx, client = _make_client([httpx.Response(status) for _ in range(4)])
    with patch("httpx.AsyncClient", return_value=ctx), \
         patch("backend.services.webhook_service.logger") as log, \
         patch("asyncio.sleep", AsyncMock()) as sleep:
        await WebhookService().deliver("https://receiver.test/hook", {"event_type": "task.done"})
    assert client.post.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [5, 30, 120]
    log.info.assert_not_called()
    log.error.assert_called_once()
    receipt = log.error.call_args.kwargs
    assert receipt == {"delivery_id": receipt["delivery_id"], "event_type": "task.done", "attempts": 4, "status": status, "outcome": outcome}
    assert all(call.kwargs["delivery_id"] == receipt["delivery_id"] for call in log.warning.call_args_list)
    assert log.warning.call_args.kwargs["retry_in_seconds"] is None


@pytest.mark.parametrize("value,expected", [("7", 7), ("99999", 120), ("0", 0), ("", 5), ("garbage", 5), ("-1", 5), ("9" * 129, 5)])
def test_retry_after_seconds_are_bounded_or_use_backoff(value, expected):
    assert _rate_limit_delay(httpx.Response(429, headers={"Retry-After": value}), 5) == expected


def test_retry_after_http_date():
    when = datetime.now(timezone.utc) + timedelta(seconds=40)
    delay = _rate_limit_delay(httpx.Response(429, headers={"Retry-After": format_datetime(when, usegmt=True)}), 5)
    assert 38 <= delay <= 40


async def test_rate_limit_then_success_reuses_signed_payload_and_delivery_id():
    # Real httpx encoding and response handling; no outbound network requests.
    requests = []
    def receive(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "7"}) if len(requests) == 1 else httpx.Response(204)
    client = httpx.AsyncClient(transport=httpx.MockTransport(receive))
    with patch("httpx.AsyncClient", return_value=client) as factory, \
         patch("backend.services.webhook_service.logger") as log, \
         patch("asyncio.sleep", AsyncMock()) as sleep:
        await WebhookService().deliver("https://receiver.test/hook", {"event_type": "task.done", "text": "Привет"}, "test-signing-key")
    assert len(requests) == 2
    assert requests[0].content == requests[1].content
    assert requests[0].headers == requests[1].headers
    signature = hmac.new(b"test-signing-key", requests[0].content, hashlib.sha256).hexdigest()
    assert requests[0].headers["X-Sphere-Signature"] == "sha256=" + signature
    assert factory.call_args.kwargs["follow_redirects"] is False
    sleep.assert_awaited_once_with(7)
    assert log.warning.call_args.args == ("webhook.rate_limited",)
    assert log.info.call_args.args == ("webhook.delivered",)
    log.error.assert_not_called()
    assert client.is_closed


async def test_cancellation_stops_delivery_and_closes_client():
    ctx, client = _make_client([asyncio.CancelledError()])
    with patch("httpx.AsyncClient", return_value=ctx), \
         patch("backend.services.webhook_service.logger") as log, \
         patch("asyncio.sleep", AsyncMock()) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await WebhookService().deliver("https://receiver.test/hook", {"event_type": "task.done"})
    client.post.assert_awaited_once()
    ctx.__aexit__.assert_awaited_once()
    sleep.assert_not_awaited()
    log.info.assert_not_called()
    log.error.assert_not_called()


async def test_transport_failure_receipt_does_not_expose_receiver_secrets():
    ctx, client = _make_client([httpx.ConnectError("https://receiver.test?token=do-not-log") for _ in range(4)])
    with patch("httpx.AsyncClient", return_value=ctx), \
         patch("backend.services.webhook_service.logger") as log, \
         patch("asyncio.sleep", AsyncMock()):
        await WebhookService().deliver("https://receiver.test?token=do-not-log", {"event_type": "task.done"})
    assert client.post.await_count == 4
    assert log.error.call_args.kwargs["outcome"] == "transport_error"
    assert log.error.call_args.kwargs["status"] is None
    assert "do-not-log" not in str(log.mock_calls)
    assert log.warning.call_args.kwargs["error_type"] == "ConnectError"


@pytest.mark.parametrize("status,accepted", [(200, True), (204, True), (403, False), (429, False), (503, False)])
async def test_n8n_receiver_contract_remains_separate_and_signed(status, accepted):
    from backend.services.n8n_webhook_service import N8nWebhookService

    requests = []
    def receive(request):
        requests.append(request)
        return httpx.Response(status)
    client = httpx.AsyncClient(transport=httpx.MockTransport(receive))
    hook = SimpleNamespace(id="contract-test", url="https://receiver.test/n8n", secret_hash="hash-test-key")
    with patch("httpx.AsyncClient", return_value=client):
        result = await N8nWebhookService()._attempt_delivery(hook, "task.done", {"task_id": "test"})
    assert result is accepted
    assert len(requests) == 1
    body = requests[0].content
    data = json.loads(body)
    assert data["event"] == "task.done" and data["data"] == {"task_id": "test"}
    assert isinstance(data["timestamp"], int)
    expected = hmac.new(b"hash-test-key", body, hashlib.sha256).hexdigest()
    assert requests[0].headers["X-Sphere-Signature"] == "sha256=" + expected
