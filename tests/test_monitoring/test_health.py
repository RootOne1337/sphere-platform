# tests/test_monitoring/test_health.py
"""
Unit-тесты для:
  - backend/services/health_service.py  (HealthService.check_all / check_readiness)
  - backend/api/v1/health/router.py     (/healthz, /readyz, /full endpoints)
  - backend/api/v1/monitoring/router.py (/monitoring/alerts webhook)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.services.health_service import HealthService


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_mock_engine(latency_ms: float = 10, raise_exc: Exception | None = None):
    """Создать мок SQLAlchemy AsyncEngine."""
    engine = MagicMock()
    pool = MagicMock()
    pool.size.return_value = 20
    pool.checkedout.return_value = 5
    engine.pool = pool

    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock()

    if raise_exc:
        engine.connect.side_effect = raise_exc
    else:
        engine.connect.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
        engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

    return engine


def _make_mock_redis(raise_exc: Exception | None = None):
    """Создать мок aioredis."""
    redis = AsyncMock()
    if raise_exc:
        redis.ping.side_effect = raise_exc
    else:
        redis.ping.return_value = True
        redis.info.return_value = {
            "used_memory": 50 * 1024 * 1024,  # 50 MB
            "connected_clients": 10,
        }
    return redis


# ── HealthService.check_all ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_all_healthy():
    """Все компоненты в норме → status=healthy."""
    svc = HealthService(
        db_engine=_make_mock_engine(),
        redis=_make_mock_redis(),
    )
    result = await svc.check_all()

    assert result.status == "healthy"
    assert result.version == "4.0.0"
    assert result.uptime_seconds >= 0
    assert len(result.components) == 3
    assert all(c.status in ("ok", "degraded") for c in result.components)


@pytest.mark.asyncio
async def test_check_all_postgres_down():
    """PostgreSQL недоступен → status=unhealthy."""
    svc = HealthService(
        db_engine=_make_mock_engine(raise_exc=ConnectionError("refused")),
        redis=_make_mock_redis(),
    )
    result = await svc.check_all()

    assert result.status == "unhealthy"
    pg = next(c for c in result.components if c.name == "postgresql")
    assert pg.status == "down"
    assert "error" in pg.details


@pytest.mark.asyncio
async def test_check_all_redis_down():
    """Redis недоступен → status=unhealthy."""
    svc = HealthService(
        db_engine=_make_mock_engine(),
        redis=_make_mock_redis(raise_exc=ConnectionError("refused")),
    )
    result = await svc.check_all()

    assert result.status == "unhealthy"
    rd = next(c for c in result.components if c.name == "redis")
    assert rd.status == "down"


@pytest.mark.asyncio
async def test_check_all_redis_none():
    """Redis=None (не инициализирован) → redis компонент down."""
    svc = HealthService(db_engine=_make_mock_engine(), redis=None)
    result = await svc.check_all()

    rd = next(c for c in result.components if c.name == "redis")
    assert rd.status == "down"
    assert "not initialized" in rd.details.get("error", "")


@pytest.mark.asyncio
async def test_check_all_timeout_handled():
    """Если компонент завис > 3s → возвращается ComponentHealth со статусом down."""

    async def _hang():
        await asyncio.sleep(999)

    engine = MagicMock()
    engine.connect.return_value.__aenter__ = AsyncMock(side_effect=_hang)
    engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

    svc = HealthService(db_engine=engine, redis=_make_mock_redis())
    result = await svc.check_all()
    # Хотя бы одна компонента упала
    assert result.status in ("unhealthy", "degraded")


# ── HealthService.check_readiness ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_readiness_ok():
    """PG + Redis доступны → True."""
    svc = HealthService(
        db_engine=_make_mock_engine(),
        redis=_make_mock_redis(),
    )
    assert await svc.check_readiness() is True


@pytest.mark.asyncio
async def test_check_readiness_pg_down():
    """PG недоступен → False."""
    svc = HealthService(
        db_engine=_make_mock_engine(raise_exc=ConnectionError()),
        redis=_make_mock_redis(),
    )
    assert await svc.check_readiness() is False


# ── HTTP endpoints ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def health_client():
    async with AsyncClient(
        transport=ASGITransport(app=__import__("backend.main", fromlist=["app"]).app),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_healthz_returns_200(health_client):
    resp = await health_client.get("/api/v1/health/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_healthz_fast_response(health_client):
    """Liveness probe должна отвечать без обращения к БД."""
    import time
    start = time.perf_counter()
    await health_client.get("/api/v1/health/healthz")
    duration = time.perf_counter() - start
    assert duration < 0.5  # Должна ответить за < 500ms


@pytest.mark.asyncio
async def test_readyz_503_when_db_down():
    """Если PostgreSQL недоступен — readyz должен вернуть 503."""
    from backend.services.health_service import get_health_service

    mock_svc = MagicMock()
    mock_svc.check_readiness = AsyncMock(return_value=False)

    from backend.main import app

    # Переопределяем DI для этого теста
    app.dependency_overrides[get_health_service] = lambda: mock_svc

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            resp = await client.get("/api/v1/health/readyz")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_readyz_200_when_healthy():
    """Если PG + Redis доступны — readyz возвращает 200."""
    from backend.services.health_service import get_health_service
    from backend.main import app

    mock_svc = MagicMock()
    mock_svc.check_readiness = AsyncMock(return_value=True)

    app.dependency_overrides[get_health_service] = lambda: mock_svc

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            resp = await client.get("/api/v1/health/readyz")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_full_health_503_when_unhealthy():
    """Если хотя бы одна компонента down — /full возвращает 503."""
    from backend.services.health_service import HealthService, SystemHealth, ComponentHealth, get_health_service
    from backend.main import app

    mock_svc = MagicMock()
    mock_svc.check_all = AsyncMock(return_value=SystemHealth(
        status="unhealthy",
        version="4.0.0",
        uptime_seconds=10.0,
        timestamp="2026-01-01T00:00:00Z",
        components=[
            ComponentHealth(name="postgresql", status="down", latency_ms=0, details={"error": "refused"}),
            ComponentHealth(name="redis", status="ok", latency_ms=2.0),
            ComponentHealth(name="disk", status="ok", latency_ms=0.1),
        ],
    ))

    app.dependency_overrides[get_health_service] = lambda: mock_svc

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            resp = await client.get("/api/v1/health/full")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


# ── Alert webhook ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alert_webhook_receives_firing_alert():
    """POST /api/v1/monitoring/alerts — корректный payload → 200."""
    from backend.main import app

    payload = {
        "version": "4",
        "receiver": "default",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "BackendDown", "severity": "critical"},
                "annotations": {
                    "summary": "Backend недоступен",
                    "description": "Test",
                    "runbook": "",
                },
            }
        ],
        "groupLabels": {"alertname": "BackendDown"},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.post("/api/v1/monitoring/alerts", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["processed"] == 1


@pytest.mark.asyncio
async def test_alert_webhook_empty_alerts():
    """Пустой список alerts — должен вернуть processed=0."""
    from backend.main import app

    payload = {
        "version": "4",
        "receiver": "default",
        "status": "resolved",
        "alerts": [],
        "groupLabels": {},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.post("/api/v1/monitoring/alerts", json=payload)

    assert resp.status_code == 200
    assert resp.json()["processed"] == 0
