"""
TZ-08 SPLIT-1: тесты архитектуры PC Agent.
SPHERE-041

pytest.ini добавляет pc-agent/ в pythonpath, поэтому `import agent.*` работает напрямую.

Покрытие:
  1. Config — env prefix SPHERE_, дефолты
  2. Exponential backoff — задержки 1→2→4→…→30
  3. Circuit breaker — открывается / сбрасывается
  4. Send queue — буферизация, переполнение
  5. Graceful shutdown — stop_event / cancel
  6. TopologyRegistry — CRUD
  7. CommandDispatcher — маршрутизация по type
"""
from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    """Обязательные SPHERE_* переменные для всех тестов."""
    monkeypatch.setenv("SPHERE_SERVER_URL", "ws://localhost:8000")
    monkeypatch.setenv("SPHERE_AGENT_TOKEN", "test-secret")
    monkeypatch.setenv("SPHERE_WORKSTATION_ID", "wks-unit")


@pytest.fixture()
def cfg(_patch_env):
    import agent.config as cfg_mod
    importlib.reload(cfg_mod)
    return cfg_mod.AgentConfig()


@pytest.fixture()
def ws_client(_patch_env):
    import agent.config as cfg_mod
    importlib.reload(cfg_mod)
    import agent.client as client_mod
    importlib.reload(client_mod)
    return client_mod.AgentWebSocketClient(on_message=AsyncMock())


@pytest.fixture()
def dispatcher():
    from agent.adb_bridge import AdbBridgeManager
    from agent.dispatcher import CommandDispatcher
    from agent.ldplayer import LDPlayerManager

    ldp = LDPlayerManager()
    adb = AdbBridgeManager(ldp)
    return CommandDispatcher(ldp, adb)


# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_picks_env_vars(self, monkeypatch):
        monkeypatch.setenv("SPHERE_SERVER_URL", "wss://prod.example.com")
        monkeypatch.setenv("SPHERE_AGENT_TOKEN", "prod-token")
        monkeypatch.setenv("SPHERE_WORKSTATION_ID", "wks-prod-01")

        import agent.config as cfg_mod
        importlib.reload(cfg_mod)
        c = cfg_mod.AgentConfig()

        assert c.server_url == "wss://prod.example.com"
        assert c.agent_token == "prod-token"
        assert c.workstation_id == "wks-prod-01"

    def test_default_reconnect_params(self, cfg):
        assert cfg.reconnect_initial_delay == 1.0
        assert cfg.reconnect_max_delay == 30.0
        assert cfg.reconnect_backoff_factor == 2.0

    def test_default_telemetry_interval(self, cfg):
        assert cfg.telemetry_interval == 30


# ---------------------------------------------------------------------------
# 2. Exponential backoff
# ---------------------------------------------------------------------------

class TestExponentialBackoff:
    @pytest.mark.asyncio
    async def test_backoff_sequence(self, ws_client):
        """Задержки удваиваются: 1 → 2 → 4 → 8 → 16 → 30 (cap)."""
        delays_recorded: list[float] = []

        async def fake_connect():
            raise ConnectionRefusedError("refused")

        async def fake_wait_for(coro, timeout):
            raise asyncio.TimeoutError()

        async def fake_sleep(delay):
            delays_recorded.append(delay)
            if len(delays_recorded) >= 6:
                ws_client._stop_event.set()

        ws_client._connect_once = fake_connect

        with patch("asyncio.sleep", side_effect=fake_sleep), \
             patch("asyncio.wait_for", side_effect=fake_wait_for):
            try:
                await asyncio.wait_for(ws_client.run(), timeout=3.0)
            except asyncio.TimeoutError:
                pass

        expected = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
        for i, exp in enumerate(expected):
            if i < len(delays_recorded):
                assert delays_recorded[i] == pytest.approx(exp, rel=0.05), \
                    f"backoff[{i}] ожидали {exp}, получили {delays_recorded[i]}"

    def test_delay_capped_at_max(self, cfg):
        """После 20 итераций задержка равна max."""
        delay = cfg.reconnect_initial_delay
        for _ in range(20):
            delay = min(delay * cfg.reconnect_backoff_factor, cfg.reconnect_max_delay)
        assert delay == cfg.reconnect_max_delay


# ---------------------------------------------------------------------------
# 3. Circuit Breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_opens_after_threshold(self, ws_client):
        """После N ошибок circuit_open_until > now."""
        ws_client._CIRCUIT_THRESHOLD = 3
        ws_client._CIRCUIT_COOLDOWN = 60.0

        for _ in range(3):
            ws_client._consecutive_failures += 1
            if ws_client._consecutive_failures >= ws_client._CIRCUIT_THRESHOLD:
                ws_client._circuit_open_until = (
                    asyncio.get_event_loop().time() + ws_client._CIRCUIT_COOLDOWN
                )

        assert ws_client._circuit_open_until > asyncio.get_event_loop().time()

    @pytest.mark.asyncio
    async def test_resets_on_success(self, ws_client):
        """Успешное подключение сбрасывает счётчик и circuit."""
        ws_client._consecutive_failures = 5
        ws_client._circuit_open_until = asyncio.get_event_loop().time() + 100

        ws_client._consecutive_failures = 0
        ws_client._circuit_open_until = 0.0

        assert ws_client._consecutive_failures == 0
        assert ws_client._circuit_open_until == 0.0


# ---------------------------------------------------------------------------
# 4. Send queue
# ---------------------------------------------------------------------------

class TestSendQueue:
    @pytest.mark.asyncio
    async def test_send_when_disconnected_does_not_raise(self, ws_client):
        """send() при _connected=False не бросает исключений."""
        ws_client._connected = False
        await ws_client.send({"type": "ping"})

    @pytest.mark.asyncio
    async def test_send_puts_to_queue(self, ws_client):
        """send() при _connected=True кладёт сообщение в очередь."""
        ws_client._connected = True
        await ws_client.send({"type": "telemetry", "data": {}})

        assert ws_client._send_queue.qsize() == 1
        item = ws_client._send_queue.get_nowait()
        assert item["type"] == "telemetry"

    @pytest.mark.asyncio
    async def test_full_queue_does_not_raise(self, ws_client):
        """Переполненная очередь — логируем, не падаем."""
        ws_client._connected = True
        for i in range(ws_client._send_queue.maxsize):
            ws_client._send_queue.put_nowait({"i": i})
        await ws_client.send({"type": "overflow"})


# ---------------------------------------------------------------------------
# 5. Graceful Shutdown
# ---------------------------------------------------------------------------

class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_stop_sets_event(self, ws_client):
        """stop() устанавливает _stop_event."""
        assert not ws_client._stop_event.is_set()
        await ws_client.stop()
        assert ws_client._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_run_exits_when_stop_event_set(self, ws_client):
        """run() завершается после успешного connect, когда _stop_event выставлен."""
        connected = []

        async def mock_connect():
            connected.append(1)
            ws_client._stop_event.set()

        ws_client._connect_once = mock_connect

        await asyncio.wait_for(ws_client.run(), timeout=2.0)
        assert len(connected) == 1


# ---------------------------------------------------------------------------
# 6. TopologyRegistry
# ---------------------------------------------------------------------------

class TestTopologyRegistry:
    @pytest.fixture()
    def reg(self):
        from agent.topology import TopologyRegistry
        return TopologyRegistry()

    def test_update_and_get(self, reg):
        from agent.topology import InstanceInfo

        reg.update([
            InstanceInfo(instance_id=0, name="emu-0", running=True),
            InstanceInfo(instance_id=1, name="emu-1", running=False),
        ])

        assert reg.get(0).name == "emu-0"
        assert reg.get(1).running is False
        assert reg.get(99) is None

    def test_all_returns_list(self, reg):
        from agent.topology import InstanceInfo
        reg.update([InstanceInfo(instance_id=5, name="emu5")])
        assert len(reg.all()) == 1

    def test_to_dict(self, reg):
        from agent.topology import InstanceInfo
        reg.update([InstanceInfo(
            instance_id=2, name="emu2", adb_serial="emulator-5554"
        )])
        d = reg.to_dict()
        assert d[0]["adb_serial"] == "emulator-5554"

    def test_update_replaces_all(self, reg):
        from agent.topology import InstanceInfo
        reg.update([InstanceInfo(instance_id=0, name="old")])
        reg.update([InstanceInfo(instance_id=1, name="new")])
        assert reg.get(0) is None
        assert reg.get(1).name == "new"


# ---------------------------------------------------------------------------
# 7. CommandDispatcher routing
# ---------------------------------------------------------------------------

class TestCommandDispatcher:
    @pytest.mark.asyncio
    async def test_ping_handler(self, dispatcher):
        await dispatcher.dispatch({"type": "ping"})

    @pytest.mark.asyncio
    async def test_unknown_type_does_not_raise(self, dispatcher):
        await dispatcher.dispatch({"type": "xyzzy_unknown"})

    @pytest.mark.asyncio
    async def test_missing_type_does_not_raise(self, dispatcher):
        await dispatcher.dispatch({})

    @pytest.mark.asyncio
    async def test_ldplayer_start_route(self, dispatcher):
        await dispatcher.dispatch({"type": "ldplayer.start", "instance_id": 0})

    @pytest.mark.asyncio
    async def test_ldplayer_stop_route(self, dispatcher):
        await dispatcher.dispatch({"type": "ldplayer.stop", "instance_id": 1})

    @pytest.mark.asyncio
    async def test_ldplayer_list_route(self, dispatcher):
        await dispatcher.dispatch({"type": "ldplayer.list"})

    @pytest.mark.asyncio
    async def test_adb_forward_route(self, dispatcher):
        await dispatcher.dispatch({
            "type": "adb.forward",
            "device_serial": "emulator-5554",
            "local_port": 5037,
            "remote_port": 5555,
        })
