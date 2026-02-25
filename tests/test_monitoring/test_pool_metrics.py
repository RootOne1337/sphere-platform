# tests/test_monitoring/test_pool_metrics.py
"""
Unit-тесты для backend/monitoring/pool_metrics.py.
Проверяет:
  - startup hook зарегистрирован в lifespan_registry
  - shutdown hook зарегистрирован в lifespan_registry
  - коллектор опрашивает pool и обновляет Gauges
  - коллектор корректно завершается при отмене задачи
"""
from __future__ import annotations

import asyncio

import pytest

# ── lifespan_registry registration ──────────────────────────────────────────

def test_pool_metrics_registers_startup_hook():
    """Импорт pool_metrics должен зарегистрировать startup hook."""
    # Импортируем модуль (он регистрирует хуки при импорте)
    import backend.monitoring.pool_metrics  # noqa: F401
    from backend.core.lifespan_registry import _startup_hooks  # noqa: PLC2701

    hook_names = [name for name, _ in _startup_hooks]
    assert "pool_metrics_collector" in hook_names


def test_pool_metrics_registers_shutdown_hook():
    """Импорт pool_metrics должен зарегистрировать shutdown hook."""
    import backend.monitoring.pool_metrics  # noqa: F401
    from backend.core.lifespan_registry import _shutdown_hooks  # noqa: PLC2701

    hook_names = [name for name, _ in _shutdown_hooks]
    assert "pool_metrics_collector" in hook_names


# ── pool gauge update ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collect_updates_gauges(monkeypatch):
    """
    _collect_pool_metrics должна обновлять db_pool_size и db_pool_checked_out.
    Использует monkeypatch для мокирования engine.pool.
    """
    from unittest.mock import MagicMock, patch

    mock_pool = MagicMock()
    mock_pool.size.return_value = 10
    mock_pool.checkedout.return_value = 3

    mock_engine = MagicMock()
    mock_engine.pool = mock_pool

    # Патчим engine до вызова _collect_pool_metrics
    with patch("backend.monitoring.pool_metrics.asyncio.sleep", side_effect=asyncio.CancelledError):
        with patch("backend.database.engine.engine", mock_engine):
            # run once iteration (sleep raises CancelledError)
            try:
                from backend.monitoring.pool_metrics import _collect_pool_metrics
                await _collect_pool_metrics()
            except asyncio.CancelledError:
                pass


    # После одной итерации Gauges должны быть обновлены
    collected = {m.name: list(m.samples) for m in __import__("prometheus_client").REGISTRY.collect()}
    pool_size_val = next(
        (s.value for s in collected.get("sphere_db_pool_size", []) if s.name == "sphere_db_pool_size"),
        None,
    )
    pool_checked_val = next(
        (s.value for s in collected.get("sphere_db_pool_checked_out", []) if s.name == "sphere_db_pool_checked_out"),
        None,
    )

    assert pool_size_val == 10.0
    assert pool_checked_val == 3.0


@pytest.mark.asyncio
async def test_start_and_stop_pool_collector():
    """
    _start_pool_collector запускает фоновую задачу,
    _stop_pool_collector отменяет её без ошибок.
    """
    from unittest.mock import patch

    async def _forever():
        await asyncio.sleep(9999)

    from backend.monitoring import pool_metrics

    pool_metrics._pool_task = None

    with patch("backend.monitoring.pool_metrics._collect_pool_metrics", _forever):
        await pool_metrics._start_pool_collector()
        assert pool_metrics._pool_task is not None
        assert not pool_metrics._pool_task.done()

        await pool_metrics._stop_pool_collector()
        assert pool_metrics._pool_task is None
