# backend/api/v1/monitoring/router.py
# TZ-11 SPLIT-3: Webhook receiver для Alertmanager + эндпоинты мониторинга.
# GET /monitoring/metrics — агрегированные метрики (CPU, RAM, Redis, сеть).
# GET /monitoring/nodes  — топология кластера (backend-сервисы как ноды).
# POST /monitoring/alerts — webhook для Alertmanager.
from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_tenant_db, require_permission
from backend.core.rbac import has_permission
from backend.database.redis_client import get_redis, get_redis_binary
from backend.schemas.fleet_coverage import FleetCoverageResponse
from backend.services.fleet_coverage import read_fleet_coverage
from backend.services.health_service import ComponentHealth, HealthService, get_health_service

logger = structlog.get_logger()

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/fleet-coverage", response_model=FleetCoverageResponse,
            summary="Tenant inventory, presence and independently timed VPN coverage")
async def get_fleet_coverage(
    current_user=require_permission("device:read"),
    db: AsyncSession = Depends(get_tenant_db),
    redis_conn=Depends(get_redis_binary),
) -> FleetCoverageResponse:
    return await read_fleet_coverage(db, redis_conn, current_user.org_id,
                                    vpn_allowed=has_permission(current_user.role, "vpn:read"))


class AlertAnnotations(BaseModel):
    summary: str = ""
    description: str = ""
    runbook: str = ""


class Alert(BaseModel):
    status: str                     # "firing" | "resolved"
    labels: dict[str, str] = {}
    annotations: AlertAnnotations = AlertAnnotations()


class AlertmanagerPayload(BaseModel):
    version: str = ""
    receiver: str = ""
    status: str = ""                # "firing" | "resolved"
    alerts: list[Alert] = []
    groupLabels: dict[str, str] = {}
    commonLabels: dict[str, str] = {}
    commonAnnotations: dict[str, str] = {}
    externalURL: str = ""


@router.post("/alerts")
async def receive_alerts(payload: AlertmanagerPayload) -> dict[str, Any]:
    """
    Webhook-ресивер для Alertmanager.

    Принимает алерты, логирует их структурированно.
    В будущем: трансляция в Fleet Events WebSocket (TZ-03 SPLIT-5).

    Alertmanager конфигурация:
        webhook_configs:
          - url: 'http://backend:8000/api/v1/monitoring/alerts'
    """
    for alert in payload.alerts:
        severity = alert.labels.get("severity", "unknown")
        alertname = alert.labels.get("alertname", "unknown")

        log_fn = logger.error if severity == "critical" else logger.warning
        if alert.status == "resolved":
            log_fn = logger.info

        log_fn(
            "alertmanager.alert",
            alertname=alertname,
            severity=severity,
            status=alert.status,
            summary=alert.annotations.summary,
            description=alert.annotations.description,
            labels=alert.labels,
        )

        # TODO (TZ-03 SPLIT-5): транслировать в Fleet Events WebSocket
        # await events_publisher.emit(FleetEvent(
        #     event_type=EventType.ALERT_TRIGGERED,
        #     org_id="system",
        #     payload={
        #         "alertname": alertname,
        #         "severity": severity,
        #         "status": alert.status,
        #         "summary": alert.annotations.summary,
        #     },
        # ))

    logger.info(
        "alertmanager.batch_processed",
        total=len(payload.alerts),
        status=payload.status,
        receiver=payload.receiver,
    )

    return {"status": "ok", "processed": len(payload.alerts)}


# ── GET /monitoring/metrics — реальные метрики системы ──────────────────────

_BOOT_TIME = time.monotonic()


@router.get("/metrics", summary="Агрегированные метрики инфраструктуры")
async def get_monitoring_metrics(
    redis_conn=Depends(get_redis),
    _principal=require_permission("monitoring:read"),
) -> dict[str, Any]:
    """
    Возвращает CPU, RAM, Redis-статистику и данные о сети.
    Load average не является CPU utilization и публикуется отдельно.
    История не хранится этим endpoint и поэтому намеренно пуста.
    """
    redis_status = "UNKNOWN"
    redis_ops = None
    redis_memory = None
    redis_clients = None
    if redis_conn is not None:
        try:
            redis_status = "HEALTHY" if await redis_conn.ping() else "CRITICAL"
        except Exception as exc:
            redis_status = "CRITICAL"
            logger.warning("monitoring.redis_ping_failed", error=str(exc))
        if redis_status == "HEALTHY":
            try:
                info_stats = await redis_conn.info(section="stats")
                info_memory = await redis_conn.info(section="memory")
                info_clients = await redis_conn.info(section="clients")
                redis_ops = info_stats.get("instantaneous_ops_per_sec")
                used_bytes = info_memory.get("used_memory")
                redis_memory = f"{int(used_bytes) / (1024 * 1024):.1f} MB" if used_bytes is not None else None
                redis_clients = info_clients.get("connected_clients")
            except Exception as exc:
                logger.warning("monitoring.redis_info_failed", error=str(exc))
    memory_used, memory_limit = _read_container_memory_bytes()
    tx_bytes, rx_bytes = _read_network_counters()

    return {
        "cpu": {"linuxLoad1mPerCpu": _read_linux_load_per_cpu(), "history": []},
        "ram": {"currentBytes": memory_used, "totalBytes": memory_limit, "history": []},
        "redis": {
            "status": redis_status,
            "ops": redis_ops,
            "memory": redis_memory,
            "clients": redis_clients,
        },
        "network": {"txTotalBytes": tx_bytes, "rxTotalBytes": rx_bytes, "activeTunnels": None},
        "observedAt": datetime.now(timezone.utc).isoformat(),
    }


# ── GET /monitoring/nodes — топология кластера ──────────────────────────────

@router.get("/nodes", summary="Топология кластера (список нод)")
async def get_monitoring_nodes(
    health_svc: HealthService = Depends(get_health_service),
    _principal=require_permission("monitoring:read"),
) -> list[dict[str, Any]]:
    """
    Возвращает только backend и зависимости, для которых реально выполняется
    health probe. Worker и edge probes не настроены и не объявляются healthy.
    """
    uptime_sec = int(time.monotonic() - _BOOT_TIME)
    uptime_str = _format_uptime(uptime_sec)

    health = await health_svc.check_all()
    components = {component.name: component for component in health.components}
    disk = components.get("disk")

    def dependency_node(
        node_id: str,
        name: str,
        node_type: str,
        component: ComponentHealth | None,
    ) -> dict[str, Any]:
        return {
            "id": node_id,
            "name": name,
            "type": node_type,
            "cpu": None,
            "ram": None,
            "disk": component.details.get("usage_percent") if component else None,
            "status": _health_status(component.status) if component else "UNKNOWN",
            "uptime": uptime_str,
            "latencyMs": component.latency_ms if component else None,
            "details": component.details if component else {"reason": "Health probe unavailable"},
        }

    return [
        {
            "id": "backend-api-responder-1",
            "name": "Backend API responder",
            "type": "API",
            "cpu": None,
            "ram": None,
            "disk": None,
            "status": "HEALTHY",  # this request reached and executed inside the API
            "uptime": uptime_str,
            "latencyMs": None,
            "details": {"probe": "HTTP request served"},
        },
        dependency_node("postgres-db-1", "PostgreSQL", "DB", components.get("postgresql")),
        dependency_node("redis-cache-1", "Redis", "CACHE", components.get("redis")),
        dependency_node("backend-disk-1", "Backend filesystem", "DISK", disk),
    ]


# ── Вспомогательные функции (Linux /proc, fallback) ─────────────────────────

def _read_linux_load_per_cpu() -> float | None:
    """Read Linux 1-minute host load per reported logical CPU, not CPU utilization."""
    try:
        with open("/proc/loadavg") as f:
            load_1m = float(f.read().split()[0])
        cpu_count = os.cpu_count() or 1
        if cpu_count < 1 or not math.isfinite(load_1m) or load_1m < 0:
            return None
        return round(load_1m / cpu_count, 3)
    except Exception:
        return None


def _read_container_memory_bytes() -> tuple[int | None, int | None]:
    """Read cgroup memory usage/limit; host-wide /proc is not a container metric."""
    candidates = (
        ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max"),
        ("/sys/fs/cgroup/memory/memory.usage_in_bytes", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    )
    for usage_path, limit_path in candidates:
        try:
            with open(usage_path) as usage_file, open(limit_path) as limit_file:
                usage_text = usage_file.read().strip()
                limit_text = limit_file.read().strip()
            usage = int(usage_text)
            if usage < 0:
                continue
            if limit_text == "max":
                return usage, None
            limit = int(limit_text)
            if limit >= 1 << 60:  # cgroup v1 uses a huge sentinel for no limit
                return usage, None
            if limit > 0 and usage <= limit:
                return usage, limit
        except (OSError, ValueError):
            continue
    return None, None


def _read_network_counters() -> tuple[int | None, int | None]:
    """Return cumulative RX/TX bytes for non-loopback interfaces, not bandwidth."""
    try:
        rx_total = 0
        tx_total = 0
        found = False
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                interface, counters = line.split(":", 1)
                if interface.strip() == "lo":
                    continue
                values = counters.split()
                if len(values) < 9:
                    continue
                rx_total += int(values[0])
                tx_total += int(values[8])
                found = True
        return (tx_total, rx_total) if found else (None, None)
    except (OSError, ValueError):
        return None, None


def _health_status(status: str) -> str:
    return {"ok": "HEALTHY", "degraded": "WARNING", "down": "CRITICAL"}.get(
        status, "UNKNOWN"
    )


def _format_uptime(seconds: int) -> str:
    """Форматирует секунды в человекочитаемый uptime."""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
