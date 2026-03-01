# SPLIT-5 — Health Checks (Endpoints для проверки состояния)

**ТЗ-родитель:** TZ-11-Monitoring  
**Ветка:** `stage/11-monitoring`  
**Задача:** `SPHERE-060`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** —
**Зависит от:** TZ-11 SPLIT-1 (Prometheus)

---

## Цель Сплита

Health check endpoints для Docker healthcheck, load balancer и Kubernetes readiness/liveness probes. Проверяют: PostgreSQL, Redis, WebSocket subsystem, VPN Router.

---

## Шаг 1 — Health Check Service

```python
# backend/services/health_service.py
import asyncio
import time
from datetime import datetime, timezone
from pydantic import BaseModel
from sqlalchemy import text

import structlog

logger = structlog.get_logger()


class ComponentHealth(BaseModel):
    name: str
    status: str           # "ok" | "degraded" | "down"
    latency_ms: float     # время проверки
    details: dict = {}


class SystemHealth(BaseModel):
    status: str           # "healthy" | "degraded" | "unhealthy"
    version: str
    uptime_seconds: float
    timestamp: str
    components: list[ComponentHealth]


_start_time = time.monotonic()


class HealthService:
    """
    Проверяет состояние всех зависимостей backend.
    Используется в /health, /healthz, /readyz endpoints.
    """
    
    def __init__(self, db_engine, redis, settings):
        self.db_engine = db_engine
        self.redis = redis
        self.settings = settings
    
    async def check_all(self) -> SystemHealth:
        """Полная проверка всех компонент (для /health)."""
        # FIX 11.1: БЫЛО — asyncio.gather без таймаута
        #   → Зависшее соединение к БД = /health зависнет навсегда
        #   → Kubernetes readiness probe timeout → pod restart loop
        # СТАЛО — каждый check обёрнут в wait_for(timeout=3.0)
        checks = await asyncio.gather(
            asyncio.wait_for(self._check_postgres(), timeout=3.0),
            asyncio.wait_for(self._check_redis(), timeout=3.0),
            asyncio.wait_for(self._check_disk(), timeout=3.0),
            return_exceptions=True,
        )
        
        components = []
        for check in checks:
            if isinstance(check, Exception):
                components.append(ComponentHealth(
                    name="unknown",
                    status="down",
                    latency_ms=0,
                    details={"error": str(check)},
                ))
            else:
                components.append(check)
        
        # Общий статус: если хотя бы один down → unhealthy
        if any(c.status == "down" for c in components):
            overall = "unhealthy"
        elif any(c.status == "degraded" for c in components):
            overall = "degraded"
        else:
            overall = "healthy"
        
        return SystemHealth(
            status=overall,
            version=self.settings.VERSION,
            uptime_seconds=time.monotonic() - _start_time,
            timestamp=datetime.now(timezone.utc).isoformat(),
            components=components,
        )
    
    async def check_liveness(self) -> bool:
        """Liveness probe: приложение живо? (не повисло)."""
        return True  # Если FastAPI отвечает — живо
    
    async def check_readiness(self) -> bool:
        """Readiness probe: приложение готово принимать трафик?"""
        try:
            pg = await self._check_postgres()
            redis = await self._check_redis()
            return pg.status != "down" and redis.status != "down"
        except Exception:
            return False
    
    async def _check_postgres(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            async with self.db_engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                row = result.scalar()
            latency = (time.perf_counter() - start) * 1000
            
            return ComponentHealth(
                name="postgresql",
                status="ok" if latency < 100 else "degraded",
                latency_ms=round(latency, 2),
                details={
                    "pool_size": self.db_engine.pool.size(),
                    "checked_out": self.db_engine.pool.checkedout(),
                },
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error("PostgreSQL health check failed", error=str(e))
            return ComponentHealth(
                name="postgresql",
                status="down",
                latency_ms=round(latency, 2),
                details={"error": str(e)},
            )
    
    async def _check_redis(self) -> ComponentHealth:
        start = time.perf_counter()
        try:
            pong = await self.redis.ping()
            info = await self.redis.info("memory")
            latency = (time.perf_counter() - start) * 1000
            
            used_memory_mb = info.get("used_memory", 0) / 1024 / 1024
            
            return ComponentHealth(
                name="redis",
                status="ok" if latency < 50 else "degraded",
                latency_ms=round(latency, 2),
                details={
                    "pong": pong,
                    "used_memory_mb": round(used_memory_mb, 2),
                    "connected_clients": info.get("connected_clients", 0),
                },
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error("Redis health check failed", error=str(e))
            return ComponentHealth(
                name="redis",
                status="down",
                latency_ms=round(latency, 2),
                details={"error": str(e)},
            )
    
    async def _check_disk(self) -> ComponentHealth:
        """Проверить свободное место на диске."""
        import shutil
        start = time.perf_counter()
        try:
            usage = shutil.disk_usage("/")
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            latency = (time.perf_counter() - start) * 1000
            
            return ComponentHealth(
                name="disk",
                status="ok" if free_gb > 5 else ("degraded" if free_gb > 1 else "down"),
                latency_ms=round(latency, 2),
                details={
                    "free_gb": round(free_gb, 2),
                    "total_gb": round(total_gb, 2),
                    "usage_percent": round((1 - usage.free / usage.total) * 100, 1),
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="disk",
                status="degraded",
                latency_ms=0,
                details={"error": str(e)},
            )
```

---

## Шаг 2 — Health Router

```python
# backend/api/v1/metrics/health_router.py
from fastapi import APIRouter, Response
from backend.services.health_service import HealthService, SystemHealth

router = APIRouter(tags=["health"])

@router.get("/health", response_model=SystemHealth)
async def health_check(health_svc: HealthService):
    """
    Полная проверка здоровья системы.
    Docker healthcheck + мониторинг дашборд.
    
    Возвращает:
      200 — healthy / degraded
      503 — unhealthy
    """
    result = await health_svc.check_all()
    
    if result.status == "unhealthy":
        return Response(
            content=result.model_dump_json(),
            media_type="application/json",
            status_code=503,
        )
    return result


@router.get("/healthz", status_code=200)
async def liveness():
    """
    Kubernetes liveness probe.
    Простейшая проверка — если FastAPI отвечает, процесс живой.
    Не проверяет зависимости (PostgreSQL, Redis).
    """
    return {"status": "alive"}


@router.get("/readyz")
async def readiness(health_svc: HealthService):
    """
    Kubernetes readiness probe.
    Проверяет: PostgreSQL + Redis доступны.
    503 → load balancer перестаёт слать трафик.
    """
    ready = await health_svc.check_readiness()
    if not ready:
        return Response(
            content='{"status": "not_ready"}',
            media_type="application/json",
            status_code=503,
        )
    return {"status": "ready"}
```

---

## Шаг 3 — Docker Healthcheck Integration

```yaml
# docker-compose.full.yml — backend сервис (уже описан в TZ-00 SPLIT-1):
# healthcheck:
#   test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]
#   interval: 30s
#   timeout: 10s
#   retries: 3
#   start_period: 15s
```

---

## Шаг 4 — Lifespan Integration

```python
# backend/api/v1/metrics/health_router.py — DI
from fastapi import Depends
from backend.database.engine import engine
from backend.core.redis import get_redis
from backend.core.config import settings

def get_health_service() -> HealthService:
    return HealthService(
        db_engine=engine,
        redis=get_redis(),
        settings=settings,
    )
```

---

## Стратегия тестирования

### Пример unit-теста

```python
async def test_health_check_healthy(mock_db_engine, mock_redis):
    """Все компоненты здоровы → status=healthy."""
    mock_redis.ping.return_value = True
    mock_redis.info.return_value = {"used_memory": 1024 * 1024, "connected_clients": 5}
    
    svc = HealthService(mock_db_engine, mock_redis, settings)
    result = await svc.check_all()
    
    assert result.status == "healthy"
    assert len(result.components) >= 2

async def test_health_check_postgres_down(mock_redis):
    """PostgreSQL недоступен → status=unhealthy."""
    mock_engine = AsyncMock()
    mock_engine.connect.side_effect = Exception("Connection refused")
    
    svc = HealthService(mock_engine, mock_redis, settings)
    result = await svc.check_all()
    
    assert result.status == "unhealthy"
    pg = next(c for c in result.components if c.name == "postgresql")
    assert pg.status == "down"

async def test_readiness_returns_503_when_redis_down(client, mock_redis):
    """Redis down → readiness probe возвращает 503."""
    mock_redis.ping.side_effect = Exception("Connection refused")
    
    resp = await client.get("/readyz")
    assert resp.status_code == 503
```

---

## Критерии готовности

- [ ] `GET /healthz` → 200 `{"status": "alive"}` (liveness, < 1ms)
- [ ] `GET /readyz` → 200/503 (readiness, проверяет PG + Redis)
- [ ] `GET /health` → полная диагностика с latency каждого компонента
- [ ] PG down → `/health` возвращает 503 + `{"status": "unhealthy"}`
- [ ] Redis down → `/readyz` возвращает 503
- [ ] Docker healthcheck использует `/healthz`
- [ ] Все health endpoints НЕ попадают в Prometheus метрики (METRICS_SKIP_PATHS)
- [ ] Uptime и версия включены в ответ `/health`
