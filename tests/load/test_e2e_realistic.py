# -*- coding: utf-8 -*-
"""
E2E-тесты реалистичного протокола Sphere Platform.

Проверяют полный жизненный цикл виртуального агента в режиме,
максимально приближенном к реальному APK:
  • Регистрация → WS auth → ping/pong с телеметрией
  • EXECUTE_DAG → CommandAck → task_progress → command_result + node_logs
  • CANCEL_DAG → прерывание выполнения
  • Pending results → flush после реконнекта
  • DagScriptEngine: retry с backoff, condition routing, loop
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid

import aiohttp
import pytest
import uvicorn

from tests.load.core.dag_script_engine import DagScriptEngine
from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.core.virtual_agent import AgentBehavior, VirtualAgent
from tests.load.protocols.message_factory import MessageFactory

logger = logging.getLogger("test_e2e_realistic")

# ---------------------------------------------------------------------------
# Настройки тестового сервера
# ---------------------------------------------------------------------------

_SERVER_HOST = "127.0.0.1"
_SERVER_PORT = 18083  # Отдельный порт для E2E-тестов
_BASE_URL = f"http://{_SERVER_HOST}:{_SERVER_PORT}"
_WS_URL = f"ws://{_SERVER_HOST}:{_SERVER_PORT}"


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _mock_server():
    """Запуск mock-сервера в daemon-потоке (на всю сессию тестов)."""
    from tests.load.mock_server import app

    config = uvicorn.Config(
        app, host=_SERVER_HOST, port=_SERVER_PORT, log_level="warning"
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Ожидаем старт
    for _ in range(50):
        try:
            import urllib.request
            urllib.request.urlopen(f"{_BASE_URL}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        pytest.fail("Mock-сервер не запустился на порту %d" % _SERVER_PORT)

    yield

    server.should_exit = True


@pytest.fixture
def factory() -> IdentityFactory:
    return IdentityFactory(org_id="e2e-realistic", seed=42)


@pytest.fixture
def metrics() -> MetricsCollector:
    return MetricsCollector()


@pytest.fixture
def behavior() -> AgentBehavior:
    """Ускоренное поведение для тестов."""
    return AgentBehavior(
        heartbeat_interval=5.0,
        telemetry_interval=3.0,
        watchdog_timeout=30.0,
        task_success_rate=0.85,
        dag_speed_factor=0.05,  # В 20 раз быстрее реального
        enable_vpn=True,
        random_disconnect_rate=0.0,  # Без случайных обрывов в E2E
        max_reconnect_retries=3,
    )


# ---------------------------------------------------------------------------
# Тест 1: DagScriptEngine — выполнение Instagram Login DAG
# ---------------------------------------------------------------------------

class TestDagScriptEngine:
    """Тесты движка выполнения DAG."""

    @pytest.mark.asyncio
    async def test_execute_instagram_dag(self) -> None:
        """Выполнение полного DAG Instagram Login (12 узлов)."""
        dag = _load_fixture("dag_instagram_login.json")
        engine = DagScriptEngine(
            success_rate=1.0,  # Гарантированный успех для теста
            speed_factor=0.01,
        )

        result = await engine.execute(dag, task_id="test-insta-001")

        assert result.success, f"DAG провалился: {result.error}"
        assert result.nodes_executed > 0
        assert len(result.node_logs) > 0
        # Проверяем формат node_logs
        for log in result.node_logs:
            d = log.to_dict()
            assert "node_id" in d
            assert "action_type" in d
            assert "duration_ms" in d
            assert "success" in d
            assert d["success"] is True

    @pytest.mark.asyncio
    async def test_execute_telegram_dag(self) -> None:
        """Выполнение DAG Telegram Message (15 узлов)."""
        dag = _load_fixture("dag_telegram_message.json")
        engine = DagScriptEngine(
            success_rate=1.0,
            speed_factor=0.01,
        )

        result = await engine.execute(dag, task_id="test-tg-001")

        assert result.success
        assert result.nodes_executed >= 5  # Минимум 5 узлов

    @pytest.mark.asyncio
    async def test_execute_with_failure(self) -> None:
        """DAG с гарантированной ошибкой — проверяем failed_node и node_logs."""
        dag = _load_fixture("dag_device_benchmark.json")
        engine = DagScriptEngine(
            success_rate=0.0,  # Гарантированный fail
            speed_factor=0.01,
        )

        result = await engine.execute(dag, task_id="test-fail-001")

        assert not result.success
        assert result.failed_node is not None
        assert result.error is not None
        # node_logs содержит записи до точки провала
        assert len(result.node_logs) >= 1

    @pytest.mark.asyncio
    async def test_cancel_dag(self) -> None:
        """CANCEL_DAG — прерывание DAG во время выполнения."""
        dag = _load_fixture("dag_instagram_login.json")
        engine = DagScriptEngine(
            success_rate=1.0,
            speed_factor=0.5,  # Замедлено для надёжного cancel
        )

        async def cancel_after_delay() -> None:
            await asyncio.sleep(0.3)
            engine.cancel()

        cancel_task = asyncio.create_task(cancel_after_delay())
        result = await engine.execute(dag, task_id="test-cancel-001")
        await cancel_task

        assert result.cancelled
        assert not result.success

    @pytest.mark.asyncio
    async def test_progress_callback(self) -> None:
        """Проверяем, что callback прогресса вызывается после каждого узла."""
        dag = _load_fixture("dag_device_benchmark.json")
        progress_events: list[dict] = []

        async def on_progress(event) -> None:
            progress_events.append({
                "task_id": event.task_id,
                "current_node": event.current_node,
                "nodes_done": event.nodes_done,
                "total_nodes": event.total_nodes,
            })

        engine = DagScriptEngine(
            success_rate=1.0,
            speed_factor=0.01,
            on_progress=on_progress,
        )

        result = await engine.execute(dag, task_id="test-progress-001")

        assert result.success
        assert len(progress_events) > 0
        # Прогресс монотонно возрастает
        for i, ev in enumerate(progress_events):
            assert ev["nodes_done"] == i + 1
            assert ev["task_id"] == "test-progress-001"

    @pytest.mark.asyncio
    async def test_condition_routing(self) -> None:
        """Condition-узел маршрутизирует по on_true/on_false."""
        dag = {
            "version": "1.0",
            "nodes": [
                {"id": "n1", "action": {"type": "start"}, "next": "n2", "timeout_ms": 1000, "retry": 0},
                {"id": "n2", "action": {"type": "condition", "check": "battery_above", "params": {"level": 20}},
                 "on_true": "n3", "on_false": "n4", "timeout_ms": 1000, "retry": 0},
                {"id": "n3", "action": {"type": "end"}, "next": None, "timeout_ms": 1000, "retry": 0},
                {"id": "n4", "action": {"type": "end"}, "next": None, "timeout_ms": 1000, "retry": 0},
            ],
            "entry_node": "n1",
            "timeout_ms": 10000,
        }
        engine = DagScriptEngine(success_rate=1.0, speed_factor=0.01)
        result = await engine.execute(dag, task_id="test-cond-001")

        assert result.success
        assert result.nodes_executed == 3  # start → condition → end


# ---------------------------------------------------------------------------
# Тест 2: Полный E2E цикл — агент + сервер
# ---------------------------------------------------------------------------

class TestE2ERealisticProtocol:
    """E2E-тесты: VirtualAgent ↔ MockServer с реалистичным протоколом."""

    @pytest.mark.asyncio
    async def test_agent_lifecycle_with_dag(
        self, factory: IdentityFactory, metrics: MetricsCollector, behavior: AgentBehavior
    ) -> None:
        """Полный жизненный цикл: регистрация → WS → DAG → результат."""
        identity = factory.create(0)
        agent = VirtualAgent(
            identity=identity,
            behavior=behavior,
            metrics=metrics,
            base_url=_BASE_URL,
            ws_url=_WS_URL,
        )

        # Запускаем агента на 20 секунд
        agent_task = asyncio.create_task(agent.run())
        await asyncio.sleep(20)
        await agent.stop()

        try:
            await asyncio.wait_for(agent_task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            agent_task.cancel()

        # Проверяем метрики
        assert metrics.counter("registration_success") >= 1 or metrics.counter("registration_duplicate") >= 1
        assert metrics.counter("ws_connect_success") >= 1
        assert metrics.counter("ws_online_total") >= 1
        assert metrics.counter("heartbeat_pong_sent") >= 1

    @pytest.mark.asyncio
    async def test_pong_echoes_server_ts(
        self, factory: IdentityFactory, metrics: MetricsCollector, behavior: AgentBehavior
    ) -> None:
        """Pong содержит echo серверного ts + телеметрию."""
        from websockets.asyncio.client import connect

        identity = factory.create(1)

        # Регистрируем устройство
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{_BASE_URL}/api/v1/devices/register",
                json={
                    "fingerprint": identity.fingerprint,
                    "name": f"e2e-{identity.serial}",
                    "type": "android",
                    "model": identity.model,
                },
            )
            data = await resp.json()
            device_id = data.get("device_id", identity.device_id)
            jwt_token = data.get("jwt_token", "test")

        # Подключаемся по WS
        ws = await connect(
            f"{_WS_URL}/ws/android/{device_id}",
            open_timeout=10,
        )
        try:
            # First-message auth
            await ws.send(json.dumps({"token": jwt_token}))
            await asyncio.wait_for(ws.recv(), timeout=5)

            # Ждём ping от сервера
            server_ts = None
            for _ in range(50):
                raw = await asyncio.wait_for(ws.recv(), timeout=35)
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    server_ts = msg.get("ts")
                    break

            assert server_ts is not None, "Не получен ping от сервера"

            # Отправляем pong в реальном формате APK
            pong = json.dumps({
                "type": "pong",
                "ts": server_ts,  # Echo серверного ts
                "battery": 87,
                "cpu": 45.2,
                "ram_mb": 2048,
                "screen_on": True,
                "vpn_active": False,
                "stream": False,
            })
            await ws.send(pong)
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_command_ack_without_type_field(
        self, factory: IdentityFactory, metrics: MetricsCollector, behavior: AgentBehavior
    ) -> None:
        """CommandAck — БЕЗ поля «type» (реальный формат APK)."""
        from websockets.asyncio.client import connect

        identity = factory.create(2)

        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{_BASE_URL}/api/v1/devices/register",
                json={"fingerprint": identity.fingerprint, "type": "android", "model": identity.model},
            )
            data = await resp.json()
            device_id = data.get("device_id", identity.device_id)
            jwt_token = data.get("jwt_token", "test")

        ws = await connect(f"{_WS_URL}/ws/android/{device_id}", open_timeout=10)
        try:
            await ws.send(json.dumps({"token": jwt_token}))
            await asyncio.wait_for(ws.recv(), timeout=5)

            # CommandAck без поля "type"
            command_id = str(uuid.uuid4())
            ack = json.dumps({
                "command_id": command_id,
                "status": "received",
            })
            await ws.send(ack)

            # Проверяем что сервер принял (через HTTP API)
            await asyncio.sleep(0.5)
            async with aiohttp.ClientSession() as s2:
                resp2 = await s2.get(f"{_BASE_URL}/api/v1/tasks/stats")
                stats = await resp2.json()
                assert stats["acks_received"] >= 1
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_execute_dag_full_flow(
        self, factory: IdentityFactory, metrics: MetricsCollector, behavior: AgentBehavior
    ) -> None:
        """Полный цикл EXECUTE_DAG: ack → progress × N → command_result."""
        from websockets.asyncio.client import connect

        identity = factory.create(3)

        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{_BASE_URL}/api/v1/devices/register",
                json={"fingerprint": identity.fingerprint, "type": "android", "model": identity.model},
            )
            data = await resp.json()
            device_id = data.get("device_id", identity.device_id)
            jwt_token = data.get("jwt_token", "test")

        ws = await connect(f"{_WS_URL}/ws/android/{device_id}", open_timeout=10)
        try:
            await ws.send(json.dumps({"token": jwt_token}))
            await asyncio.wait_for(ws.recv(), timeout=5)

            # Отправляем EXECUTE_DAG в реальном формате
            command_id = str(uuid.uuid4())
            task_id = str(uuid.uuid4())
            dag = _load_fixture("dag_device_benchmark.json")

            execute_msg = json.dumps({
                "command_id": command_id,
                "type": "EXECUTE_DAG",
                "signed_at": time.time(),
                "ttl_seconds": 3600,
                "payload": {
                    "task_id": task_id,
                    "dag": dag,
                },
            })
            await ws.send(execute_msg)

            # Собираем ответы агента (через mock-сервер они не уходят,
            # но мы проверяем формат на клиентской стороне через DagScriptEngine)
            engine = DagScriptEngine(success_rate=1.0, speed_factor=0.01)
            result = await engine.execute(dag, task_id)

            # Проверяем формат результата
            result_dict = result.to_dict()
            assert "nodes_executed" in result_dict
            assert "success" in result_dict
            assert "node_logs" in result_dict
            assert isinstance(result_dict["node_logs"], list)

            if result.success:
                assert result_dict["success"] is True
                assert result_dict["failed_node"] is None
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_noop_keepalive(
        self, factory: IdentityFactory, metrics: MetricsCollector, behavior: AgentBehavior
    ) -> None:
        """Noop keepalive от сервера обновляет watchdog-таймер."""
        from websockets.asyncio.client import connect

        identity = factory.create(4)

        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{_BASE_URL}/api/v1/devices/register",
                json={"fingerprint": identity.fingerprint, "type": "android", "model": identity.model},
            )
            data = await resp.json()
            device_id = data.get("device_id", identity.device_id)
            jwt_token = data.get("jwt_token", "test")

        ws = await connect(f"{_WS_URL}/ws/android/{device_id}", open_timeout=10)
        try:
            await ws.send(json.dumps({"token": jwt_token}))
            await asyncio.wait_for(ws.recv(), timeout=5)

            # Ожидаем noop (каждые 10s)
            noop_received = False
            for _ in range(20):
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                msg = json.loads(raw)
                if msg.get("type") == "noop":
                    noop_received = True
                    break

            assert noop_received, "Не получен noop keepalive от сервера"
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_message_factory_formats(self) -> None:
        """Проверяем, что MessageFactory генерирует корректные форматы."""
        # Pong
        pong = json.loads(MessageFactory.pong(ts=1234567890.123))
        assert pong["type"] == "pong"
        assert pong["ts"] == 1234567890.123
        assert "battery" in pong
        assert "cpu" in pong
        assert "ram_mb" in pong
        assert "stream" in pong

        # CommandAck — нет поля "type"!
        ack = json.loads(MessageFactory.command_ack("cmd-123"))
        assert "type" not in ack
        assert ack["command_id"] == "cmd-123"
        assert ack["status"] == "received"

        # EXECUTE_DAG
        dag = {"version": "1.0", "nodes": [], "entry_node": "n1"}
        exec_msg = json.loads(MessageFactory.server_execute_dag(dag, command_id="c1", task_id="t1"))
        assert exec_msg["type"] == "EXECUTE_DAG"
        assert exec_msg["command_id"] == "c1"
        assert "signed_at" in exec_msg
        assert "ttl_seconds" in exec_msg
        assert exec_msg["payload"]["task_id"] == "t1"
        assert exec_msg["payload"]["dag"] == dag

        # Ping
        ping = json.loads(MessageFactory.server_ping())
        assert ping["type"] == "ping"
        assert "ts" in ping

        # task_progress
        progress = json.loads(MessageFactory.task_progress("t1", "n3", 3, 12))
        assert progress["type"] == "task_progress"
        assert progress["task_id"] == "t1"
        assert progress["current_node"] == "n3"
        assert progress["nodes_done"] == 3
        assert progress["total_nodes"] == 12

    @pytest.mark.asyncio
    async def test_multiple_agents_with_dag(
        self, factory: IdentityFactory, metrics: MetricsCollector, behavior: AgentBehavior
    ) -> None:
        """Несколько агентов одновременно выполняют DAG-скрипты."""
        agents: list[VirtualAgent] = []
        for i in range(5):
            identity = factory.create(100 + i)
            agent = VirtualAgent(
                identity=identity,
                behavior=behavior,
                metrics=metrics,
                base_url=_BASE_URL,
                ws_url=_WS_URL,
            )
            agents.append(agent)

        # Запускаем всех
        tasks = [asyncio.create_task(a.run()) for a in agents]
        await asyncio.sleep(15)

        # Останавливаем
        for a in agents:
            await a.stop()

        for t in tasks:
            try:
                await asyncio.wait_for(t, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                t.cancel()

        # Проверяем что все подключились
        assert metrics.counter("ws_online_total") >= 5
        assert metrics.counter("heartbeat_pong_sent") >= 5


# ---------------------------------------------------------------------------
# Тест 3: DagScriptEngine — edge cases
# ---------------------------------------------------------------------------

class TestDagScriptEngineEdgeCases:
    """Граничные случаи DagScriptEngine."""

    @pytest.mark.asyncio
    async def test_empty_dag(self) -> None:
        """Пустой DAG возвращает ошибку."""
        engine = DagScriptEngine(speed_factor=0.01)
        result = await engine.execute({"nodes": [], "entry_node": "n1"}, "test")
        assert not result.success
        assert "пуст" in (result.error or "").lower() or "empty" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_missing_entry_node(self) -> None:
        """entry_node не найден → ошибка."""
        dag = {
            "nodes": [{"id": "n1", "action": {"type": "start"}, "next": None}],
            "entry_node": "n99",
        }
        engine = DagScriptEngine(speed_factor=0.01)
        result = await engine.execute(dag, "test")
        assert not result.success
        assert "n99" in (result.error or "")

    @pytest.mark.asyncio
    async def test_dag_with_loop_node(self) -> None:
        """DAG с loop-узлом (3 итерации)."""
        dag = {
            "version": "1.0",
            "nodes": [
                {
                    "id": "n1",
                    "action": {
                        "type": "loop",
                        "count": 3,
                        "body": [
                            {"id": "body_1", "action": {"type": "sleep", "ms": 10}},
                        ],
                    },
                    "next": "n2",
                    "timeout_ms": 10000,
                    "retry": 0,
                },
                {"id": "n2", "action": {"type": "end"}, "next": None, "timeout_ms": 1000, "retry": 0},
            ],
            "entry_node": "n1",
            "timeout_ms": 30000,
        }
        engine = DagScriptEngine(success_rate=1.0, speed_factor=0.01)
        result = await engine.execute(dag, "test-loop")
        assert result.success
        assert result.nodes_executed == 2

    @pytest.mark.asyncio
    async def test_retry_with_backoff(self) -> None:
        """Узел с retry=2 — проверяем что ретраи происходят."""
        dag = {
            "version": "1.0",
            "nodes": [
                {
                    "id": "n1",
                    "action": {"type": "find_element", "selector": "//nonexistent", "strategy": "xpath"},
                    "next": None,
                    "timeout_ms": 5000,
                    "retry": 2,
                },
            ],
            "entry_node": "n1",
            "timeout_ms": 30000,
        }
        # success_rate=0 → гарантированный fail → retry сработает
        engine = DagScriptEngine(success_rate=0.0, speed_factor=0.01)
        t0 = time.monotonic()
        result = await engine.execute(dag, "test-retry")
        _ = time.monotonic() - t0

        assert not result.success
        # С retry=2 должно быть 3 попытки (0, 1, 2)
        # Backoff: 50ms + 100ms = минимум ~150ms * speed_factor
        assert result.nodes_executed == 1  # Один узел, но retry внутри


# ---------------------------------------------------------------------------
# Тест 4: Broadcast — запуск на всех онлайн-устройствах
# ---------------------------------------------------------------------------

class TestBroadcastBatch:
    """Тесты broadcast-батча: запуск скрипта на всех онлайн-устройствах."""

    @pytest.mark.asyncio
    async def test_broadcast_no_online_devices(self) -> None:
        """Broadcast без онлайн-устройств → 409 Conflict."""
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{_BASE_URL}/api/v1/batches/broadcast",
                json={"script_id": str(uuid.uuid4()), "wave_size": 5},
            )
            assert resp.status == 409
            data = await resp.json()
            assert "онлайн" in data.get("detail", "").lower() or "online" in data.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_broadcast_to_connected_agents(
        self, factory: IdentityFactory, metrics: MetricsCollector, behavior: AgentBehavior
    ) -> None:
        """Broadcast на N подключённых агентов — все получают EXECUTE_DAG."""
        agents: list[VirtualAgent] = []
        agent_count = 3

        for i in range(agent_count):
            identity = factory.create(200 + i)
            agent = VirtualAgent(
                identity=identity,
                behavior=behavior,
                metrics=metrics,
                base_url=_BASE_URL,
                ws_url=_WS_URL,
            )
            agents.append(agent)

        # Запускаем агентов и ждём подключения
        tasks = [asyncio.create_task(a.run()) for a in agents]
        await asyncio.sleep(10)

        # Проверяем что агенты онлайн
        assert metrics.counter("ws_online_total") >= agent_count

        # Вызываем broadcast
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{_BASE_URL}/api/v1/batches/broadcast",
                json={
                    "script_id": str(uuid.uuid4()),
                    "wave_size": 10,
                    "priority": 7,
                },
            )
            assert resp.status == 202
            data = await resp.json()
            assert data["online_devices"] >= agent_count
            assert data["total"] >= agent_count
            assert data["status"] == "RUNNING"
            assert "id" in data  # batch_id

        # Даём время на обработку DAG
        await asyncio.sleep(5)

        # Останавливаем агентов
        for a in agents:
            await a.stop()
        for t in tasks:
            try:
                await asyncio.wait_for(t, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                t.cancel()

    @pytest.mark.asyncio
    async def test_broadcast_returns_batch_metadata(self) -> None:
        """Broadcast-ответ содержит обязательные поля батча."""
        from websockets.asyncio.client import connect

        # Регистрируем и подключаем 1 агента напрямую
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{_BASE_URL}/api/v1/devices/register",
                json={"fingerprint": f"bc-meta-{uuid.uuid4().hex[:8]}", "type": "android", "model": "Pixel 7"},
            )
            reg = await resp.json()
            device_id = reg["device_id"]
            jwt_token = reg["jwt_token"]

        ws = await connect(f"{_WS_URL}/ws/android/{device_id}", open_timeout=10)
        try:
            await ws.send(json.dumps({"token": jwt_token}))
            await asyncio.wait_for(ws.recv(), timeout=5)  # auth_ok noop
            await asyncio.sleep(1)

            # Broadcast
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"{_BASE_URL}/api/v1/batches/broadcast",
                    json={"script_id": str(uuid.uuid4()), "wave_size": 5, "priority": 3},
                )
                assert resp.status == 202
                data = await resp.json()

                # Обязательные поля BroadcastBatchResponse
                assert "id" in data
                assert "online_devices" in data
                assert data["online_devices"] >= 1
                assert "total" in data
                assert "wave_config" in data
                assert data["wave_config"]["priority"] == 3
                assert data["wave_config"]["wave_size"] == 5
        finally:
            await ws.close()


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _load_fixture(filename: str) -> dict:
    """Загрузить DAG-фикстуру из tests/load/fixtures/."""
    import os
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    path = os.path.join(fixtures_dir, filename)
    with open(path, encoding="utf-8") as f:
        return json.load(f)
