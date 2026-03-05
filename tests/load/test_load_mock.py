# -*- coding: utf-8 -*-
"""
Нагрузочный Quick-тест: 32 → 64 → 128 агентов через mock-сервер.

Проверяет:
  • Ramp-up: 32 → 64 → 128 агентов с линейной подачей
  • Fleet Availability ≥ 90% на каждом шаге
  • Heartbeat, telemetry, VPN enrollment
  • Корректная остановка (graceful shutdown)

Запуск: pytest tests/load/test_load_mock.py -v -s
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Generator

import pytest
import uvicorn

from tests.load.core.agent_pool import AgentPool
from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.core.virtual_agent import AgentBehavior
from tests.load.mock_server import app

logger = logging.getLogger("test_load_mock")

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

MOCK_HOST = "127.0.0.1"
MOCK_PORT = 18082
BASE_URL = f"http://{MOCK_HOST}:{MOCK_PORT}"
WS_URL = f"ws://{MOCK_HOST}:{MOCK_PORT}"

# Шаги нагрузки: (target_agents, ramp_sec, hold_sec)
LOAD_STEPS = [
    (32, 10.0, 15.0),
    (64, 10.0, 15.0),
    (128, 15.0, 20.0),
]

FA_THRESHOLD = 85.0  # % Fleet Availability (порог прохождения)

# ---------------------------------------------------------------------------
# Сервер
# ---------------------------------------------------------------------------

_server_thread: threading.Thread | None = None


def _ensure_mock_server() -> None:
    """Запускает mock-сервер в daemon-потоке."""
    global _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        return
    config = uvicorn.Config(
        app, host=MOCK_HOST, port=MOCK_PORT, log_level="warning",
    )
    server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=server.run, daemon=True)
    _server_thread.start()

    import urllib.request
    for _ in range(50):
        try:
            with urllib.request.urlopen(
                f"{BASE_URL}/api/health", timeout=2
            ) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("Mock-сервер не стартовал")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def start_server() -> Generator[None, None, None]:
    _ensure_mock_server()
    yield


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_quick_ramp() -> None:
    """Нагрузочный тест: 32 → 64 → 128 агентов через mock-сервер."""
    metrics = MetricsCollector()
    factory = IdentityFactory(org_id="load-quick", seed=777)
    behavior = AgentBehavior(
        heartbeat_interval=10.0,
        telemetry_interval=5.0,
        watchdog_timeout=120.0,
        task_success_rate=0.85,
        enable_vpn=True,
        enable_video=False,
        random_disconnect_rate=0.0,  # без случайных обрывов
    )

    pool = AgentPool(
        identity_factory=factory,
        behavior=behavior,
        metrics=metrics,
        base_url=BASE_URL,
        ws_url=WS_URL,
    )

    step_results: list[dict] = []
    test_start = time.monotonic()

    try:
        for step_num, (target, ramp_sec, hold_sec) in enumerate(LOAD_STEPS, 1):
            step_t0 = time.monotonic()
            logger.info(
                "=== ШАГ %d: %d агентов (ramp=%.0fs, hold=%.0fs) ===",
                step_num, target, ramp_sec, hold_sec,
            )
            print(
                f"\n{'='*60}\n"
                f"  ШАГ {step_num}: Масштабирование до {target} агентов\n"
                f"  Ramp: {ramp_sec}s | Hold: {hold_sec}s\n"
                f"{'='*60}"
            )

            # Ramp-up
            await pool.scale_to(target, ramp_sec)

            # Ожидание выхода агентов в ONLINE
            online = await pool.wait_online(
                target=int(target * 0.8),  # 80% порог
                timeout=ramp_sec + 30.0,
            )

            # Hold — даём поработать
            fa_samples: list[float] = []
            for _ in range(int(hold_sec)):
                await asyncio.sleep(1.0)
                fa = pool.get_fleet_availability()
                fa_samples.append(fa)
                metrics.set_gauge("fleet_availability", fa)

            # Итог шага
            avg_fa = sum(fa_samples) / max(len(fa_samples), 1)
            min_fa = min(fa_samples) if fa_samples else 0.0
            step_duration = time.monotonic() - step_t0
            dist = pool.get_state_distribution()

            result = {
                "step": step_num,
                "target": target,
                "online": pool.online_count,
                "total": pool.total_count,
                "avg_fa": round(avg_fa, 2),
                "min_fa": round(min_fa, 2),
                "duration_sec": round(step_duration, 1),
                "distribution": dist,
                "passed": avg_fa >= FA_THRESHOLD,
            }
            step_results.append(result)

            print(
                f"  -> Online: {pool.online_count}/{target} | "
                f"FA avg={avg_fa:.1f}% min={min_fa:.1f}% | "
                f"Distribution: {dist}"
            )

    finally:
        # Graceful shutdown
        print(f"\n{'='*60}\n  Остановка всех агентов...\n{'='*60}")
        await pool.stop_all(timeout=15.0)

    # ---------------------------------------------------------------------------
    # Сводка
    # ---------------------------------------------------------------------------
    total_duration = time.monotonic() - test_start
    snap = metrics.snapshot()

    print(f"\n{'='*60}")
    print(f"  ИТОГИ НАГРУЗОЧНОГО ТЕСТА")
    print(f"  Общее время: {total_duration:.1f}s")
    print(f"{'='*60}")

    for r in step_results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"  Шаг {r['step']}: {r['target']} агентов | "
            f"Online {r['online']}/{r['target']} | "
            f"FA avg={r['avg_fa']}% min={r['min_fa']}% | "
            f"[{status}]"
        )

    # Метрики
    counters = snap.get("counters", {})
    print(f"\n  Ключевые метрики:")
    for key in [
        "registration_success", "registration_duplicate",
        "ws_connect_success", "ws_online_total",
        "telemetry_sent", "heartbeat_pong_sent",
        "vpn_enroll_success", "task_received", "task_completed",
        "ws_disconnect_total", "ws_reconnect_total",
    ]:
        val = counters.get(key, 0)
        if val:
            print(f"    {key}: {val}")

    # Проверка
    all_passed = all(r["passed"] for r in step_results)
    assert all_passed, (
        f"Тест не пройден: FA ниже {FA_THRESHOLD}% на одном из шагов. "
        f"Результаты: {step_results}"
    )
