# backend/monitoring/pool_metrics.py
# Периодический сборщик метрик SQLAlchemy connection pool.
#
# FIX 11.3: БЫЛО — collect_pool_metrics() нигде не запускалась → Gauges всегда = 0.
# СТАЛО — регистрируется через lifespan_registry; запускается автоматически при старте.
import asyncio

import structlog

from backend.core.lifespan_registry import register_shutdown, register_startup
from backend.metrics import db_pool_checked_out, db_pool_size

logger = structlog.get_logger()

_POLL_INTERVAL_SECONDS = 15

_pool_task: asyncio.Task | None = None


async def _collect_pool_metrics() -> None:
    """
    Опрашивает SQLAlchemy pool каждые 15 секунд и обновляет Gauges.
    Запускается как фоновая задача через lifespan.
    """
    # Импорт отложен: engine создаётся при старте приложения, не при импорте модуля.
    from backend.database.engine import engine

    while True:
        try:
            pool = engine.pool
            db_pool_size.set(pool.size())
            db_pool_checked_out.set(pool.checkedout())
        except Exception:
            logger.exception("pool_metrics.collect_error")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def _start_pool_collector() -> None:
    global _pool_task
    _pool_task = asyncio.create_task(
        _collect_pool_metrics(),
        name="pool_metrics_collector",
    )
    logger.info("pool_metrics.started", interval_seconds=_POLL_INTERVAL_SECONDS)


async def _stop_pool_collector() -> None:
    global _pool_task
    if _pool_task and not _pool_task.done():
        _pool_task.cancel()
        try:
            await _pool_task
        except asyncio.CancelledError:
            pass
    _pool_task = None
    logger.info("pool_metrics.stopped")


# Регистрируем через lifespan_registry → main.py не трогаем.
register_startup("pool_metrics_collector", _start_pool_collector)
register_shutdown("pool_metrics_collector", _stop_pool_collector)
