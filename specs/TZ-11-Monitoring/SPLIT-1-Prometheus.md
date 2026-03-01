# SPLIT-1 — Prometheus Metrics (FastAPI + кастомные метрики)

**ТЗ-родитель:** TZ-11-Monitoring  
**Ветка:** `stage/11-monitoring`  
**Задача:** `SPHERE-056`  
**Исполнитель:** Backend/DevOps  
**Оценка:** 1 день  
**Блокирует:** TZ-11 SPLIT-2

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-11` — НЕ в `sphere-platform`.
> Ветка `stage/11-monitoring` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-11
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/11-monitoring
pwd                          # ОБЯЗАНT содержать: sphere-stage-11
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-11 stage/11-monitoring
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/11-monitoring` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/11-monitoring` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `infrastructure/monitoring/` | `backend/main.py` 🔴 |
| `backend/monitoring/` | `backend/core/` 🔴 |
| `backend/middleware/prometheus*` | `backend/database/` 🔴 |
| `backend/api/v1/metrics/` | `frontend/` (TZ-10) 🔴 |
| `tests/test_monitoring*` | `docker-compose*.yml` 🔴 |

---

## Цель Сплита

Выставить `/metrics` endpoint на FastAPI с 100+ метриками: HTTP latency, device states, WS connections, task queue depth, VPN pool, DB pool.

---

## Шаг 1 — Зависимости

```
prometheus-client==0.20.0
starlette-exporter==0.17.0
```

---

## Шаг 2 — Метрики реестр

```python
# backend/metrics.py
from prometheus_client import Counter, Histogram, Gauge, Summary

# --- HTTP ---
http_requests_total = Counter(
    "sphere_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
http_request_duration_seconds = Histogram(
    "sphere_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# --- WebSocket ---
ws_connections_active = Gauge("sphere_ws_connections_active", "Active WS connections", ["role"])
ws_messages_total = Counter("sphere_ws_messages_total", "WS messages", ["direction", "role"])

# --- Devices ---
devices_total = Gauge("sphere_devices_total", "Total registered devices", ["org_id"])
devices_online = Gauge("sphere_devices_online", "Online devices right now", ["org_id"])
device_commands_total = Counter(
    "sphere_device_commands_total",
    "Commands sent to devices",
    ["command_type", "status"],
)

# --- Tasks ---
task_queue_depth = Gauge("sphere_task_queue_depth", "Tasks waiting in queue")
tasks_total = Counter("sphere_tasks_total", "Total tasks", ["status"])
task_execution_duration_seconds = Histogram(
    "sphere_task_execution_duration_seconds",
    "Task execution time",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# --- VPN ---
vpn_pool_total = Gauge("sphere_vpn_pool_total", "Total VPN IPs")
vpn_pool_allocated = Gauge("sphere_vpn_pool_allocated", "Allocated VPN IPs")
vpn_reconnects_total = Counter("sphere_vpn_reconnects_total", "VPN reconnect events")
vpn_handshake_stale_total = Counter("sphere_vpn_handshake_stale_total", "Stale handshakes detected")

# --- Database ---
db_pool_size = Gauge("sphere_db_pool_size", "SQLAlchemy pool size")
db_pool_checked_out = Gauge("sphere_db_pool_checked_out", "Connections in use")
db_query_duration_seconds = Histogram(
    "sphere_db_query_duration_seconds",
    "DB query duration",
    ["query_name"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
)

# --- Redis ---
redis_commands_total = Counter("sphere_redis_commands_total", "Redis commands", ["command"])
redis_errors_total = Counter("sphere_redis_errors_total", "Redis errors")

# --- Streaming ---
# ⚠️ FIX: device_id — высокая кардинальность. При 10k устройств = 30k+ stale series навсегда.
# Решение: всегда вызывать cleanup_stream_metrics(device_id) при остановке стрима
# (TZ-05 SPLIT-3 StreamingManager.stop(), TZ-03 disconnect handler).
stream_fps = Gauge("sphere_stream_fps", "Current FPS per device", ["device_id"])
stream_bitrate_kbps = Gauge("sphere_stream_bitrate_kbps", "Stream bitrate", ["device_id"])
stream_frame_drops_total = Counter("sphere_stream_frame_drops_total", "Dropped frames", ["device_id"])


import contextlib

def cleanup_stream_metrics(device_id: str) -> None:
    """
    Удалить Prometheus time series устройства при завершении стрима.
    Без вызова этой функции series остаются навсегда (stale high-cardinality leak).
    
    Вызвать из:
      - TZ-05 SPLIT-3 StreamingManager.stop(device_id)
      - TZ-03 SPLIT-4 WebSocket disconnect handler
    """
    with contextlib.suppress(KeyError):
        stream_fps.remove(device_id)
        stream_bitrate_kbps.remove(device_id)
        stream_frame_drops_total.remove(device_id)

# --- Auth ---
auth_attempts_total = Counter("sphere_auth_attempts_total", "Auth attempts", ["status"])
auth_token_refresh_total = Counter("sphere_auth_token_refresh_total", "Token refreshes")
```

---

## Шаг 3 — Prometheus Middleware

```python
# backend/middleware/metrics.py
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from backend.metrics import http_requests_total, http_request_duration_seconds

# LOW-6: импорт из backend/core/constants.py — без дублирования в TZ-01 и других middleware
# backend/core/constants.py должен содержать: METRICS_SKIP_PATHS = {"/metrics", "/health", "/healthz", "/favicon.ico"}
from backend.core.constants import METRICS_SKIP_PATHS

class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        
        if path in METRICS_SKIP_PATHS:
            return await call_next(request)
        
        # Нормализуем path для label (убираем UUID-сегменты)
        normalized = _normalize_path(path)
        
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        
        http_requests_total.labels(
            method=request.method,
            endpoint=normalized,
            status_code=str(response.status_code),
        ).inc()
        
        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=normalized,
        ).observe(duration)
        
        return response


def _normalize_path(path: str) -> str:
    """
    /api/v1/devices/550e8400... → /api/v1/devices/{id}
    /api/v1/tasks/123/logs     → /api/v1/tasks/{id}/logs
    """
    import re
    # UUID
    path = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '/{id}', path)
    # Числа
    path = re.sub(r'/\d+', '/{id}', path)
    return path
```

---

## Шаг 4 — Подключение в main.py

```python
# backend/main.py
from starlette_exporter import PrometheusMiddleware as StarlettePrometheus, handle_metrics
from backend.middleware.metrics import PrometheusMiddleware

app = FastAPI(title="Sphere Platform API")

# Наш custom middleware (порядок важен: сначала timing)
app.add_middleware(PrometheusMiddleware)

# /metrics endpoint
app.add_route("/metrics", handle_metrics)
```

---

## Шаг 5 — DB Pool Metrics Collector

```python
# backend/db/pool_metrics.py
import asyncio
from backend.metrics import db_pool_size, db_pool_checked_out
from backend.db import engine  # AsyncEngine

async def collect_pool_metrics():
    while True:
        pool = engine.pool
        db_pool_size.set(pool.size())
        db_pool_checked_out.set(pool.checkedout())
        await asyncio.sleep(15)

# FIX 11.3: БЫЛО — collect_pool_metrics() определена, но НИГДЕ не запущена!
#   → Gauges db_pool_size и db_pool_checked_out всегда = 0
#   → Grafana дашборд "DB Pool" — пустые графики
# СТАЛО — запуск через lifespan
from backend.core.lifespan_registry import register_startup

_pool_task: asyncio.Task | None = None

async def _start_pool_collector():
    global _pool_task
    _pool_task = asyncio.create_task(collect_pool_metrics(), name="pool_metrics")

register_startup("pool_metrics", _start_pool_collector)
```

---

## Критерии готовности

- [ ] `/metrics` возвращает text/plain с prometheus format
- [ ] UUID в эндпоинтах нормализуются → `{id}` (нет label explosion)
- [ ] HTTP 5xx request_duration тоже трекается (middleware до exception handler)
- [ ] `/metrics`, `/health` — не попадают в метрики (SKIP_PATHS)
- [ ] DB pool `checkedout` + `size` собираются каждые 15 секунд
- [ ] Все labels заданы в момент объявления метрик (правило Prometheus)
