# backend/services/health_service.py
# TZ-11 SPLIT-5: Диагностика здоровья всех компонент платформы.
# Используется в /api/v1/health/healthz (liveness), /readyz (readiness), /full (diagnostics).
#
# FIX 11.1: БЫЛО — asyncio.gather без таймаута
#   → зависшее соединение к БД = /health зависнет навсегда
#   → Kubernetes readiness probe timeout → pod restart loop
# СТАЛО — каждый check обёрнут в asyncio.wait_for(timeout=3.0)
import asyncio
import shutil
import time
from datetime import datetime, timezone

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

_start_time = time.monotonic()

# Версия приложения — единый источник истины
APP_VERSION = "4.0.0"


class ComponentHealth(BaseModel):
    name: str
    status: str             # "ok" | "degraded" | "down"
    latency_ms: float
    details: dict = {}


class SystemHealth(BaseModel):
    status: str             # "healthy" | "degraded" | "unhealthy"
    version: str
    uptime_seconds: float
    timestamp: str
    components: list[ComponentHealth]


class HealthService:
    """
    Проверяет состояние всех зависимостей backend.
    Используется в /api/v1/health/ endpoints.
    """

    def __init__(self, db_engine, redis):
        self.db_engine = db_engine
        self.redis = redis

    async def check_all(self) -> SystemHealth:
        """Полная проверка всех компонент (для /api/v1/health/full)."""
        results = await asyncio.gather(
            asyncio.wait_for(self._check_postgres(), timeout=3.0),
            asyncio.wait_for(self._check_redis(), timeout=3.0),
            asyncio.wait_for(self._check_disk(), timeout=3.0),
            return_exceptions=True,
        )

        components: list[ComponentHealth] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                name = ("postgresql", "redis", "disk")[i]
                components.append(ComponentHealth(
                    name=name,
                    status="down",
                    latency_ms=0,
                    details={"error": str(result)},
                ))
            else:
                components.append(result)  # type: ignore[arg-type]

        if any(c.status == "down" for c in components):
            overall = "unhealthy"
        elif any(c.status == "degraded" for c in components):
            overall = "degraded"
        else:
            overall = "healthy"

        return SystemHealth(
            status=overall,
            version=APP_VERSION,
            uptime_seconds=round(time.monotonic() - _start_time, 2),
            timestamp=datetime.now(timezone.utc).isoformat(),
            components=components,
        )

    async def check_readiness(self) -> bool:
        """Readiness probe: PostgreSQL + Redis доступны?"""
        try:
            pg, rd = await asyncio.gather(
                asyncio.wait_for(self._check_postgres(), timeout=3.0),
                asyncio.wait_for(self._check_redis(), timeout=3.0),
                return_exceptions=True,
            )
            pg_ok = not isinstance(pg, Exception) and pg.status != "down"
            rd_ok = not isinstance(rd, Exception) and rd.status != "down"
            return pg_ok and rd_ok
        except Exception:
            return False

    # ── Component checks ──────────────────────────────────────────────────────

    async def _check_postgres(self) -> ComponentHealth:
        from sqlalchemy import text

        start = time.perf_counter()
        try:
            async with self.db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            latency = (time.perf_counter() - start) * 1000

            pool = self.db_engine.pool
            status = "ok" if latency < 100 else "degraded"

            return ComponentHealth(
                name="postgresql",
                status=status,
                latency_ms=round(latency, 2),
                details={
                    "pool_size": pool.size(),
                    "checked_out": pool.checkedout(),
                },
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            logger.error("health.postgres_check_failed", error=str(exc))
            return ComponentHealth(
                name="postgresql",
                status="down",
                latency_ms=round(latency, 2),
                details={"error": str(exc)},
            )

    async def _check_redis(self) -> ComponentHealth:
        start = time.perf_counter()

        if self.redis is None:
            return ComponentHealth(
                name="redis",
                status="down",
                latency_ms=0,
                details={"error": "redis client not initialized"},
            )

        try:
            pong = await self.redis.ping()
            latency = (time.perf_counter() - start) * 1000

            details: dict = {"pong": bool(pong)}
            try:
                info = await self.redis.info("memory")
                details["used_memory_mb"] = round(
                    info.get("used_memory", 0) / 1024 / 1024, 2
                )
                details["connected_clients"] = info.get("connected_clients", 0)
            except Exception:
                pass  # info() may not be available in all Redis configurations

            return ComponentHealth(
                name="redis",
                status="ok" if latency < 50 else "degraded",
                latency_ms=round(latency, 2),
                details=details,
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            logger.error("health.redis_check_failed", error=str(exc))
            return ComponentHealth(
                name="redis",
                status="down",
                latency_ms=round(latency, 2),
                details={"error": str(exc)},
            )

    async def _check_disk(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            usage = shutil.disk_usage("/")
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            latency = (time.perf_counter() - start) * 1000

            if free_gb > 5:
                status = "ok"
            elif free_gb > 1:
                status = "degraded"
            else:
                status = "down"

            return ComponentHealth(
                name="disk",
                status=status,
                latency_ms=round(latency, 2),
                details={
                    "free_gb": round(free_gb, 2),
                    "total_gb": round(total_gb, 2),
                    "usage_percent": round((1 - usage.free / usage.total) * 100, 1),
                },
            )
        except Exception as exc:
            return ComponentHealth(
                name="disk",
                status="degraded",
                latency_ms=0,
                details={"error": str(exc)},
            )


# ── Dependency factory ────────────────────────────────────────────────────────

def get_health_service() -> HealthService:
    """
    FastAPI Depends factory.
    Импортирует engine и redis лениво (они инициализируются при lifespan).
    """
    from backend.database.engine import engine
    from backend.database.redis_client import redis

    return HealthService(db_engine=engine, redis=redis)
