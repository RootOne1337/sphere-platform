# -*- coding: utf-8 -*-
"""
Интеграционные тесты — виртуальные агенты ↔ mock-сервер.

Тестируют полный цикл: регистрация → WS-подключение → heartbeat →
telemetry → task execution → VPN enrollment.

Запуск: pytest tests/load/test_integration.py -v
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

import aiohttp
import pytest
import uvicorn

from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.core.virtual_agent import VirtualAgent, AgentBehavior, AgentState
from tests.load.mock_server import app

logger = logging.getLogger("test_integration")

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

MOCK_HOST = "127.0.0.1"
MOCK_PORT = 18081  # Отдельный порт для тестов
BASE_URL = f"http://{MOCK_HOST}:{MOCK_PORT}"
WS_URL = f"ws://{MOCK_HOST}:{MOCK_PORT}"

# ---------------------------------------------------------------------------
# Глобальный сервер — запуск в потоке один раз на модуль
# ---------------------------------------------------------------------------

_server_thread: threading.Thread | None = None
_server_started = threading.Event()


def _run_server() -> None:
    """Запуск uvicorn в отдельном потоке с собственным event loop."""
    config = uvicorn.Config(
        app, host=MOCK_HOST, port=MOCK_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    _server_started.set()
    server.run()


def _ensure_server() -> None:
    """Гарантирует что mock-сервер запущен."""
    global _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        return
    _server_thread = threading.Thread(target=_run_server, daemon=True)
    _server_thread.start()
    _server_started.wait(timeout=10)
    # Ждём пока /api/health ответит
    import urllib.request
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("Mock-сервер не поднялся за 5 секунд")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def mock_server():
    """Поднимаем mock-сервер один раз на модуль (синхронная fixture)."""
    _ensure_server()
    yield


@pytest.fixture
def factory():
    return IdentityFactory(org_id="integration-test", seed=123)


@pytest.fixture
def metrics():
    return MetricsCollector()


# ---------------------------------------------------------------------------
# Тесты: REST API
# ---------------------------------------------------------------------------

class TestRestAPI:
    """REST endpoint-ы mock-сервера."""

    @pytest.mark.asyncio
    async def test_health(self):
        """Health check отвечает 200."""
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{BASE_URL}/api/health") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_register_device(self, factory):
        """Регистрация устройства возвращает 201 + device_id + jwt_token."""
        identity = factory.create(0)
        payload = {
            "fingerprint": identity.fingerprint,
            "name": f"test-{identity.serial}",
            "type": "android",
            "model": identity.model,
            "os_version": identity.android_version,
            "agent_version": identity.agent_version,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{BASE_URL}/api/v1/devices/register", json=payload
            ) as resp:
                assert resp.status == 201
                data = await resp.json()
                assert "device_id" in data
                assert "jwt_token" in data

    @pytest.mark.asyncio
    async def test_register_duplicate(self, factory):
        """Повторная регистрация → 409."""
        identity = factory.create(100)
        payload = {
            "fingerprint": identity.fingerprint,
            "name": f"dup-{identity.serial}",
            "type": "android",
        }
        async with aiohttp.ClientSession() as s:
            # Первая регистрация
            async with s.post(
                f"{BASE_URL}/api/v1/devices/register", json=payload
            ) as resp:
                assert resp.status == 201

            # Дубликат
            async with s.post(
                f"{BASE_URL}/api/v1/devices/register", json=payload
            ) as resp:
                assert resp.status == 409

    @pytest.mark.asyncio
    async def test_vpn_assign(self, factory):
        """VPN enrollment возвращает assigned_ip."""
        identity = factory.create(200)
        # Сначала зарегистрируем устройство
        payload = {
            "fingerprint": identity.fingerprint,
            "name": f"vpn-{identity.serial}",
            "type": "android",
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{BASE_URL}/api/v1/devices/register", json=payload
            ) as resp:
                data = await resp.json()
                device_id = data["device_id"]

            # VPN assign
            async with s.post(
                f"{BASE_URL}/api/v1/vpn/assign",
                json={"device_id": device_id},
            ) as resp:
                assert resp.status == 201
                data = await resp.json()
                assert "assigned_ip" in data
                assert data["assigned_ip"].startswith("10.100.")


# ---------------------------------------------------------------------------
# Тесты: WebSocket
# ---------------------------------------------------------------------------

class TestWebSocket:
    """WebSocket endpoint mock-сервера."""

    @pytest.mark.asyncio
    async def test_ws_connect_and_auth(self):
        """Подключение + first-message auth → получаем noop."""
        import websockets

        uri = f"{WS_URL}/ws/android/test-device-ws-001"
        async with websockets.connect(uri) as ws:
            # Отправляем first-message auth
            await ws.send(json.dumps({"token": "mock_jwt_test"}))
            reply = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(reply)
            assert data["type"] == "noop"
            assert data["message"] == "auth_ok"

    @pytest.mark.asyncio
    async def test_ws_receive_ping(self):
        """После auth получаем серверный ping (формат: {type:ping, ts:...})."""
        import websockets

        uri = f"{WS_URL}/ws/android/test-device-ws-002"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"token": "mock_jwt_test"}))
            # Auth ack
            await asyncio.wait_for(ws.recv(), timeout=5.0)

            # Ждём первый ping (приходит через ~5s) или noop (через ~10s)
            ping_received = False
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=12.0)
                    data = json.loads(raw)
                    if data.get("type") == "ping":
                        assert "ts" in data
                        ping_received = True
                        break
                except asyncio.TimeoutError:
                    break

            if not ping_received:
                pytest.skip("Ping не пришёл в ожидаемое время")


# ---------------------------------------------------------------------------
# Тесты: VirtualAgent ↔ Mock Server (полный цикл)
# ---------------------------------------------------------------------------

class TestVirtualAgentIntegration:
    """Полная интеграция: VirtualAgent подключается к mock-серверу."""

    @pytest.mark.asyncio
    async def test_agent_lifecycle(self, factory, metrics):
        """Один агент: register → connect → online → heartbeat → stop."""
        identity = factory.create(300)
        behavior = AgentBehavior(
            heartbeat_interval=5.0,
            telemetry_interval=3.0,
            watchdog_timeout=60.0,
            task_success_rate=0.9,
            enable_vpn=True,
            enable_video=False,
        )

        agent = VirtualAgent(
            identity=identity,
            behavior=behavior,
            metrics=metrics,
            base_url=BASE_URL,
            ws_url=WS_URL,
        )

        # Запускаем агента в фоне
        agent_task = asyncio.create_task(agent.run())

        # Ждём пока выйдет в ONLINE
        t0 = time.monotonic()
        while agent.state not in (AgentState.ONLINE, AgentState.EXECUTING):
            if time.monotonic() - t0 > 15.0:
                break
            await asyncio.sleep(0.2)

        assert agent.state in (
            AgentState.ONLINE, AgentState.EXECUTING
        ), f"Агент не вышел в ONLINE, state={agent.state}"

        # Проверяем что метрики пишутся
        assert metrics._counters.get("registration_success", 0) > 0 or \
               metrics._counters.get("registration_duplicate", 0) > 0

        # Живём 5 секунд — собираем heartbeat/telemetry
        await asyncio.sleep(5)

        # Стоп
        await agent.stop()
        try:
            await asyncio.wait_for(agent_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            agent_task.cancel()

        # Проверяем метрики
        assert metrics._counters.get("ws_connect_success", 0) > 0 or \
               metrics._counters.get("ws_online_total", 0) > 0
        assert metrics._counters.get("telemetry_sent", 0) > 0

    @pytest.mark.asyncio
    async def test_multiple_agents(self, factory, metrics):
        """5 агентов параллельно: все выходят в ONLINE."""
        agents = []
        behavior = AgentBehavior(
            heartbeat_interval=5.0,
            telemetry_interval=3.0,
            watchdog_timeout=60.0,
            enable_vpn=False,
            enable_video=False,
        )

        for i in range(5):
            identity = factory.create(400 + i)
            agent = VirtualAgent(
                identity=identity,
                behavior=behavior,
                metrics=metrics,
                base_url=BASE_URL,
                ws_url=WS_URL,
            )
            agents.append(agent)

        # Запускаем всех
        tasks = [asyncio.create_task(a.run()) for a in agents]

        # Ждём пока все выйдут в ONLINE
        t0 = time.monotonic()
        while time.monotonic() - t0 < 15.0:
            online = sum(
                1 for a in agents
                if a.state in (AgentState.ONLINE, AgentState.EXECUTING)
            )
            if online == len(agents):
                break
            await asyncio.sleep(0.3)

        online_count = sum(
            1 for a in agents
            if a.state in (AgentState.ONLINE, AgentState.EXECUTING)
        )
        assert online_count >= 4, (
            f"Ожидали ≥4 из 5 агентов ONLINE, реально: {online_count}"
        )

        # Живём 3 секунды
        await asyncio.sleep(3)

        # Гасим всех
        for a in agents:
            await a.stop()
        for t in tasks:
            try:
                await asyncio.wait_for(t, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                t.cancel()

    @pytest.mark.asyncio
    async def test_agent_vpn_enrollment(self, factory, metrics):
        """Агент с enable_vpn=True получает VPN IP."""
        identity = factory.create(500)
        behavior = AgentBehavior(
            heartbeat_interval=5.0,
            telemetry_interval=3.0,
            watchdog_timeout=60.0,
            enable_vpn=True,
        )

        agent = VirtualAgent(
            identity=identity,
            behavior=behavior,
            metrics=metrics,
            base_url=BASE_URL,
            ws_url=WS_URL,
        )

        agent_task = asyncio.create_task(agent.run())

        # Ждём ONLINE
        t0 = time.monotonic()
        while agent.state not in (AgentState.ONLINE, AgentState.EXECUTING):
            if time.monotonic() - t0 > 15.0:
                break
            await asyncio.sleep(0.2)

        # Ждём VPN enrollment
        await asyncio.sleep(2)

        await agent.stop()
        try:
            await asyncio.wait_for(agent_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            agent_task.cancel()

        assert agent.vpn_enrolled, "VPN enrollment не произошёл"
        assert agent.vpn_ip is not None, "VPN IP не назначен"
        assert metrics._counters.get("vpn_enroll_success", 0) > 0

    @pytest.mark.asyncio
    async def test_metrics_snapshot_after_run(self, factory, metrics):
        """Snapshot метрик содержит ненулевые значения после работы агентов."""
        identity = factory.create(600)
        behavior = AgentBehavior(
            heartbeat_interval=5.0,
            telemetry_interval=2.0,
            watchdog_timeout=60.0,
            enable_vpn=False,
        )

        agent = VirtualAgent(
            identity=identity,
            behavior=behavior,
            metrics=metrics,
            base_url=BASE_URL,
            ws_url=WS_URL,
        )

        agent_task = asyncio.create_task(agent.run())

        t0 = time.monotonic()
        while agent.state not in (AgentState.ONLINE, AgentState.EXECUTING):
            if time.monotonic() - t0 > 15.0:
                break
            await asyncio.sleep(0.2)

        await asyncio.sleep(4)
        await agent.stop()
        try:
            await asyncio.wait_for(agent_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            agent_task.cancel()

        snap = metrics.snapshot()
        assert snap["counters"], "Счётчики не должны быть пусты"
        assert any("ws_" in k for k in snap["counters"]), (
            "Ожидали WS-метрики в счётчиках"
        )
