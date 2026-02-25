# backend/main.py — СОЗДАЁТСЯ В TZ-00, РЕДАКТИРОВАТЬ ЗАПРЕЩЕНО ВСЕМ ЭТАПАМ
# Каждый новый этап создаёт ТОЛЬКО backend/api/v1/<NAME>/router.py — он подключится автоматически
import importlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette_exporter import PrometheusMiddleware as _StarlettePrometheus
from starlette_exporter import handle_metrics

import backend.core.logging_config  # noqa: F401 — TZ-11 SPLIT-4: module-level structlog init
from backend.core.cors import setup_cors
from backend.middleware.metrics import PrometheusMiddleware
from backend.middleware.request_id import RequestIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    CRIT-3: main.py не знает о конкретных сервисах — только запускает реестр.
    Новые startup/shutdown хуки регистрируются в самих модулях через register_startup().
    """
    # Импортируем redis_client для регистрации хуков (register_startup/register_shutdown)
    # Остальные модули регистрируют свои хуки при импорте router.py
    import backend.database.redis_client  # noqa: F401
    import backend.monitoring.pool_metrics  # noqa: F401 — регистрирует DB pool collector
    from backend.core.lifespan_registry import run_all_shutdown, run_all_startup

    await run_all_startup()

    # F-02: fail-fast if backend DB user is a PostgreSQL superuser (bypasses RLS)
    from backend.core.startup_checks import check_db_role_not_superuser
    await check_db_role_not_superuser()

    # PROC-4: экспорт OpenAPI schema для TZ-10 (frontend типы через openapi-typescript)
    Path("openapi.json").write_text(
        json.dumps(app.openapi(), indent=2, ensure_ascii=False)
    )

    yield   # приложение работает

    await run_all_shutdown()


app = FastAPI(
    title="Sphere Platform API",
    version="4.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,             # FastAPI ≥ 0.93: рекомендуемый способ startup/shutdown
)

setup_cors(app)

# TZ-11 SPLIT-1: Prometheus metrics middleware + /metrics endpoint
# TZ-11 SPLIT-4: RequestIdMiddleware — X-Request-ID на каждый ответ + structlog context
# Порядок (add_middleware в Starlette применяется в обратном порядке LIFO):
#   1) RequestIdMiddleware  — самый внешний (запускается первым)
#   2) PrometheusMiddleware — timing после request_id
#   3) StarlettePrometheus  — exposition
app.add_middleware(_StarlettePrometheus, app_name="sphere", group_paths=True)
app.add_middleware(PrometheusMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_route("/metrics", handle_metrics)

# ── Авто-дискавери роутеров ───────────────────────────────────────────────────
# Подключает backend/api/v1/<subdir>/router.py для каждой поддиректории.
# ВАЖНО: каждый новый этап создаёт backend/api/v1/<NAME>/router.py
# НЕ файл <NAME>.py в корне — авто-дискавери не найдёт файл!
# Порядок: алфавитный (auth < devices < scripts < ...).
_v1_path = Path(__file__).parent / "api" / "v1"
if _v1_path.exists():
    for _sub in sorted(_v1_path.iterdir()):
        if _sub.is_dir() and (_sub / "router.py").exists():
            _mod = importlib.import_module(f"backend.api.v1.{_sub.name}.router")
            if hasattr(_mod, "router"):
                app.include_router(_mod.router, prefix="/api/v1")

# ── WebSocket роутеры ─────────────────────────────────────────────────────────
# Подключает backend/api/ws/<subdir>/router.py (stage/3-websocket)
# КАЖДЫЙ WS-модуль ОБЯЗАН быть папкой с router.py:
#   backend/api/ws/android/router.py
#   backend/api/ws/agent/router.py
# НЕ backend/api/ws/android.py — авто-дискавери не найдёт файл!
_ws_path = Path(__file__).parent / "api" / "ws"
if _ws_path.exists():
    for _sub in sorted(_ws_path.iterdir()):
        if _sub.is_dir() and (_sub / "router.py").exists():
            _mod = importlib.import_module(f"backend.api.ws.{_sub.name}.router")
            if hasattr(_mod, "router"):
                app.include_router(_mod.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """Catch-all handler so 5xx errors pass through CORSMiddleware (inside ExceptionMiddleware)."""
    import structlog as _structlog
    _structlog.get_logger().error("unhandled_exception", error=str(exc))
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/v1/health", tags=["health"])
async def health_check():
    return {"status": "ok", "version": "4.0.0"}


@app.get("/api/v1/health/ready", tags=["health"])
async def readiness_check():
    """Readiness probe — проверяет подключение к БД и Redis."""
    from backend.database.engine import engine
    from backend.database.redis_client import redis

    checks: dict = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    try:
        if redis:
            await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    from fastapi import HTTPException
    if not all_ok:
        raise HTTPException(status_code=503, detail=checks)
    return {"status": "ready", "checks": checks}
