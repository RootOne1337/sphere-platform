from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1.monitoring import router as monitoring
from backend.core.dependencies import get_current_user
from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.main import app
from backend.services.health_service import get_health_service


def _health(components):
    return SimpleNamespace(components=components)


def _component(name, status, *, details=None, latency_ms=2.5):
    return SimpleNamespace(
        name=name,
        status=status,
        details=details or {},
        latency_ms=latency_ms,
    )


@pytest.fixture
def restore_dependency_overrides():
    previous = app.dependency_overrides.copy()
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


async def _monitoring_request(path: str, *, role: str | None):
    async def user_for_role():
        return SimpleNamespace(role=role)

    async def no_database():
        yield None

    async def no_redis():
        return None

    async def empty_health_service():
        return SimpleNamespace(check_all=AsyncMock(return_value=_health([])))

    app.dependency_overrides[get_db] = no_database
    if role is not None:
        app.dependency_overrides[get_current_user] = user_for_role
    app.dependency_overrides[get_redis] = no_redis
    app.dependency_overrides[get_health_service] = empty_health_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/v1/monitoring/metrics",
    "/api/v1/monitoring/nodes",
])
async def test_monitoring_read_endpoints_require_authentication(path, restore_dependency_overrides):
    response = await _monitoring_request(path, role=None)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/v1/monitoring/metrics",
    "/api/v1/monitoring/nodes",
])
async def test_monitoring_read_endpoints_enforce_monitoring_permission(path, restore_dependency_overrides):
    response = await _monitoring_request(path, role="api_user")

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/v1/monitoring/metrics",
    "/api/v1/monitoring/nodes",
])
async def test_viewer_can_read_monitoring_endpoints(path, restore_dependency_overrides):
    response = await _monitoring_request(path, role="viewer")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_monitoring_nodes_report_probe_results_and_no_invented_resources():
    health_service = SimpleNamespace(
        check_all=AsyncMock(return_value=_health([
            _component("postgresql", "down", details={"error": "connection refused"}),
            _component("redis", "degraded", details={"pong": True}),
            _component("disk", "ok", details={"usage_percent": 42.0}),
        ]))
    )

    nodes = await monitoring.get_monitoring_nodes(health_service)
    by_id = {node["id"]: node for node in nodes}

    assert by_id["backend-api-responder-1"]["status"] == "HEALTHY"
    assert by_id["postgres-db-1"]["status"] == "CRITICAL"
    assert by_id["redis-cache-1"]["status"] == "WARNING"
    assert by_id["backend-disk-1"]["disk"] == 42.0
    assert all(node["cpu"] is None and node["ram"] is None for node in nodes)
    assert "task-worker-1" not in by_id
    assert "nginx-edge-1" not in by_id


@pytest.mark.asyncio
async def test_monitoring_metrics_are_measured_or_explicitly_unavailable(monkeypatch):
    redis = SimpleNamespace(
        ping=AsyncMock(return_value=True),
        info=AsyncMock(side_effect=[
            {"instantaneous_ops_per_sec": 17},
            {"used_memory": 2 * 1024 * 1024},
            {"connected_clients": 4},
        ]),
    )
    monkeypatch.setattr(monitoring, "_read_linux_load_per_cpu", lambda: 0.375)
    monkeypatch.setattr(monitoring, "_read_container_memory_bytes", lambda: (100, 500))
    monkeypatch.setattr(monitoring, "_read_network_counters", lambda: (2000, 1000))

    result = await monitoring.get_monitoring_metrics(redis)

    assert result["cpu"] == {"linuxLoad1mPerCpu": 0.375, "history": []}
    assert result["ram"] == {"currentBytes": 100, "totalBytes": 500, "history": []}
    assert result["redis"] == {
        "status": "HEALTHY",
        "ops": 17,
        "memory": "2.0 MB",
        "clients": 4,
    }
    assert result["network"] == {
        "txTotalBytes": 2000,
        "rxTotalBytes": 1000,
        "activeTunnels": None,
    }
    assert result["observedAt"].endswith("+00:00")


@pytest.mark.asyncio
async def test_monitoring_metrics_keep_redis_failure_explicit():
    redis = SimpleNamespace(ping=AsyncMock(side_effect=TimeoutError("redis timeout")))

    result = await monitoring.get_monitoring_metrics(redis)

    assert result["redis"] == {
        "status": "CRITICAL",
        "ops": None,
        "memory": None,
        "clients": None,
    }


def test_container_memory_without_limit_reports_usage_and_unknown_limit(monkeypatch):
    contents = {
        "/sys/fs/cgroup/memory.current": "2048\n",
        "/sys/fs/cgroup/memory.max": "max\n",
    }
    monkeypatch.setattr("builtins.open", lambda path, *args, **kwargs: io.StringIO(contents[path]))

    assert monitoring._read_container_memory_bytes() == (2048, None)


def test_linux_load_is_not_mislabeled_or_clamped_to_cpu_percent(monkeypatch):
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO("100.0 0 0 0/0 1\n"))
    monkeypatch.setattr(monitoring.os, "cpu_count", lambda: 4)

    assert monitoring._read_linux_load_per_cpu() == 25.0


def test_linux_load_failure_is_unavailable_not_zero(monkeypatch):
    def fail_open(*args, **kwargs):
        raise OSError("procfs unavailable")

    monkeypatch.setattr("builtins.open", fail_open)

    assert monitoring._read_linux_load_per_cpu() is None


def test_network_counters_sum_interfaces_and_exclude_loopback(monkeypatch):
    network = """Inter-| Receive | Transmit
 face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed
    lo: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0
  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0
  tun0: 3000 0 0 0 0 0 0 0 4000 0 0 0 0 0 0 0
"""
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(network))

    assert monitoring._read_network_counters() == (6000, 4000)


def test_unavailable_health_probe_is_not_reported_as_healthy():
    assert monitoring._health_status("ok") == "HEALTHY"
    assert monitoring._health_status("degraded") == "WARNING"
    assert monitoring._health_status("down") == "CRITICAL"
    assert monitoring._health_status("not-configured") == "UNKNOWN"
