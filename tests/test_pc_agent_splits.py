"""
TZ-08 SPLIT-2/3/4/5: тесты полной реализации PC Agent.
SPHERE-042/043/044/045

Покрытие:
  SPLIT-2  LDPlayerManager: list_instances (CSV-парсинг), launch (polling),
           quit, reboot, create, install_apk, run_app, exec_command, rc!=0 → RuntimeError
  SPLIT-2  CommandDispatcher: match/case роутинг, command_id в ответе, unknown type
  SPLIT-3  TelemetryReporter: _collect() → WorkstationTelemetry, executor,
           disk all=False, LDPlayer error не крашит
  SPLIT-4  AdbBridgeManager: sync_connections идемпотентен,
           shell() allowlist (injection chars → ValueError),
           list_devices() парсинг, FIX 8.3 offline reconnect
  SPLIT-5  TopologyReporter: report_on_connect() отправляет workstation_register,
           _get_local_ip() fallback=127.0.0.1
"""
from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Env fixtures (required для AgentConfig)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("SPHERE_SERVER_URL", "ws://localhost:8000")
    monkeypatch.setenv("SPHERE_AGENT_TOKEN", "test-secret")
    monkeypatch.setenv("SPHERE_WORKSTATION_ID", "wks-unit-test")


# ---------------------------------------------------------------------------
# SPLIT-2: LDPlayerManager
# ---------------------------------------------------------------------------

LIST2_OUTPUT = """\
0,Simulator0,0,0,1,0
1,Simulator1,1234,0,1,0
2,Simulator2,0,0,0,0
"""
#  cols: index, name, pid, ?, running(1/0), ?


@pytest.fixture()
def ldplayer():
    import agent.config as cfg_mod
    importlib.reload(cfg_mod)
    import agent.ldplayer as mod
    importlib.reload(mod)
    return mod.LDPlayerManager()


class TestLDPlayerListInstances:
    async def test_list_returns_all_instances(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock(return_value=LIST2_OUTPUT)):
            instances = await ldplayer.list_instances()
        assert len(instances) == 3

    async def test_running_instance_fields(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock(return_value=LIST2_OUTPUT)):
            instances = await ldplayer.list_instances()
        running = [i for i in instances if i.status.value == "running"]
        assert len(running) == 2  # index 0 and 1 have status_str == "1"

    async def test_pid_parsed(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock(return_value=LIST2_OUTPUT)):
            instances = await ldplayer.list_instances()
        i1 = next(i for i in instances if i.index == 1)
        assert i1.pid == 1234

    async def test_adb_port_formula(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock(return_value=LIST2_OUTPUT)):
            instances = await ldplayer.list_instances()
        for inst in instances:
            assert inst.adb_port == 5554 + inst.index * 2

    async def test_empty_output(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock(return_value="")):
            instances = await ldplayer.list_instances()
        assert instances == []

    async def test_nonzero_rc_raises(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock(side_effect=RuntimeError("rc=1"))):
            with pytest.raises(RuntimeError):
                await ldplayer.list_instances()


class TestLDPlayerLaunch:
    async def test_launch_succeeds_after_poll(self, ldplayer):
        from agent.models import InstanceStatus, LDPlayerInstance
        running_inst = LDPlayerInstance(index=0, name="Sim0", status=InstanceStatus.RUNNING, pid=100, adb_port=5554)
        with (
            patch.object(ldplayer, "_run", AsyncMock()),
            patch.object(ldplayer, "get_instance", AsyncMock(return_value=running_inst)),
        ):
            await ldplayer.launch(0)  # must not raise

    async def test_launch_timeout(self, ldplayer):
        from agent.models import InstanceStatus, LDPlayerInstance
        stopped = LDPlayerInstance(index=0, name="Sim0", status=InstanceStatus.STOPPED, adb_port=5554)
        with (
            patch.object(ldplayer, "_run", AsyncMock()),
            patch.object(ldplayer, "get_instance", AsyncMock(return_value=stopped)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            with pytest.raises(TimeoutError):
                await ldplayer.launch(0)


class TestLDPlayerActions:
    async def test_quit_calls_ldconsole(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock()) as mock_run:
            await ldplayer.quit(2)
        mock_run.assert_called_once_with("quit", "--index", "2", timeout=15.0)

    async def test_reboot_is_quit_then_launch(self, ldplayer):
        with (
            patch.object(ldplayer, "quit", AsyncMock()) as q,
            patch.object(ldplayer, "launch", AsyncMock()) as launch_mock,
            patch("asyncio.sleep", AsyncMock()),
        ):
            await ldplayer.reboot(1)
        q.assert_called_once_with(1)
        launch_mock.assert_called_once_with(1)

    async def test_create_returns_index(self, ldplayer):
        from agent.models import InstanceStatus, LDPlayerInstance
        new_inst = LDPlayerInstance(index=3, name="NewEmu", status=InstanceStatus.STOPPED, adb_port=5560)
        with (
            patch.object(ldplayer, "_run", AsyncMock()),
            patch.object(ldplayer, "list_instances", AsyncMock(return_value=[new_inst])),
        ):
            idx = await ldplayer.create("NewEmu")
        assert idx == 3

    async def test_create_not_found_raises(self, ldplayer):
        with (
            patch.object(ldplayer, "_run", AsyncMock()),
            patch.object(ldplayer, "list_instances", AsyncMock(return_value=[])),
        ):
            with pytest.raises(RuntimeError):
                await ldplayer.create("Ghost")

    async def test_install_apk_uses_timeout_120(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock()) as mock_run:
            await ldplayer.install_apk(0, "/tmp/app.apk")
        _, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 120.0

    async def test_run_app(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock()) as mock_run:
            await ldplayer.run_app(0, "com.example.app")
        assert "runapp" in mock_run.call_args[0]

    async def test_exec_command_returns_output(self, ldplayer):
        with patch.object(ldplayer, "_run", AsyncMock(return_value="OK")):
            out = await ldplayer.exec_command(0, "shell pm list packages")
        assert out == "OK"


# ---------------------------------------------------------------------------
# SPLIT-2: CommandDispatcher
# ---------------------------------------------------------------------------

@pytest.fixture()
def dispatcher():
    import agent.config as cfg_mod
    importlib.reload(cfg_mod)
    import agent.dispatcher as mod
    importlib.reload(mod)
    ld = MagicMock()
    adb = MagicMock()
    ws = MagicMock()
    ws.send = AsyncMock()
    d = mod.CommandDispatcher(ld, adb, ws_client=ws)
    return d, ld, adb, ws


class TestCommandDispatcher:
    async def test_ping_response(self, dispatcher):
        d, ld, adb, ws = dispatcher
        await d.dispatch({"type": "ping", "command_id": "cid1"})
        ws.send.assert_called_once()
        call_args = ws.send.call_args[0][0]
        assert call_args["status"] == "completed"
        assert call_args["result"]["pong"] is True
        assert call_args["command_id"] == "cid1"

    async def test_ld_list_returns_instances(self, dispatcher):
        from agent.models import InstanceStatus, LDPlayerInstance
        d, ld, adb, ws = dispatcher
        ld.list_instances = AsyncMock(return_value=[
            LDPlayerInstance(index=0, name="Sim0", status=InstanceStatus.RUNNING, adb_port=5554)
        ])
        await d.dispatch({"type": "ld_list", "command_id": "c2"})
        result = ws.send.call_args[0][0]["result"]
        assert isinstance(result, list)
        assert result[0]["index"] == 0

    async def test_ld_launch_dispatches(self, dispatcher):
        d, ld, adb, ws = dispatcher
        ld.launch = AsyncMock()
        await d.dispatch({"type": "ld_launch", "payload": {"index": 1}, "command_id": "c3"})
        ld.launch.assert_called_once_with(1)

    async def test_adb_shell_dispatches(self, dispatcher):
        d, ld, adb, ws = dispatcher
        adb.shell = AsyncMock(return_value="output")
        await d.dispatch({"type": "adb_shell", "payload": {"port": 5554, "command": "ls"}, "command_id": "c4"})
        adb.shell.assert_called_once_with(5554, "ls")

    async def test_error_sends_failed_status(self, dispatcher):
        d, ld, adb, ws = dispatcher
        ld.launch = AsyncMock(side_effect=RuntimeError("boom"))
        await d.dispatch({"type": "ld_launch", "payload": {"index": 0}, "command_id": "c5"})
        sent = ws.send.call_args[0][0]
        assert sent["status"] == "failed"
        assert "boom" in sent["error"]

    async def test_unknown_type_no_crash(self, dispatcher):
        d, ld, adb, ws = dispatcher
        # no command_id → no send, no exception
        await d.dispatch({"type": "totally_unknown"})
        ws.send.assert_not_called()

    async def test_no_command_id_no_send(self, dispatcher):
        d, ld, adb, ws = dispatcher
        await d.dispatch({"type": "ping"})  # no command_id
        ws.send.assert_not_called()


# ---------------------------------------------------------------------------
# SPLIT-3: TelemetryReporter
# ---------------------------------------------------------------------------

@pytest.fixture()
def telemetry_reporter():
    import agent.config as cfg_mod
    importlib.reload(cfg_mod)
    import agent.telemetry as mod
    importlib.reload(mod)
    ws = MagicMock()
    ws.send = AsyncMock()
    ldplayer = MagicMock()
    ldplayer.list_instances = AsyncMock(return_value=[])
    reporter = mod.TelemetryReporter(ws, ldplayer)
    return reporter, ws, ldplayer


class TestTelemetryReporter:
    async def test_collect_returns_telemetry(self, telemetry_reporter):
        from agent.models import WorkstationTelemetry
        reporter, ws, ldplayer = telemetry_reporter
        telemetry = await reporter._collect()
        assert isinstance(telemetry, WorkstationTelemetry)

    async def test_collect_has_cpu_percent(self, telemetry_reporter):
        reporter, ws, ldplayer = telemetry_reporter
        t = await reporter._collect()
        assert 0.0 <= t.cpu_percent <= 100.0

    async def test_collect_has_disks(self, telemetry_reporter):
        reporter, ws, ldplayer = telemetry_reporter
        t = await reporter._collect()
        # At least one disk (the OS partition)
        assert len(t.disk) >= 1

    async def test_collect_disk_free_ge_zero(self, telemetry_reporter):
        reporter, ws, ldplayer = telemetry_reporter
        t = await reporter._collect()
        for d in t.disk:
            assert d.free_gb >= 0.0

    async def test_collect_ldplayer_error_doesnt_crash(self, telemetry_reporter):
        reporter, ws, ldplayer = telemetry_reporter
        ldplayer.list_instances = AsyncMock(side_effect=RuntimeError("ldplayer down"))
        t = await reporter._collect()  # must not raise
        assert t.ldplayer_instances_running == 0

    async def test_collect_ldplayer_running_count(self, telemetry_reporter):
        from agent.models import InstanceStatus, LDPlayerInstance
        reporter, ws, ldplayer = telemetry_reporter
        ldplayer.list_instances = AsyncMock(return_value=[
            LDPlayerInstance(index=0, name="S0", status=InstanceStatus.RUNNING, adb_port=5554),
            LDPlayerInstance(index=1, name="S1", status=InstanceStatus.STOPPED, adb_port=5556),
        ])
        t = await reporter._collect()
        assert t.ldplayer_instances_running == 1

    async def test_run_loop_sends_once(self, telemetry_reporter):
        reporter, ws, ldplayer = telemetry_reporter

        # Stop the infinite loop by raising CancelledError from `send()` after
        # the first call. asyncio.sleep is patched to return instantly so the
        # loop body executes without blocking.
        async def stop_after_first_send(msg):
            raise asyncio.CancelledError("test stop")

        ws.send.side_effect = stop_after_first_send

        with patch("asyncio.sleep", AsyncMock(return_value=None)):
            with pytest.raises(asyncio.CancelledError):
                await reporter.run()

        ws.send.assert_called_once()
        msg = ws.send.call_args[0][0]
        assert msg["type"] == "workstation_telemetry"


# ---------------------------------------------------------------------------
# SPLIT-4: AdbBridgeManager
# ---------------------------------------------------------------------------

ADB_DEVICES_OUTPUT = """\
List of devices attached
127.0.0.1:5554\tdevice
127.0.0.1:5556\toffline
127.0.0.1:5558\tdevice
"""


@pytest.fixture()
def adb_bridge():
    import agent.config as cfg_mod
    importlib.reload(cfg_mod)
    import agent.adb_bridge as mod
    importlib.reload(mod)
    import agent.ldplayer as ld_mod
    importlib.reload(ld_mod)
    ldplayer = MagicMock()
    return mod.AdbBridgeManager(ldplayer), ldplayer, mod


class TestAdbListDevices:
    async def test_parse_devices(self, adb_bridge):
        bridge, ld, mod = adb_bridge
        with patch.object(bridge, "_adb", AsyncMock(return_value=ADB_DEVICES_OUTPUT)):
            devices = await bridge.list_devices()
        assert {"serial": "127.0.0.1:5554", "state": "device"} in devices
        assert {"serial": "127.0.0.1:5556", "state": "offline"} in devices
        assert len(devices) == 3

    async def test_adb_error_returns_empty(self, adb_bridge):
        bridge, ld, mod = adb_bridge
        with patch.object(bridge, "_adb", AsyncMock(side_effect=RuntimeError("no adb"))):
            devices = await bridge.list_devices()
        assert devices == []


class TestAdbShellSanitization:
    @pytest.mark.parametrize("cmd", [
        "ls; rm -rf /",
        "echo $HOME",
        "cmd | grep foo",
        "cmd & bg",
        "cmd`injection`",
        "cmd$(evil)",
        "cmd{evil}",
        "cmd\\path",
        "cmd < input",
        "cmd > output",
        "multi\nline",
        "test\r\n",
        "cmd #comment",
        "cmd~user",
        "cmd!bang",
        "cmd(paren)",
    ])
    async def test_injection_chars_raise(self, adb_bridge, cmd):
        bridge, ld, mod = adb_bridge
        with pytest.raises(ValueError, match="injection|запрещённые"):
            await bridge.shell(5554, cmd)

    async def test_safe_command_passes(self, adb_bridge):
        bridge, ld, mod = adb_bridge
        with patch.object(bridge, "_adb", AsyncMock(return_value="result")):
            out = await bridge.shell(5554, "pm list packages")
        assert out == "result"

    async def test_safe_command_with_path(self, adb_bridge):
        bridge, ld, mod = adb_bridge
        with patch.object(bridge, "_adb", AsyncMock(return_value="ok")):
            out = await bridge.shell(5554, "ls /sdcard/Download")
        assert out == "ok"


class TestAdbSyncConnections:
    async def test_connects_new_running_ports(self, adb_bridge):
        from agent.models import InstanceStatus, LDPlayerInstance
        bridge, ld, mod = adb_bridge
        ld.list_instances = AsyncMock(return_value=[
            LDPlayerInstance(index=0, name="S0", status=InstanceStatus.RUNNING, adb_port=5554),
        ])
        with (
            patch.object(bridge, "connect", AsyncMock(return_value=True)) as c,
            patch.object(bridge, "list_devices", AsyncMock(return_value=[])),
            patch.object(bridge, "disconnect", AsyncMock()),
        ):
            await bridge.sync_connections()
        c.assert_called_once_with(5554)
        assert 5554 in bridge._connected_ports

    async def test_does_not_reconnect_already_connected(self, adb_bridge):
        from agent.models import InstanceStatus, LDPlayerInstance
        bridge, ld, mod = adb_bridge
        bridge._connected_ports = {5554}
        ld.list_instances = AsyncMock(return_value=[
            LDPlayerInstance(index=0, name="S0", status=InstanceStatus.RUNNING, adb_port=5554),
        ])
        devices = [{"serial": "127.0.0.1:5554", "state": "device"}]
        with (
            patch.object(bridge, "connect", AsyncMock(return_value=True)) as c,
            patch.object(bridge, "list_devices", AsyncMock(return_value=devices)),
            patch.object(bridge, "disconnect", AsyncMock()),
        ):
            await bridge.sync_connections()
        c.assert_not_called()  # already connected + device state → no reconnect

    async def test_fix83_offline_port_reconnects(self, adb_bridge):
        """FIX 8.3: порт числится в running_ports, но ADB видит как offline → reconnect."""
        from agent.models import InstanceStatus, LDPlayerInstance
        bridge, ld, mod = adb_bridge
        bridge._connected_ports = {5554}
        ld.list_instances = AsyncMock(return_value=[
            LDPlayerInstance(index=0, name="S0", status=InstanceStatus.RUNNING, adb_port=5554),
        ])
        # ADB says port is offline
        devices = [{"serial": "127.0.0.1:5554", "state": "offline"}]
        with (
            patch.object(bridge, "connect", AsyncMock(return_value=True)) as c,
            patch.object(bridge, "list_devices", AsyncMock(return_value=devices)),
            patch.object(bridge, "disconnect", AsyncMock()) as disc,
        ):
            await bridge.sync_connections()
        disc.assert_called_with(5554)
        c.assert_called_with(5554)

    async def test_disconnects_stopped_instances(self, adb_bridge):
        from agent.models import InstanceStatus, LDPlayerInstance
        bridge, ld, mod = adb_bridge
        bridge._connected_ports = {5554}  # was running
        ld.list_instances = AsyncMock(return_value=[
            LDPlayerInstance(index=0, name="S0", status=InstanceStatus.STOPPED, adb_port=5554),
        ])
        with (
            patch.object(bridge, "connect", AsyncMock(return_value=True)),
            patch.object(bridge, "list_devices", AsyncMock(return_value=[])),
            patch.object(bridge, "disconnect", AsyncMock()) as disc,
        ):
            await bridge.sync_connections()
        disc.assert_called_with(5554)
        assert 5554 not in bridge._connected_ports


# ---------------------------------------------------------------------------
# SPLIT-5: TopologyReporter
# ---------------------------------------------------------------------------

@pytest.fixture()
def topology_reporter():
    import agent.config as cfg_mod
    importlib.reload(cfg_mod)
    import agent.topology as mod
    importlib.reload(mod)
    ws = MagicMock()
    ws.send = AsyncMock()
    ldplayer = MagicMock()
    ldplayer.list_instances = AsyncMock(return_value=[])
    reporter = mod.TopologyReporter(ws, ldplayer)
    return reporter, ws, ldplayer, mod


class TestTopologyReporter:
    async def test_report_on_connect_sends_workstation_register(self, topology_reporter):
        reporter, ws, ldplayer, mod = topology_reporter
        await reporter.report_on_connect()
        ws.send.assert_called_once()
        msg = ws.send.call_args[0][0]
        assert msg["type"] == "workstation_register"
        assert "payload" in msg

    async def test_payload_has_required_fields(self, topology_reporter):
        reporter, ws, ldplayer, mod = topology_reporter
        await reporter.report_on_connect()
        payload = ws.send.call_args[0][0]["payload"]
        for field in ["workstation_id", "hostname", "os_version", "ip_address", "instances", "agent_version"]:
            assert field in payload, f"Missing field: {field}"

    async def test_instances_list_populated(self, topology_reporter):
        from agent.models import InstanceStatus, LDPlayerInstance
        reporter, ws, ldplayer, mod = topology_reporter
        ldplayer.list_instances = AsyncMock(return_value=[
            LDPlayerInstance(index=0, name="Sim0", status=InstanceStatus.RUNNING, adb_port=5554),
            LDPlayerInstance(index=1, name="Sim1", status=InstanceStatus.STOPPED, adb_port=5556),
        ])
        await reporter.report_on_connect()
        payload = ws.send.call_args[0][0]["payload"]
        assert len(payload["instances"]) == 2
        assert payload["instances"][0]["index"] == 0

    async def test_get_local_ip_fallback(self, topology_reporter):
        reporter, ws, ldplayer, mod = topology_reporter
        with patch("socket.socket") as mock_sock:
            mock_sock.return_value.connect.side_effect = OSError("network unreachable")
            ip = reporter._get_local_ip()
        assert ip == "127.0.0.1"

    async def test_report_error_doesnt_propagate(self, topology_reporter):
        reporter, ws, ldplayer, mod = topology_reporter
        ldplayer.list_instances = AsyncMock(side_effect=RuntimeError("ldplayer crashed"))
        await reporter.report_on_connect()  # must not raise; error is logged

    async def test_android_serial_set_correctly(self, topology_reporter):
        from agent.models import InstanceStatus, LDPlayerInstance
        reporter, ws, ldplayer, mod = topology_reporter
        ldplayer.list_instances = AsyncMock(return_value=[
            LDPlayerInstance(index=0, name="Sim0", status=InstanceStatus.RUNNING, adb_port=5554),
        ])
        await reporter.report_on_connect()
        inst = ws.send.call_args[0][0]["payload"]["instances"][0]
        assert inst["android_serial"] == "127.0.0.1:5554"
