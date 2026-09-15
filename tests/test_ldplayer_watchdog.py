"""Exercise actual watchdog state transitions, durable cooldown and OS locking."""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import ldplayer_watchdog as watchdog
from scripts.ldplayer_network import NetworkRecoveryError, RecoveryBusy, exclusive_lock, recover
from tests.test_ldplayer_network import Host, process


class Station(Host):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.running = {"leidian0": "id0", "leidian1": "id1"}
        self.shared = False
        self.snapshots = 0

    def running_vms(self):
        return self.running

    def processes(self):
        self.snapshots += 1
        return super().processes()

    def assert_dedicated(self, index, network):
        if self.shared:
            raise NetworkRecoveryError("Shared network")


def cycle(host, path, now, indices=None):
    return watchdog.run_cycle(host, indices or [0, 1], path, now=now)


def test_two_observations_repair_only_second_and_survive_new_worker(tmp_path):
    host, path = Station(), tmp_path / "state.json"
    first = cycle(host, path, 1000)
    assert first["instances"]["1"]["status"] == "observing_missing_nat"
    assert not host.changes
    second = cycle(host, path, 1060)
    assert second["instances"]["1"]["status"] == "nat_restored"
    assert host.changes == [("stop", 101, "LdNatNetwork1"), ("start", "LdNatNetwork1")]
    assert second["instances"]["0"]["status"] == "nat_present"
    assert not second["internet_verified"] and not second["apk_connection_verified"]
    assert cycle(host, path, 1120)["status"] == "ok"
    assert len(host.changes) == 2


@pytest.mark.parametrize("next_time", [1010, 1200, 999])
def test_too_soon_stale_or_backward_clock_cannot_repair(tmp_path, next_time):
    host, path = Station(), tmp_path / "state.json"
    cycle(host, path, 1000)
    cycle(host, path, next_time)
    assert not host.changes


def test_repeated_early_polls_do_not_prevent_full_grace(tmp_path):
    host, path = Station(), tmp_path / "state.json"
    for now in (1000, 1005, 1010, 1029):
        cycle(host, path, now)
        assert not host.changes
    assert cycle(host, path, 1030)["instances"]["1"]["status"] == "nat_restored"


@pytest.mark.parametrize("outcome", ["stopped", "healthy", "error"])
def test_interrupted_observation_requires_new_grace(tmp_path, outcome):
    host, path = Station(), tmp_path / "state.json"
    cycle(host, path, 1000)
    if outcome == "stopped":
        host.running.pop("leidian1")
    elif outcome == "healthy":
        host.entries.append(process(1, "nat", 102))
    else:
        host.network = "wrong-network"
    cycle(host, path, 1060)
    host.running["leidian1"] = "id1"
    host.entries = [p for p in host.entries if p["ProcessId"] != 102]
    host.network = "LdNatNetwork1"
    cycle(host, path, 1120)
    assert not host.changes


def test_cim_timeout_cannot_mutate_or_preserve_old_observation(tmp_path):
    host, path = Station(), tmp_path / "state.json"
    cycle(host, path, 1000)
    original = host.processes
    def failure():
        raise subprocess.TimeoutExpired("powershell", 20)
    host.processes = failure
    assert cycle(host, path, 1060)["status"] == "error"
    host.processes = original
    cycle(host, path, 1120)
    assert not host.changes


def test_failed_repair_cooldown_is_durable_and_retry_is_bounded(tmp_path):
    host, path = Station(), tmp_path / "state.json"
    host.start_succeeds = False
    cycle(host, path, 1000)
    assert cycle(host, path, 1060)["instances"]["1"]["status"] == "error"
    for now in (1120, 1180, 1240, 1300):
        cycle(host, path, now)
    assert host.changes == [("stop", 101, "LdNatNetwork1"), ("start", "LdNatNetwork1")]
    host.start_succeeds = True
    assert cycle(host, path, 1360)["instances"]["1"]["status"] == "nat_restored"


def test_write_ahead_attempt_survives_abrupt_worker_exit(tmp_path, monkeypatch):
    host, path = Station(), tmp_path / "state.json"
    cycle(host, path, 1000)
    original = watchdog.recover
    def crash(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(watchdog, "recover", crash)
    with pytest.raises(KeyboardInterrupt):
        cycle(host, path, 1060)
    assert json.loads(path.read_text())["instances"]["1"]["last_attempt"] == 1060
    monkeypatch.setattr(watchdog, "recover", original)
    assert cycle(host, path, 1120)["instances"]["1"]["status"] == "cooldown"
    assert not host.changes


def test_unwritable_state_prevents_host_mutation(tmp_path, monkeypatch):
    host, path = Station(), tmp_path / "state.json"
    cycle(host, path, 1000)
    def failure(*args):
        raise OSError("Disk unavailable")
    monkeypatch.setattr(watchdog, "write_state", failure)
    with pytest.raises(OSError):
        cycle(host, path, 1060)
    assert not host.changes


@pytest.mark.parametrize("invalid", ["{", '{"version": 2}', "[]"])
def test_corrupted_state_is_not_reset_into_permission_to_repair(tmp_path, invalid):
    host, path = Station(), tmp_path / "state.json"
    path.write_text(invalid)
    with pytest.raises(ValueError):
        cycle(host, path, 1000)
    assert not host.changes and host.snapshots == 0


def test_scope_change_is_rejected(tmp_path):
    host, path = Station(), tmp_path / "state.json"
    cycle(host, path, 1000)
    with pytest.raises(ValueError, match="scoped"):
        cycle(host, path, 1060, [1])
    assert not host.changes


def test_shared_running_vm_prevents_even_orphan_dhcp_stop(tmp_path):
    host, path = Station(), tmp_path / "state.json"
    host.shared = True
    cycle(host, path, 1000)
    assert cycle(host, path, 1060)["instances"]["1"]["status"] == "error"
    assert not host.changes


def test_healthy_fleet_uses_one_snapshot_and_no_vm_detail_calls(tmp_path):
    host = Station(nat=True)
    host.running = {f"leidian{i}": str(i) for i in range(100)}
    host.entries = [process(i, "nat", i + 100) for i in range(100)]
    assert cycle(host, tmp_path / "state.json", 1000, list(range(100)))["status"] == "ok"
    assert host.snapshots == 1 and host.info_calls == 0 and not host.changes


def test_only_one_repair_per_cycle_and_other_instance_gets_next_turn(tmp_path, monkeypatch):
    host, path = Station(), tmp_path / "state.json"
    host.entries = []
    host.vm_info = lambda i: (f'name="leidian{i}"\nVMState="running"\nnic1="natnetwork"\n'
        f'nat-network1="LdNatNetwork{i}"\ncableconnected1="on"\n')
    called = []
    def failure(host, index, **kwargs):
        called.append(index)
        raise NetworkRecoveryError("Failed start")
    monkeypatch.setattr(watchdog, "recover", failure)
    cycle(host, path, 1000)
    cycle(host, path, 1060)
    assert called == [0]
    cycle(host, path, 1120)
    assert called == [0, 1]


@pytest.mark.parametrize("indices", [[], [1, 1], [True], [-1], [4096], "1", list(range(257))])
def test_invalid_allowlist_rejected(indices, tmp_path):
    with pytest.raises(ValueError):
        watchdog.validate_config({"indices": indices, "vboxmanage": str(tmp_path / "VBoxManage.exe"),
            "state_path": str(tmp_path / "state.json")})


def test_thread_and_subprocess_lock_contention_and_release(tmp_path):
    path = tmp_path / "lock"
    def acquire():
        with exclusive_lock(path):
            pass
    code = ("import sys; from pathlib import Path; "
        "from scripts.ldplayer_network import exclusive_lock; "
        "lock=exclusive_lock(Path(sys.argv[1])); lock.__enter__()")
    with exclusive_lock(path), ThreadPoolExecutor(1) as pool:
        with pytest.raises(RecoveryBusy):
            pool.submit(acquire).result(timeout=5)
        child = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, timeout=15)
        assert child.returncode != 0 and b"RecoveryBusy" in child.stderr
    # Child exits without __exit__: OS releases the lock after process death.
    assert subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, timeout=15).returncode == 0
    acquire()


def test_manual_repair_shares_host_lock_with_another_worker(tmp_path):
    host, path = Station(), tmp_path / "host.lock"
    host.repair_lock = lambda: exclusive_lock(path)
    with exclusive_lock(path), pytest.raises(RecoveryBusy):
        recover(host, 1, repair=True)
    assert not host.changes and not host.info_calls


def test_parallel_watchdog_does_not_overwrite_inflight_state(tmp_path):
    host, path = Station(), tmp_path / "state.json"
    with exclusive_lock(path.with_suffix(".lock")), pytest.raises(RecoveryBusy):
        cycle(host, path, 1000)
    assert not path.exists() and not host.changes


def test_repair_does_not_hide_another_degraded_instance(tmp_path, monkeypatch):
    host, path = Station(), tmp_path / "state.json"
    cycle(host, path, 1000)
    host.entries = [p for p in host.entries if p["ProcessId"] != 50]
    real_info = host.vm_info
    host.vm_info = lambda i: real_info(i).replace("LdNatNetwork1", f"LdNatNetwork{i}")
    result = cycle(host, path, 1060)
    assert result["instances"]["1"]["status"] == "nat_restored"
    assert result["instances"]["0"]["status"] == "observing_missing_nat"
    assert result["status"] == "degraded"
