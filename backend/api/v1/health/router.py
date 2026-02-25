# backend/api/v1/health/router.py
# TZ-11 SPLIT-5: Health check endpoints.
# Auto-discovered → routes зарегистрированы с prefix /api/v1/health/...
#
# Итоговые пути:
#   GET /api/v1/health/healthz  — liveness probe  (Kubernetes, Docker healthcheck)
#   GET /api/v1/health/readyz   — readiness probe (load balancer)
#   GET /api/v1/health/full     — полная диагностика с latency компонент
#
# NOTE: /api/v1/health и /api/v1/health/ready определены в main.py (TZ-00).
# Новые sub-routes не конфликтуют.
from fastapi import APIRouter, Depends, Response

from backend.services.health_service import HealthService, SystemHealth, get_health_service

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/healthz", status_code=200)
async def liveness():
    """
    Kubernetes liveness probe / Docker healthcheck.

    Просто проверяет, что FastAPI процесс жив и отвечает.
    НЕ проверяет зависимости (PostgreSQL, Redis) — это readyz.

    Docker healthcheck (docker-compose):
        healthcheck:
          test: ["CMD", "wget", "-q", "--spider", "http://localhost:8000/api/v1/health/healthz"]
          interval: 30s
          timeout: 5s
          retries: 3
    """
    return {"status": "alive", "version": "4.0.0"}


@router.get("/readyz")
async def readiness(health_svc: HealthService = Depends(get_health_service)):
    """
    Kubernetes readiness probe.

    Возвращает 200 только если PostgreSQL + Redis доступны.
    503 → load balancer перестаёт направлять трафик к этому поду.
    """
    ready = await health_svc.check_readiness()
    if not ready:
        return Response(
            content='{"status":"not_ready"}',
            media_type="application/json",
            status_code=503,
        )
    return {"status": "ready"}


@router.get("/full", response_model=SystemHealth)
async def full_health(health_svc: HealthService = Depends(get_health_service)):
    """
    Полная диагностика: PostgreSQL, Redis, disk — с latency каждого компонента.

    200 — healthy / degraded (предупреждение, но работаем)
    503 — unhealthy (критическая зависимость упала)

    Grafana health dashboard + мониторинг дашборд используют этот endpoint.
    """
    result = await health_svc.check_all()

    if result.status == "unhealthy":
        return Response(
            content=result.model_dump_json(),
            media_type="application/json",
            status_code=503,
        )
    return result
