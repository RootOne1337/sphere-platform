"""Replay the observed running-but-unhealthy connector without touching Docker."""
import json

import pytest

from scripts import discovery_publisher as module


@pytest.fixture
def rig(tmp_path, monkeypatch):
    container = {"Id": "a" * 64, "Config": {"Labels": {
        "com.docker.compose.project": "isolated-pilot", "com.docker.compose.service": "cloudflare-quick"}},
        "State": {"Running": True, "Paused": False, "StartedAt": "first", "Health": {"Status": "unhealthy"}}}
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        if args[1] == "ps":
            return b"abc\n"
        if args[1] == "inspect":
            return json.dumps([container]).encode()
        assert args[1:] == ["restart", "--timeout", "10", "a" * 64]
        return b"ok"

    monkeypatch.setattr(module, "run_command", run)
    source = module.QuickTunnelSource("isolated-pilot", "cloudflare-quick")
    path = tmp_path / "recovery.json"

    def create():
        return module.QuickTunnelRecovery(source, path)

    return container, commands, path, create


def test_unhealthy_connector_recovers_after_persisted_grace_across_once_runs(rig):
    _, commands, _, create = rig
    assert create().reconcile(1000)["state"] == "waiting_for_recovery"
    assert create().reconcile(1179)["state"] == "waiting_for_recovery"
    assert create().reconcile(1180)["state"] == "connector_restarted"
    assert sum(c[1] == "restart" for c in commands) == 1


def test_persistent_outage_has_bounded_backoff_and_no_restart_storm(rig):
    container, commands, _, create = rig
    create().reconcile(1000)
    assert create().reconcile(1180)["retry_after"] == 1480
    container["State"]["StartedAt"] = "second"
    create().reconcile(1200)
    assert create().reconcile(1479)["state"] == "waiting_for_recovery"
    assert create().reconcile(1480)["retry_after"] == 2080
    assert create().reconcile(2080)["retry_after"] == 3280
    assert create().reconcile(3280)["retry_after"] == 5680
    assert create().reconcile(5680)["retry_after"] == 9280
    assert sum(c[1] == "restart" for c in commands) == 5


@pytest.mark.parametrize("health", ["healthy", "starting", None])
def test_healthy_or_initializing_connector_is_not_restarted_for_backend_outage(rig, health):
    container, commands, _, create = rig
    container["State"]["Health"]["Status"] = health
    create().reconcile(1000)
    create().reconcile(5000)
    assert not any(c[1] == "restart" for c in commands)


@pytest.mark.parametrize("case", ["foreign", "paused", "stopped"])
def test_never_restarts_foreign_paused_or_stopped_container(rig, case):
    container, commands, _, create = rig
    if case == "foreign":
        container["Config"]["Labels"]["com.docker.compose.project"] = "old-installation"
    else:
        container["State"]["Paused" if case == "paused" else "Running"] = case == "paused"
    with pytest.raises(module.PublicationError):
        create().reconcile(5000)
    assert not any(c[1] == "restart" for c in commands)


def test_recovery_during_grace_clears_failure_history(rig):
    container, commands, path, create = rig
    create().reconcile(1000)
    container["State"]["Health"]["Status"] = "healthy"
    create().reconcile(1100)
    assert "unhealthy_since" not in json.loads(path.read_text())
    container["State"]["Health"]["Status"] = "unhealthy"
    assert create().reconcile(1200)["retry_after"] == 1380
    assert not any(c[1] == "restart" for c in commands)


def test_journal_write_failure_prevents_mutation(rig, monkeypatch):
    _, commands, _, create = rig
    create().reconcile(1000)
    monkeypatch.setattr(module, "atomic_write", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        create().reconcile(1180)
    assert not any(c[1] == "restart" for c in commands)


def test_ambiguous_restart_observes_persisted_cooldown(rig, monkeypatch):
    _, _, _, create = rig
    create().reconcile(1000)
    original = module.run_command

    def ambiguous(args, **kwargs):
        if args[1] == "restart":
            raise TimeoutError("unknown CLI outcome")
        return original(args, **kwargs)

    monkeypatch.setattr(module, "run_command", ambiguous)
    with pytest.raises(TimeoutError):
        create().reconcile(1180)
    assert create().reconcile(1200)["retry_after"] == 1480


def test_recheck_prevents_restart_if_connector_changed(rig, monkeypatch):
    _, commands, _, create = rig
    create().reconcile(1000)
    subject = create()
    original = subject.source.inspect
    calls = 0

    def inspect():
        nonlocal calls
        calls += 1
        value = original()
        if calls == 2:
            value["State"]["StartedAt"] = "operator-replacement"
        return value

    monkeypatch.setattr(subject.source, "inspect", inspect)
    assert subject.reconcile(1180)["state"] == "connector_changed"
    assert not any(c[1] == "restart" for c in commands)


def test_corrupt_or_foreign_state_does_not_reset_cooldown(rig):
    _, commands, path, create = rig
    for raw in ('broken', '{"scope":["other","cloudflare-quick"]}'):
        path.write_text(raw)
        with pytest.raises((ValueError, module.PublicationError)):
            create().reconcile(5000)
    assert not any(c[1] == "restart" for c in commands)
