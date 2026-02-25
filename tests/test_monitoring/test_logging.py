# tests/test_monitoring/test_logging.py
"""
Unit-тесты для:
  - backend/core/logging_config.py   (setup_logging, JSON/console mode)
  - backend/middleware/request_id.py (X-Request-ID header, structlog context)
  - backend/middleware/logging_context.py (bind_user_context)
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
import structlog
from httpx import ASGITransport, AsyncClient

from backend.main import app

# ── setup_logging ─────────────────────────────────────────────────────────────

def test_setup_logging_no_error():
    """setup_logging() не должна бросать исключений."""
    from backend.core.logging_config import setup_logging
    setup_logging()  # повторный вызов — идемпотентен


def test_root_logger_has_handler_after_setup():
    """После setup_logging() у root logger должен быть хотя бы один handler."""
    from backend.core.logging_config import setup_logging
    setup_logging()
    root = logging.getLogger()
    assert len(root.handlers) >= 1


def test_structlog_produces_output(capsys):
    """structlog logger должен производить хоть какой-то вывод."""
    from backend.core.logging_config import setup_logging
    setup_logging()
    logger = structlog.get_logger("test")
    structlog.contextvars.clear_contextvars()
    logger.info("test_event", key="value")
    captured = capsys.readouterr()
    assert "test_event" in captured.out


def test_context_vars_appear_in_log(capsys):
    """ContextVar (request_id) должен автоматически добавляться в лог."""
    from backend.core.logging_config import setup_logging
    setup_logging()
    logger = structlog.get_logger("test")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="test-req-123")
    logger.info("ctx_test")
    captured = capsys.readouterr()
    assert "test-req-123" in captured.out


# ── RequestIdMiddleware ───────────────────────────────────────────────────────

@pytest.fixture
def anon_client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_request_id_header_added_to_response():
    """Ответ должен содержать X-Request-ID header."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/api/v1/health")
    assert "x-request-id" in resp.headers


@pytest.mark.asyncio
async def test_request_id_preserved_from_client():
    """Если клиент передаёт X-Request-ID — он должен вернуться в ответе."""
    custom_id = "my-trace-abc"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get(
            "/api/v1/health",
            headers={"X-Request-ID": custom_id},
        )
    assert resp.headers.get("x-request-id") == custom_id


@pytest.mark.asyncio
async def test_request_id_generated_when_absent():
    """Если X-Request-ID не передан — должен быть сгенерирован непустой ID."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/api/v1/health")
    assert resp.headers.get("x-request-id", "") != ""


# ── bind_user_context ─────────────────────────────────────────────────────────

def test_bind_user_context_binds_fields():
    """bind_user_context должна добавлять org_id, user_id, role в structlog context."""
    import uuid

    from backend.middleware.logging_context import bind_user_context

    user = MagicMock()
    user.org_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    user.id = uuid.UUID("660e9400-f39c-51e5-b826-557766550000")
    user.role = "org_admin"

    structlog.contextvars.clear_contextvars()
    bind_user_context(user)

    ctx = structlog.contextvars.get_contextvars()
    assert ctx["org_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert ctx["user_id"] == "660e9400-f39c-51e5-b826-557766550000"
    assert ctx["role"] == "org_admin"
