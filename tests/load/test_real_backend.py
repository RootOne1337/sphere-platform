# -*- coding: utf-8 -*-
"""
Нагрузочный тест против РЕАЛЬНОГО backend (Docker-стек).

В отличие от test_load_1024.py (mock-сервер), этот тест проверяет
полную серверную цепочку:
  • FastAPI/uvicorn (backend на порту 8000)
  • PostgreSQL 15 (регистрация устройств, task results, api_keys)
  • Redis 7.2 (status_cache, task_progress, PubSub events)
  • ConnectionManager (WS-менеджер с session tracking)
  • HeartbeatManager (ping/pong + watchdog)
  • DeviceStatusCache (Redis binary/msgpack)
  • PubSub router (fleet events)
  • Offline queue (pending commands)

Метрики серверной нагрузки:
  • Docker stats: CPU%, RAM, Network I/O для каждого контейнера
  • Postgres: active connections, deadlocks, cache hit ratio
  • Redis: connected_clients, memory, ops/sec
  • Backend: registration latency, WS connect latency, heartbeat RTT

Шаги нагрузки (адаптировано под одну машину):
  1. 32 агентов — прогрев (DB connection pool, Redis pool)
  2. 128 агентов — средняя нагрузка
  3. 512 агентов — высокая нагрузка
  4. 1024 агентов — стресс-тест (предел для одного хоста)

Запуск: pytest tests/load/test_real_backend.py -v -s --timeout=600
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Generator

import aiohttp
import pytest

from tests.load.core.agent_pool import AgentPool
from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.core.virtual_agent import AgentBehavior

logger = logging.getLogger("test_real_backend")

# Подавляем DEBUG-флуд от websockets (каждый фрейм логируется)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("websockets.client").setLevel(logging.WARNING)
logging.getLogger("websockets.protocol").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

REAL_BACKEND_URL = "http://127.0.0.1:8000"
REAL_WS_URL = "ws://127.0.0.1:8000"

# API-ключ для нагрузочного тестирования (создан в БД)
LOAD_TEST_API_KEY = os.environ.get("LOAD_TEST_API_KEY", "")

# Шаги нагрузки: (target_agents, ramp_sec, hold_sec)
LOAD_STEPS = [
    (32,   10.0, 20.0),    # Шаг 1: прогрев
    (128,  20.0, 30.0),    # Шаг 2: средняя нагрузка
    (512,  40.0, 40.0),    # Шаг 3: высокая нагрузка
    (1024, 60.0, 60.0),    # Шаг 4: стресс-тест
]

FA_THRESHOLD = 75.0       # % Fleet Availability (порог на реальном backend ниже)
DEAD_THRESHOLD = 10.0     # % макс DEAD-агентов (реальный backend строже к ресурсам)

# Авторизация для создания задач (admin user)
ADMIN_EMAIL = os.environ.get("LOAD_TEST_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("LOAD_TEST_ADMIN_PASSWORD", "")

# Тестовый скрипт (создан через SQL)
LOAD_TEST_SCRIPT_ID = "a7f5c4a3-887e-47ac-90d9-cf081047f0cb"

# DAG-dispatch: на каких шагах слать задачи, % онлайн-устройств за раз
DAG_DISPATCH_STEPS = {2, 3, 4}   # Шаги 2+ (128+ агентов)
DAG_DISPATCH_PCT = 0.20           # 20% online-устройств получают задачу за волну
DAG_DISPATCH_WAVES = 2            # 2 волны за hold-фазу


# ---------------------------------------------------------------------------
# Серверный мониторинг
# ---------------------------------------------------------------------------

@dataclass
class ContainerStats:
    """Метрики одного Docker-контейнера."""
    name: str
    cpu_pct: float = 0.0
    mem_usage_mb: float = 0.0
    mem_limit_mb: float = 0.0
    mem_pct: float = 0.0
    net_in_mb: float = 0.0
    net_out_mb: float = 0.0


@dataclass
class ServerSnapshot:
    """Снимок серверных метрик."""
    ts: float = 0.0
    containers: list[ContainerStats] = field(default_factory=list)
    pg_active_conns: int = 0
    pg_idle_conns: int = 0
    pg_max_conns: int = 200
    pg_cache_hit_ratio: float = 0.0
    redis_connected_clients: int = 0
    redis_used_memory_mb: float = 0.0
    redis_ops_per_sec: int = 0


def _parse_docker_stats_size(s: str) -> float:
    """Парсинг размеров из docker stats: '123.4MiB' -> 123.4."""
    s = s.strip()
    if not s or s == "--":
        return 0.0
    multipliers = {"B": 1e-6, "KIB": 1e-3, "KB": 1e-3, "MIB": 1.0, "MB": 1.0, "GIB": 1024.0, "GB": 1024.0}
    upper = s.upper()
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if upper.endswith(suffix):
            try:
                return float(upper[: -len(suffix)]) * mult
            except ValueError:
                return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def collect_docker_stats() -> list[ContainerStats]:
    """Собрать Docker stats для ключевых контейнеров."""
    targets = ["backend", "postgres", "redis", "nginx"]
    result: list[ContainerStats] = []

    try:
        raw = subprocess.run(
            [
                "docker", "stats", "--no-stream",
                "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}",
            ],
            capture_output=True, text=True, timeout=15,
        )
        if raw.returncode != 0:
            return result

        for line in raw.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            name = parts[0].strip()
            # Фильтруем только нужные контейнеры
            if not any(t in name.lower() for t in targets):
                continue

            cpu_s = parts[1].strip().rstrip("%")
            try:
                cpu_pct = float(cpu_s)
            except ValueError:
                cpu_pct = 0.0

            # MemUsage: "123.4MiB / 1GiB"
            mem_parts = parts[2].split("/")
            mem_usage = _parse_docker_stats_size(mem_parts[0]) if len(mem_parts) > 0 else 0.0
            mem_limit = _parse_docker_stats_size(mem_parts[1]) if len(mem_parts) > 1 else 0.0

            mem_pct_s = parts[3].strip().rstrip("%")
            try:
                mem_pct = float(mem_pct_s)
            except ValueError:
                mem_pct = 0.0

            # NetIO: "1.23MB / 4.56MB"
            net_parts = parts[4].split("/")
            net_in = _parse_docker_stats_size(net_parts[0]) if len(net_parts) > 0 else 0.0
            net_out = _parse_docker_stats_size(net_parts[1]) if len(net_parts) > 1 else 0.0

            result.append(ContainerStats(
                name=name,
                cpu_pct=cpu_pct,
                mem_usage_mb=mem_usage,
                mem_limit_mb=mem_limit,
                mem_pct=mem_pct,
                net_in_mb=net_in,
                net_out_mb=net_out,
            ))
    except Exception as exc:
        logger.warning("Ошибка сбора docker stats: %s", exc)

    return result


def collect_postgres_stats() -> dict[str, Any]:
    """Собрать метрики PostgreSQL через docker exec."""
    try:
        raw = subprocess.run(
            [
                "docker", "exec", "sphere-platform-postgres-1",
                "psql", "-U", "sphere", "-d", "sphereplatform", "-t", "-A", "-c",
                "SELECT "
                "(SELECT count(*) FROM pg_stat_activity WHERE state = 'active') AS active, "
                "(SELECT count(*) FROM pg_stat_activity WHERE state = 'idle') AS idle, "
                "(SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_conn, "
                "COALESCE((SELECT round(100.0 * sum(blks_hit) / NULLIF(sum(blks_hit) + sum(blks_read), 0), 2) "
                "FROM pg_stat_database), 0) AS cache_hit_ratio;",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if raw.returncode != 0:
            return {}
        parts = raw.stdout.strip().split("|")
        if len(parts) >= 4:
            return {
                "active": int(parts[0]),
                "idle": int(parts[1]),
                "max_conn": int(parts[2]),
                "cache_hit_ratio": float(parts[3]),
            }
    except Exception as exc:
        logger.warning("Ошибка сбора PG stats: %s", exc)
    return {}


def collect_redis_stats() -> dict[str, Any]:
    """Собрать метрики Redis через docker exec."""
    try:
        raw = subprocess.run(
            [
                "docker", "exec", "sphere-platform-redis-1",
                "redis-cli", "-a", os.environ.get("REDIS_PASSWORD", ""), "INFO", "clients", "memory", "stats",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if raw.returncode != 0:
            return {}
        info: dict[str, Any] = {}
        for line in raw.stdout.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                k, v = line.split(":", 1)
                info[k.strip()] = v.strip()
        return {
            "connected_clients": int(info.get("connected_clients", 0)),
            "used_memory_mb": round(int(info.get("used_memory", 0)) / 1048576, 1),
            "ops_per_sec": int(info.get("instantaneous_ops_per_sec", 0)),
        }
    except Exception as exc:
        logger.warning("Ошибка сбора Redis stats: %s", exc)
    return {}


def collect_server_snapshot() -> ServerSnapshot:
    """Полный снимок серверных метрик."""
    snap = ServerSnapshot(ts=time.time())
    snap.containers = collect_docker_stats()

    pg = collect_postgres_stats()
    if pg:
        snap.pg_active_conns = pg.get("active", 0)
        snap.pg_idle_conns = pg.get("idle", 0)
        snap.pg_max_conns = pg.get("max_conn", 200)
        snap.pg_cache_hit_ratio = pg.get("cache_hit_ratio", 0.0)

    rd = collect_redis_stats()
    if rd:
        snap.redis_connected_clients = rd.get("connected_clients", 0)
        snap.redis_used_memory_mb = rd.get("used_memory_mb", 0.0)
        snap.redis_ops_per_sec = rd.get("ops_per_sec", 0)

    return snap


def print_server_snapshot(snap: ServerSnapshot, label: str = "") -> None:
    """Красивый вывод серверного снимка."""
    print(f"\n    --- Серверные метрики{f' ({label})' if label else ''} ---")
    for c in snap.containers:
        print(
            f"    {c.name:<35} CPU={c.cpu_pct:>6.1f}%  "
            f"RAM={c.mem_usage_mb:>7.1f}MB ({c.mem_pct:.1f}%)  "
            f"Net I/O={c.net_in_mb:.1f}/{c.net_out_mb:.1f}MB"
        )
    print(
        f"    PostgreSQL: active={snap.pg_active_conns} idle={snap.pg_idle_conns} "
        f"max={snap.pg_max_conns} cache_hit={snap.pg_cache_hit_ratio}%"
    )
    print(
        f"    Redis: clients={snap.redis_connected_clients} "
        f"memory={snap.redis_used_memory_mb}MB ops/s={snap.redis_ops_per_sec}"
    )


# ---------------------------------------------------------------------------
# DAG-dispatch: создание задач через REST API
# ---------------------------------------------------------------------------

async def _get_admin_jwt() -> str:
    """Получить JWT admin-пользователя для создания задач."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{REAL_BACKEND_URL}/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Admin login failed: {resp.status}")
            data = await resp.json()
            return data["access_token"]


async def _dispatch_dag_tasks(
    pool: AgentPool,
    admin_jwt: str,
    metrics: MetricsCollector,
    target_pct: float = DAG_DISPATCH_PCT,
) -> int:
    """Создать задачи для случайной выборки online-агентов.

    Возвращает количество успешно созданных задач.
    """
    online_agents = [
        a for a in pool._agents.values()
        if a.state.name == "ONLINE" and a.registered_device_id
    ]
    if not online_agents:
        return 0

    sample_size = max(1, int(len(online_agents) * target_pct))
    targets = random.sample(online_agents, min(sample_size, len(online_agents)))

    headers = {"Authorization": f"Bearer {admin_jwt}"}
    created = 0

    async with aiohttp.ClientSession() as session:
        for agent in targets:
            try:
                async with session.post(
                    f"{REAL_BACKEND_URL}/api/v1/tasks",
                    json={
                        "script_id": LOAD_TEST_SCRIPT_ID,
                        "device_id": agent.registered_device_id,
                        "priority": 5,
                    },
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 201:
                        created += 1
                        metrics.inc("dag_tasks_created")
                    else:
                        metrics.inc("dag_tasks_create_error")
            except Exception:
                metrics.inc("dag_tasks_create_error")

    return created


# ---------------------------------------------------------------------------
# Предварительная проверка стека
# ---------------------------------------------------------------------------

def _verify_stack_health() -> bool:
    """Проверить что весь Docker-стек работает."""
    import requests
    try:
        r = requests.get(f"{REAL_BACKEND_URL}/api/v1/health", timeout=5)
        if r.status_code != 200:
            logger.error("Backend health check failed: %d", r.status_code)
            return False
    except Exception as exc:
        logger.error("Backend недоступен: %s", exc)
        return False

    # Проверяем что API-ключ валиден
    try:
        r = requests.get(
            f"{REAL_BACKEND_URL}/api/v1/devices/me",
            headers={"X-API-Key": LOAD_TEST_API_KEY},
            timeout=5,
        )
        # 200 или 404 (no device) — OK. 401 — ключ невалиден.
        if r.status_code == 401:
            logger.error("API-ключ невалиден! Создай через SQL (см. документацию)")
            return False
    except Exception as exc:
        logger.error("Ошибка проверки API-ключа: %s", exc)
        return False

    return True


# ---------------------------------------------------------------------------
# Cleanup: удалить тестовые устройства из БД после теста
# ---------------------------------------------------------------------------

def _cleanup_test_devices() -> int:
    """Удалить устройства с именем load-LOAD-* из базы."""
    try:
        raw = subprocess.run(
            [
                "docker", "exec", "sphere-platform-postgres-1",
                "psql", "-U", "sphere", "-d", "sphereplatform", "-t", "-A", "-c",
                "DELETE FROM devices WHERE name LIKE 'load-LOAD-%' RETURNING id;",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if raw.returncode == 0:
            deleted = len([l for l in raw.stdout.strip().split("\n") if l.strip()])
            return deleted
    except Exception as exc:
        logger.warning("Ошибка cleanup: %s", exc)
    return 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def verify_stack() -> Generator[None, None, None]:
    """Проверяем стек перед тестом, cleanup после."""
    if not _verify_stack_health():
        pytest.skip(
            "Docker-стек недоступен. Запустите: docker compose up -d"
        )
    yield
    deleted = _cleanup_test_devices()
    logger.info("Cleanup: удалено %d тестовых устройств", deleted)


# ---------------------------------------------------------------------------
# Нагрузочный тест: 32 -> 128 -> 512 -> 1024 по реальному backend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_real_backend_load() -> None:
    """Нагрузочный тест 32 -> 128 -> 512 -> 1024 агентов по реальному backend.

    Проверяет полную серверную цепочку:
    FastAPI -> PostgreSQL -> Redis -> ConnectionManager -> HeartbeatManager.
    Мониторит Docker stats, PG connections, Redis ops в реальном времени.
    """
    metrics = MetricsCollector()
    factory = IdentityFactory(
        org_id="load-real-backend",
        seed=42,
        shared_api_key=LOAD_TEST_API_KEY,
    )
    behavior = AgentBehavior(
        heartbeat_interval=20.0,       # Не слишком агрессивно для реального backend
        telemetry_interval=15.0,       # Телеметрия каждые 15s
        watchdog_timeout=120.0,        # Увеличенный watchdog
        task_success_rate=0.85,
        dag_speed_factor=0.1,          # В 10x быстрее
        max_pending_results=50,
        enable_vpn=False,              # VPN не тестируем — нет реального WireGuard
        enable_video=False,
        random_disconnect_rate=0.0,    # Стабильные агенты для чистого теста
        max_reconnect_retries=5,
    )

    pool = AgentPool(
        identity_factory=factory,
        behavior=behavior,
        metrics=metrics,
        base_url=REAL_BACKEND_URL,
        ws_url=REAL_WS_URL,
    )

    step_results: list[dict] = []
    server_snapshots: list[ServerSnapshot] = []
    test_start = time.monotonic()

    # Начальный серверный снимок
    print("\n" + "=" * 80)
    print("  НАГРУЗОЧНЫЙ ТЕСТ ПРОТИВ РЕАЛЬНОГО BACKEND")
    print(f"  Backend: {REAL_BACKEND_URL}")
    print(f"  Шаги: {' -> '.join(str(s[0]) for s in LOAD_STEPS)} агентов")
    print(f"  DAG-dispatch: шаги {DAG_DISPATCH_STEPS}, {DAG_DISPATCH_PCT*100:.0f}% агентов x {DAG_DISPATCH_WAVES} волн")
    print("=" * 80)

    # Получаем admin JWT для рассылки DAG-задач
    admin_jwt: str | None = None
    try:
        admin_jwt = await _get_admin_jwt()
        print(f"  Admin JWT получен: {admin_jwt[:30]}...")
    except Exception as exc:
        print(f"  [!] Admin JWT не получен ({exc}), DAG-dispatch выключен")

    baseline = collect_server_snapshot()
    server_snapshots.append(baseline)
    print_server_snapshot(baseline, "baseline")

    try:
        for step_num, (target, ramp_sec, hold_sec) in enumerate(LOAD_STEPS, 1):
            step_t0 = time.monotonic()

            print(
                f"\n{'='*70}\n"
                f"  ШАГ {step_num}/{len(LOAD_STEPS)}: "
                f"{target} агентов\n"
                f"  Ramp: {ramp_sec}s | Hold: {hold_sec}s | "
                f"FA threshold: {FA_THRESHOLD}%\n"
                f"{'='*70}"
            )

            # --- Ramp-up ---
            await pool.scale_to(target, ramp_sec)

            # --- Ожидание ONLINE ---
            online_target = int(target * 0.60)  # 60% порог (реальный backend строже)
            online = await pool.wait_online(
                target=online_target,
                timeout=ramp_sec + 90.0,  # Больше запаса для реального backend
            )
            print(f"  Ramp-up: {online}/{target} online (target >={online_target})")

            # --- Серверный снимок после ramp-up ---
            snap_ramp = collect_server_snapshot()
            server_snapshots.append(snap_ramp)
            print_server_snapshot(snap_ramp, f"step {step_num} ramp-up")

            # --- Hold: мониторинг FA + серверные метрики + DAG-dispatch ---
            fa_samples: list[float] = []
            progress_interval = max(1, int(hold_sec / 4))
            dag_dispatched = 0

            # DAG-dispatch: рассылаем задачи волнами
            dag_dispatch_secs: set[int] = set()
            if admin_jwt and step_num in DAG_DISPATCH_STEPS:
                wave_interval = max(1, int(hold_sec / (DAG_DISPATCH_WAVES + 1)))
                dag_dispatch_secs = {wave_interval * (w + 1) for w in range(DAG_DISPATCH_WAVES)}

            for sec in range(int(hold_sec)):
                await asyncio.sleep(1.0)
                fa = pool.get_fleet_availability()
                fa_samples.append(fa)
                metrics.set_gauge("fleet_availability", fa)

                if sec > 0 and sec % progress_interval == 0:
                    dist = pool.get_state_distribution()
                    print(
                        f"    [{sec}s] Online={pool.online_count}/{target} "
                        f"FA={fa:.1f}% | DAG={dag_dispatched} | {dist}"
                    )

                # DAG-dispatch волна
                if sec in dag_dispatch_secs:
                    cnt = await _dispatch_dag_tasks(pool, admin_jwt, metrics)
                    dag_dispatched += cnt
                    print(f"    [{sec}s] DAG-dispatch: +{cnt} задач (всего {dag_dispatched})")

            # --- Серверный снимок после hold ---
            snap_hold = collect_server_snapshot()
            server_snapshots.append(snap_hold)
            print_server_snapshot(snap_hold, f"step {step_num} hold-end")

            # --- Итоги шага ---
            avg_fa = sum(fa_samples) / max(len(fa_samples), 1)
            min_fa = min(fa_samples) if fa_samples else 0.0
            max_fa = max(fa_samples) if fa_samples else 0.0
            step_duration = time.monotonic() - step_t0
            dist = pool.get_state_distribution()

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
                # Серверные метрики
                "server_snapshot": {
                    "pg_active_conns": snap_hold.pg_active_conns,
                    "pg_idle_conns": snap_hold.pg_idle_conns,
                    "pg_cache_hit_ratio": snap_hold.pg_cache_hit_ratio,
                    "redis_clients": snap_hold.redis_connected_clients,
                    "redis_memory_mb": snap_hold.redis_used_memory_mb,
                    "redis_ops_sec": snap_hold.redis_ops_per_sec,
                    "containers": [
                        {
                            "name": c.name,
                            "cpu_pct": c.cpu_pct,
                            "mem_mb": c.mem_usage_mb,
                            "mem_pct": c.mem_pct,
                        }
                        for c in snap_hold.containers
                    ],
                },
            }
            step_results.append(result)

            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"\n  [{status}] Шаг {step_num}: {pool.online_count}/{target} online | "
                f"FA avg={avg_fa:.1f}% min={min_fa:.1f}% | "
                f"DEAD={dead_count} ({dead_pct:.1f}%) | DAG={dag_dispatched}"
            )

    finally:
        # --- Graceful shutdown ---
        print(f"\n{'='*70}\n  Graceful shutdown {pool.total_count} агентов...\n{'='*70}")
        t_stop = time.monotonic()
        await pool.stop_all(timeout=45.0)
        stop_duration = time.monotonic() - t_stop
        print(f"  Остановка за {stop_duration:.1f}s")

        # Финальный серверный снимок (после shutdown)
        snap_final = collect_server_snapshot()
        server_snapshots.append(snap_final)
        print_server_snapshot(snap_final, "after shutdown")

    # -----------------------------------------------------------------------
    # Сводка
    # -----------------------------------------------------------------------
    total_duration = time.monotonic() - test_start
    snap = metrics.snapshot()
    counters = snap.get("counters", {})
    histograms = snap.get("histograms", {})

    print(f"\n{'='*80}")
    print("  ИТОГИ: НАГРУЗКА ПО РЕАЛЬНОМУ BACKEND")
    print(f"  Время: {total_duration:.1f}s ({total_duration/60:.1f} мин)")
    print(f"{'='*80}")

    # Таблица шагов
    for r in step_results:
        status = "PASS" if r["passed"] else "FAIL"
        srv = r["server_snapshot"]
        # Ищем backend CPU
        backend_cpu = 0.0
        for c in srv["containers"]:
            if "backend" in c["name"]:
                backend_cpu = c["cpu_pct"]
        print(
            f"  Шаг {r['step']}: {r['target']:>5} | "
            f"Online {r['online']:>5}/{r['target']:>5} | "
            f"FA={r['avg_fa']:>5.1f}% | "
            f"DEAD={r['dead_count']:>3} ({r['dead_pct']:.1f}%) | "
            f"PG={srv['pg_active_conns']}/{srv['pg_idle_conns']} | "
            f"Redis={srv['redis_clients']}cl {srv['redis_ops_sec']}ops/s | "
            f"CPU={backend_cpu:.1f}% | "
            f"[{status}]"
        )

    # Метрики клиентской стороны
    print("\n  --- Клиентские метрики ---")
    print(f"  Регистраций: {counters.get('registration_success', 0)} OK / {counters.get('registration_error', 0)} ERR")
    print(f"  WS connect: {counters.get('ws_connect_success', 0)} OK / {counters.get('ws_connect_error', 0)} ERR")
    print(f"  Heartbeat pong: {counters.get('heartbeat_pong_sent', 0)}")
    print(f"  Telemetry: {counters.get('telemetry_sent', 0)}")
    print(f"  DEAD: {counters.get('agent_dead_total', 0)}")
    print(f"  Watchdog timeout: {counters.get('ws_watchdog_timeout', 0)}")
    print(f"  Reconnects: {counters.get('ws_reconnect_total', 0)}")

    # DAG-execution метрики (VirtualAgent: task_received/task_ack_sent/task_progress_sent/task_completed/task_failed)
    print("\n  --- DAG Execution ---")
    print(f"  Задач создано (API): {counters.get('dag_tasks_created', 0)} OK / {counters.get('dag_tasks_create_error', 0)} ERR")
    print(f"  DAG received (WS): {counters.get('task_received', 0)}")
    print(f"  DAG ack sent: {counters.get('task_ack_sent', 0)}")
    print(f"  DAG completed: {counters.get('task_completed', 0)}")
    print(f"  DAG failed: {counters.get('task_failed', 0)}")
    print(f"  DAG progress sent: {counters.get('task_progress_sent', 0)}")
    print(f"  DAG result sent: {counters.get('command_result_sent', 0)}")

    # Латентности
    print("\n  --- Латентности ---")
    for name in ["registration_latency_ms", "ws_connect_latency_ms", "ws_auth_latency_ms", "ws_heartbeat_rtt_ms"]:
        h = histograms.get(name, {})
        if h:
            print(
                f"  {name}: p50={h.get('p50', 0):.1f}ms "
                f"p95={h.get('p95', 0):.1f}ms "
                f"p99={h.get('p99', 0):.1f}ms "
                f"max={h.get('max', 0):.1f}ms"
            )

    # Серверная эволюция: как росли метрики
    print("\n  --- Эволюция серверных ресурсов ---")
    backend_cpus = []
    pg_cpus = []
    redis_cpus = []
    for snap in server_snapshots:
        for c in snap.containers:
            if "backend" in c.name:
                backend_cpus.append(c.cpu_pct)
            elif "postgres" in c.name:
                pg_cpus.append(c.cpu_pct)
            elif "redis" in c.name:
                redis_cpus.append(c.cpu_pct)

    if backend_cpus:
        print(f"  Backend CPU: {' -> '.join(f'{x:.1f}%' for x in backend_cpus)}")
    if pg_cpus:
        print(f"  Postgres CPU: {' -> '.join(f'{x:.1f}%' for x in pg_cpus)}")
    if redis_cpus:
        print(f"  Redis CPU: {' -> '.join(f'{x:.1f}%' for x in redis_cpus)}")

    print(f"\n{'='*80}")

    # Bottleneck анализ
    print("  АНАЛИЗ BOTTLENECK:")
    bottlenecks: list[str] = []

    # PG connections
    last_snap = server_snapshots[-2] if len(server_snapshots) > 1 else server_snapshots[-1]
    pg_usage = (last_snap.pg_active_conns + last_snap.pg_idle_conns) / max(last_snap.pg_max_conns, 1) * 100
    if pg_usage > 80:
        bottlenecks.append(f"  [!] PostgreSQL: {pg_usage:.0f}% connection pool usage (critical)")
    elif pg_usage > 50:
        bottlenecks.append(f"  [*] PostgreSQL: {pg_usage:.0f}% connection pool usage (attention)")

    # Backend CPU
    if backend_cpus and max(backend_cpus) > 80:
        bottlenecks.append(f"  [!] Backend CPU peak: {max(backend_cpus):.1f}% (critical)")
    elif backend_cpus and max(backend_cpus) > 50:
        bottlenecks.append(f"  [*] Backend CPU peak: {max(backend_cpus):.1f}% (attention)")

    # Redis memory
    if last_snap.redis_used_memory_mb > 400:
        bottlenecks.append(f"  [!] Redis memory: {last_snap.redis_used_memory_mb:.0f}MB (near 512MB limit)")

    # Registration latency
    reg_h = histograms.get("registration_latency_ms", {})
    if reg_h and reg_h.get("p99", 0) > 1000:
        bottlenecks.append(f"  [!] Registration p99: {reg_h['p99']:.0f}ms (>1s)")

    # WS connect latency
    ws_h = histograms.get("ws_connect_latency_ms", {})
    if ws_h and ws_h.get("p99", 0) > 500:
        bottlenecks.append(f"  [!] WS connect p99: {ws_h['p99']:.0f}ms (>500ms)")

    # Dead agents
    dead_total = counters.get("agent_dead_total", 0)
    if dead_total > 0:
        bottlenecks.append(f"  [!] DEAD агентов: {dead_total} (reconnect limit exceeded)")

    if bottlenecks:
        for b in bottlenecks:
            print(b)
    else:
        print("  Bottleneck не обнаружен — система стабильна!")

    print(f"{'='*80}")

    # Assert — все шаги прошли
    for r in step_results:
        assert r["fa_passed"], (
            f"Шаг {r['step']} ({r['target']} агентов): "
            f"FA {r['avg_fa']:.1f}% < {FA_THRESHOLD}%"
        )
        assert r["dead_passed"], (
            f"Шаг {r['step']} ({r['target']} агентов): "
            f"DEAD {r['dead_pct']:.1f}% > {DEAD_THRESHOLD}%"
        )
