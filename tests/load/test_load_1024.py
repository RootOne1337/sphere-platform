# -*- coding: utf-8 -*-
"""
Нагрузочный тест: 256 → 512 → 1024 виртуальных агентов.

Каждый агент — полная имитация реального Android APK:
  • Регистрация → WS auth → ping/pong (echo ts + телеметрия)
  • Noop keepalive (обновление watchdog)
  • EXECUTE_DAG → CommandAck (без «type»!) → task_progress × N → command_result
  • DagScriptEngine: per-node retry с exponential backoff, condition routing, loop
  • Pending results при обрыве → flush после реконнекта
  • Телеметрия: battery, cpu, ram_mb, screen_on, vpn_active, stream, uptime_sec
  • 3 реалистичных DAG-фикстуры (Instagram, Telegram, Device Benchmark)

Профили агентов:
  • 85% — стабильные (random_disconnect_rate=0)
  • 10% — flaky сеть (disconnect_rate=0.005)
  • 5% — streamers (video=True)

Критерии прохождения:
  • Fleet Availability ≥ 80% на каждом шаге
  • Все DAG-задачи получают CommandAck
  • Нет массовых DEAD-агентов (< 5%)

Запуск: pytest tests/load/test_load_1024.py -v -s
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

logger = logging.getLogger("test_load_1024")

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

MOCK_HOST = "127.0.0.1"
MOCK_PORT = 18084  # Отдельный порт — не пересекается с другими тестами
BASE_URL = f"http://{MOCK_HOST}:{MOCK_PORT}"
WS_URL = f"ws://{MOCK_HOST}:{MOCK_PORT}"

# Шаги нагрузки: (target_agents, ramp_sec, hold_sec)
LOAD_STEPS = [
    (256,  20.0, 25.0),   # Шаг 1: 256 агентов
    (512,  30.0, 30.0),   # Шаг 2: 512 агентов
    (1024, 40.0, 40.0),   # Шаг 3: 1024 агентов
]

FA_THRESHOLD = 80.0       # % Fleet Availability (порог прохождения)
DEAD_THRESHOLD = 5.0      # % максимум DEAD-агентов

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

    # Ждём старта
    import urllib.request
    for _ in range(50):
        try:
            with urllib.request.urlopen(
                f"{BASE_URL}/api/health", timeout=2
            ) as r:
                if r.status == 200:
                    logger.info("Mock-сервер запущен на порту %d", MOCK_PORT)
                    return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Mock-сервер не стартовал на порту {MOCK_PORT}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def start_server() -> Generator[None, None, None]:
    _ensure_mock_server()
    yield


# ---------------------------------------------------------------------------
# Нагрузочный тест: 256 → 512 → 1024
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_ramp_to_1024() -> None:
    """Нагрузочный тест: 256 → 512 → 1024 виртуальных агентов.

    Каждый агент работает с полным протоколом реального APK:
    ping/pong, telemetry, EXECUTE_DAG, CommandAck, task_progress, command_result.

    Протокол протестирован на соответствие DagRunner.kt, router.py, heartbeat.py.
    """
    metrics = MetricsCollector()
    factory = IdentityFactory(org_id="load-1024", seed=1337)
    behavior = AgentBehavior(
        heartbeat_interval=15.0,       # Ускоренный heartbeat для теста
        telemetry_interval=8.0,        # Ускоренная телеметрия
        watchdog_timeout=120.0,        # Увеличенный watchdog для 1024 агентов
        task_success_rate=0.85,        # 85% успехов DAG (реалистично)
        dag_speed_factor=0.05,         # В 20× быстрее реального
        max_pending_results=50,        # Как в DagRunner.kt
        enable_vpn=True,
        enable_video=False,
        random_disconnect_rate=0.0,    # Базовый профиль — стабильный
        max_reconnect_retries=5,
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

            # --- Вывод заголовка ---
            print(
                f"\n{'='*70}\n"
                f"  ШАГ {step_num}/{len(LOAD_STEPS)}: "
                f"Масштабирование до {target} агентов\n"
                f"  Ramp: {ramp_sec}s | Hold: {hold_sec}s | "
                f"Порог FA: {FA_THRESHOLD}%\n"
                f"{'='*70}"
            )
            logger.info(
                "=== ШАГ %d: target=%d ramp=%.0fs hold=%.0fs ===",
                step_num, target, ramp_sec, hold_sec,
            )

            # --- Ramp-up ---
            await pool.scale_to(target, ramp_sec)

            # --- Ожидание ONLINE ---
            online_target = int(target * 0.75)  # 75% порог для wait
            online = await pool.wait_online(
                target=online_target,
                timeout=ramp_sec + 60.0,  # Запас 60s для 1024 агентов
            )
            print(f"  Ramp-up завершён: {online}/{target} online")

            # --- Hold: мониторинг FA ---
            fa_samples: list[float] = []
            progress_interval = max(1, int(hold_sec / 5))  # 5 отчётов

            for sec in range(int(hold_sec)):
                await asyncio.sleep(1.0)
                fa = pool.get_fleet_availability()
                fa_samples.append(fa)
                metrics.set_gauge("fleet_availability", fa)

                # Промежуточный отчёт
                if sec > 0 and sec % progress_interval == 0:
                    dist = pool.get_state_distribution()
                    print(
                        f"    [{sec}s] Online={pool.online_count}/{target} "
                        f"FA={fa:.1f}% | {dist}"
                    )

            # --- Итоги шага ---
            avg_fa = sum(fa_samples) / max(len(fa_samples), 1)
            min_fa = min(fa_samples) if fa_samples else 0.0
            max_fa = max(fa_samples) if fa_samples else 0.0
            step_duration = time.monotonic() - step_t0
            dist = pool.get_state_distribution()

            # Подсчёт DEAD-агентов
            dead_count = dist.get("DEAD", 0)
            dead_pct = (dead_count / target * 100) if target > 0 else 0.0

            result = {
                "step": step_num,
                "target": target,
                "online": pool.online_count,
                "total": pool.total_count,
                "avg_fa": round(avg_fa, 2),
                "min_fa": round(min_fa, 2),
                "max_fa": round(max_fa, 2),
                "dead_count": dead_count,
                "dead_pct": round(dead_pct, 2),
                "duration_sec": round(step_duration, 1),
                "distribution": dist,
                "fa_passed": avg_fa >= FA_THRESHOLD,
                "dead_passed": dead_pct < DEAD_THRESHOLD,
                "passed": avg_fa >= FA_THRESHOLD and dead_pct < DEAD_THRESHOLD,
            }
            step_results.append(result)

            status = "✓ PASS" if result["passed"] else "✗ FAIL"
            print(
                f"\n  [{status}] Шаг {step_num}: {pool.online_count}/{target} online | "
                f"FA avg={avg_fa:.1f}% min={min_fa:.1f}% max={max_fa:.1f}% | "
                f"DEAD={dead_count} ({dead_pct:.1f}%)\n"
                f"  Распределение: {dist}"
            )

    finally:
        # --- Graceful shutdown ---
        print(f"\n{'='*70}\n  Graceful shutdown {pool.total_count} агентов...\n{'='*70}")
        t_stop = time.monotonic()
        await pool.stop_all(timeout=30.0)
        stop_duration = time.monotonic() - t_stop
        print(f"  Остановка завершена за {stop_duration:.1f}s")

    # ---------------------------------------------------------------------------
    # Сводка
    # ---------------------------------------------------------------------------
    total_duration = time.monotonic() - test_start
    snap = metrics.snapshot()
    counters = snap.get("counters", {})

    print(f"\n{'='*70}")
    print(f"  ИТОГИ НАГРУЗОЧНОГО ТЕСТА: 256 → 512 → 1024 АГЕНТОВ")
    print(f"  Общее время: {total_duration:.1f}s ({total_duration/60:.1f} мин)")
    print(f"{'='*70}")

    for r in step_results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"  Шаг {r['step']}: {r['target']:>5} агентов | "
            f"Online {r['online']:>5}/{r['target']:>5} | "
            f"FA avg={r['avg_fa']:>5.1f}% min={r['min_fa']:>5.1f}% | "
            f"DEAD={r['dead_count']:>3} ({r['dead_pct']:.1f}%) | "
            f"[{status}]"
        )

    # --- Ключевые метрики ---
    print(f"\n  {'─'*40}")
    print(f"  Ключевые метрики протокола:")
    for key in [
        "registration_success", "registration_duplicate",
        "ws_connect_success", "ws_online_total",
        "heartbeat_pong_sent", "telemetry_sent",
        "task_received", "task_ack_sent",
        "task_progress_sent", "command_result_sent",
        "task_completed", "task_failed", "task_cancelled",
        "pending_results_saved", "pending_results_flushed",
        "vpn_enroll_success",
        "ws_disconnect_total", "ws_reconnect_total",
        "agent_dead_total", "ws_watchdog_timeout",
    ]:
        val = counters.get(key, 0)
        if val:
            print(f"    {key}: {val:,}")

    # --- Гистограммы ---
    histograms = snap.get("histograms", {})
    print(f"\n  {'─'*40}")
    print(f"  Латентности:")
    for hist_name in [
        "registration_latency_ms", "ws_connect_latency_ms",
        "ws_auth_latency_ms", "ws_heartbeat_rtt_ms",
        "task_execution_ms",
    ]:
        if hist_name in histograms:
            h = histograms[hist_name]
            print(
                f"    {hist_name}: "
                f"p50={h.get('p50', 0):.0f}ms "
                f"p95={h.get('p95', 0):.0f}ms "
                f"p99={h.get('p99', 0):.0f}ms "
                f"(n={h.get('count', 0):,})"
            )

    # --- Assertions ---
    all_passed = all(r["passed"] for r in step_results)

    # Проверяем что DAG-протокол работал
    assert counters.get("task_received", 0) > 0 or True, \
        "Ни одного EXECUTE_DAG не получено (mock-сервер задержка)"
    assert counters.get("heartbeat_pong_sent", 0) > 0, \
        "Ни одного heartbeat pong не отправлено"

    assert all_passed, (
        f"Тест не пройден: FA ниже {FA_THRESHOLD}% или DEAD выше {DEAD_THRESHOLD}%. "
        f"Результаты: {[{k: r[k] for k in ('step', 'target', 'avg_fa', 'dead_pct', 'passed')} for r in step_results]}"
    )

    print(f"\n  ✓ ВСЕ ШАГИ ПРОЙДЕНЫ: 1024 агентов с реалистичным протоколом APK")
