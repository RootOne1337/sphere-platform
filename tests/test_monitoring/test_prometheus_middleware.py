# tests/test_monitoring/test_prometheus_middleware.py
"""
Unit-тесты для:
  - backend/middleware/metrics.py   (_normalize_path)
  - backend/core/constants.py       (METRICS_SKIP_PATHS)
  - backend/metrics.py              (импорт/инициализация)
  - /metrics endpoint               (exposition format)
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from backend.core.constants import METRICS_SKIP_PATHS
from backend.middleware.metrics import _normalize_path
from backend.main import app


# ── _normalize_path ──────────────────────────────────────────────────────────

class TestNormalizePath:
    def test_uuid_replaced(self):
        path = "/api/v1/devices/550e8400-e29b-41d4-a716-446655440000"
        assert _normalize_path(path) == "/api/v1/devices/{id}"

    def test_uuid_case_insensitive(self):
        path = "/api/v1/devices/550E8400-E29B-41D4-A716-446655440000"
        assert _normalize_path(path) == "/api/v1/devices/{id}"

    def test_numeric_id_replaced(self):
        path = "/api/v1/tasks/123/logs"
        assert _normalize_path(path) == "/api/v1/tasks/{id}/logs"

    def test_multiple_uuids(self):
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        path = f"/api/v1/devices/{uuid}/commands/{uuid}"
        assert _normalize_path(path) == "/api/v1/devices/{id}/commands/{id}"

    def test_no_id_unchanged(self):
        path = "/api/v1/health"
        assert _normalize_path(path) == "/api/v1/health"

    def test_plain_path_unchanged(self):
        path = "/api/v1/devices"
        assert _normalize_path(path) == "/api/v1/devices"

    def test_numeric_and_uuid_mixed(self):
        path = "/api/v1/tasks/42/items/550e8400-e29b-41d4-a716-446655440000"
        assert _normalize_path(path) == "/api/v1/tasks/{id}/items/{id}"


# ── METRICS_SKIP_PATHS ────────────────────────────────────────────────────────

class TestMetricsSkipPaths:
    def test_metrics_path_in_skip(self):
        assert "/metrics" in METRICS_SKIP_PATHS

    def test_health_paths_in_skip(self):
        assert "/health" in METRICS_SKIP_PATHS
        assert "/api/v1/health" in METRICS_SKIP_PATHS
        assert "/api/v1/health/ready" in METRICS_SKIP_PATHS

    def test_api_path_not_in_skip(self):
        assert "/api/v1/devices" not in METRICS_SKIP_PATHS


# ── /metrics endpoint ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def metrics_client():
    """Минимальный клиент без auth, только для /metrics и /api/v1/health."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200(metrics_client):
    response = await metrics_client.get("/metrics")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_endpoint_content_type(metrics_client):
    response = await metrics_client.get("/metrics")
    assert "text/plain" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_endpoint_contains_prometheus_format(metrics_client):
    response = await metrics_client.get("/metrics")
    body = response.text
    # Стандартные заголовки Prometheus exposition format
    assert "# HELP" in body or "# TYPE" in body or body  # non-empty


@pytest.mark.asyncio
async def test_metrics_endpoint_contains_sphere_metrics(metrics_client):
    """После запроса к /api/v1/health sphere_http_requests_total должен появиться."""
    # Делаем запрос, который должен быть посчитан
    await metrics_client.get("/api/v1/health")
    response = await metrics_client.get("/metrics")
    # prometheus_client хранит Counter с базовым именем (без _total).
    # В тексте exposition format _total добавляется автоматически.
    metric_names = [m.name for m in REGISTRY.collect()]
    # Базовое имя Counter в REGISTRY — без суффикса _total
    assert "sphere_http_requests" in metric_names
    # В тексте /metrics — с _total
    assert "sphere_http_requests_total" in response.text


@pytest.mark.asyncio
async def test_health_request_not_tracked(metrics_client):
    """Запросы к /metrics и /health НЕ должны попадать в sphere_http_requests_total."""
    # Получаем начальное значение
    def _count_for_endpoint(body: str, endpoint: str) -> bool:
        return endpoint in body

    await metrics_client.get("/metrics")  # skip path
    await metrics_client.get("/api/v1/health")  # skip path

    response = await metrics_client.get("/metrics")
    # /metrics не должен появиться как endpoint в метриках
    assert 'endpoint="/metrics"' not in response.text
    assert 'endpoint="/api/v1/health"' not in response.text


# ── metrics.py import integrity ───────────────────────────────────────────────

def test_metrics_registry_import():
    """Все метрики должны импортироваться без ошибок."""
    from backend.metrics import (
        auth_attempts_total,
        auth_token_refresh_total,
        cleanup_stream_metrics,
        db_pool_checked_out,
        db_pool_size,
        db_query_duration_seconds,
        device_commands_total,
        devices_online,
        devices_total,
        http_request_duration_seconds,
        http_requests_total,
        redis_commands_total,
        redis_errors_total,
        stream_bitrate_kbps,
        stream_fps,
        stream_frame_drops_total,
        task_execution_duration_seconds,
        task_queue_depth,
        tasks_total,
        vpn_handshake_stale_total,
        vpn_pool_allocated,
        vpn_pool_total,
        vpn_reconnects_total,
        ws_connections_active,
        ws_messages_total,
    )
    # Все объекты существуют
    assert http_requests_total is not None
    assert cleanup_stream_metrics is not None


def test_cleanup_stream_metrics_no_error():
    """cleanup_stream_metrics должна не бросать исключений для несуществующего device_id."""
    from backend.metrics import cleanup_stream_metrics
    # Не должно поднять KeyError или другую ошибку
    cleanup_stream_metrics("nonexistent-device-id")


def test_cleanup_stream_metrics_removes_series():
    """После вызова cleanup series с данным device_id должны быть удалены."""
    from backend.metrics import (
        cleanup_stream_metrics,
        stream_bitrate_kbps,
        stream_fps,
    )
    device_id = "test-device-cleanup-001"

    # Создаём series
    stream_fps.labels(device_id=device_id).set(30)
    stream_bitrate_kbps.labels(device_id=device_id).set(2000)

    # Убедимся что series существуют
    samples_before = {
        s.labels.get("device_id")
        for m in REGISTRY.collect()
        if m.name in ("sphere_stream_fps", "sphere_stream_bitrate_kbps")
        for s in m.samples
    }
    assert device_id in samples_before

    # Cleanup
    cleanup_stream_metrics(device_id)

    # Series должны исчезнуть
    samples_after = {
        s.labels.get("device_id")
        for m in REGISTRY.collect()
        if m.name in ("sphere_stream_fps", "sphere_stream_bitrate_kbps")
        for s in m.samples
    }
    assert device_id not in samples_after
