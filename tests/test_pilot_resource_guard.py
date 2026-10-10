import subprocess
from pathlib import Path

import pytest

from scripts.pilot import resource_guard as guard


def healthy():
    return {"system": "Windows", "freeDiskBytes": 30 * guard.GIB,
            "totalRamBytes": 48 * guard.GIB, "availableRamBytes": 12 * guard.GIB,
            "committedBytes": 45 * guard.GIB, "commitLimitBytes": 90 * guard.GIB,
            "volumeHealthStatus": "Healthy", "volumeOperationalStatus": ["OK"]}


def test_pre_incident_disk_and_commit_pressure_prevent_heavy_build():
    snapshot = healthy() | {"freeDiskBytes": 41000960, "committedBytes": 97196965888,
                           "commitLimitBytes": 102267379712}
    assert guard.evaluate(snapshot) == ["disk_headroom_low", "commit_headroom_low"]


def test_headroom_boundary_and_no_mutations():
    assert guard.evaluate(healthy() | {"freeDiskBytes": 20 * guard.GIB,
                                     "availableRamBytes": 4 * guard.GIB}) == []
    assert guard.evaluate(healthy() | {"committedBytes": 85, "commitLimitBytes": 100}) == ["commit_headroom_low"]


@pytest.mark.parametrize("field,value,expected", [
    ("freeDiskBytes", None, "disk_measurement_unavailable"),
    ("freeDiskBytes", True, "disk_measurement_unavailable"),
    ("availableRamBytes", -1, "memory_measurement_unavailable"),
    ("availableRamBytes", 49 * guard.GIB, "memory_measurement_unavailable"),
    ("totalRamBytes", 0, "memory_measurement_unavailable"),
    ("committedBytes", "12", "commit_measurement_unavailable"),
    ("commitLimitBytes", 0, "commit_measurement_unavailable"),
    ("committedBytes", 91 * guard.GIB, "commit_measurement_unavailable"),
])
def test_unknown_or_impossible_counters_fail_closed(field, value, expected):
    assert guard.evaluate(healthy() | {field: value}) == [expected]


@pytest.mark.parametrize("settings", [{"min_disk_gib": 0}, {"min_ram_gib": float("nan")},
                                     {"max_commit_percent": 100}, {"min_disk_gib": float("inf")}])
def test_invalid_threshold_cannot_disable_guard(settings):
    with pytest.raises(ValueError):
        guard.evaluate(healthy(), **settings)


def test_linux_never_uses_windows_commit_comparison():
    assert guard.evaluate(healthy() | {"system": "Linux", "committedBytes": 999 * guard.GIB}) == []


def test_unsupported_platform_is_not_a_success():
    assert guard.evaluate(healthy() | {"system": "Darwin"}) == ["unsupported_host"]


def test_windows_counter_timeout_remains_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(guard.platform, "system", lambda: "Windows")
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 10 and command[0] == "powershell.exe"
        raise subprocess.TimeoutExpired(command, 10)
    monkeypatch.setattr(guard.subprocess, "run", timeout)
    snapshot = guard.collect(tmp_path)
    assert snapshot["collectionError"] == "TimeoutExpired"
    assert "memory_measurement_unavailable" in guard.evaluate(snapshot)
    assert snapshot["deviceCommandsSent"] is False and snapshot["mutationsPerformed"] is False


def test_linux_memavailable_and_kib_units(monkeypatch, tmp_path):
    monkeypatch.setattr(guard.platform, "system", lambda: "Linux")
    monkeypatch.setattr(Path, "read_text", lambda _: "MemTotal: 50331648 kB\nMemAvailable: 6291456 kB\n")
    snapshot = guard.collect(tmp_path)
    assert snapshot["availableRamBytes"] == 6 * guard.GIB
    assert snapshot["totalRamBytes"] == 48 * guard.GIB


def test_full_repair_needed_blocks_build_despite_good_disk_ram_and_commit():
    snapshot = healthy() | {"volumeHealthStatus": "Warning", "volumeOperationalStatus": ["Full Repair Needed"]}
    assert guard.evaluate(snapshot) == ["volume_not_ready"]


@pytest.mark.parametrize("health,operations", [
    (None, ["OK"]), ("Healthy", None), ("Healthy", []), ("Healthy", "OK"),
    ("Healthy", [None]), ("", ["OK"]),
])
def test_unknown_volume_measurement_never_grants_build_permission(health, operations):
    assert guard.evaluate(healthy() | {"volumeHealthStatus": health, "volumeOperationalStatus": operations}) == ["volume_health_unavailable"]


@pytest.mark.parametrize("health,operations", [
    ("Unhealthy", ["OK"]), ("Healthy", ["Unknown"]),
    ("Healthy", ["OK", "Full Repair Needed"]), ("Warning", ["Spot Fix Needed"]),
])
def test_unready_volume_is_not_masked_by_one_healthy_signal(health, operations):
    assert guard.evaluate(healthy() | {"volumeHealthStatus": health, "volumeOperationalStatus": operations}) == ["volume_not_ready"]


def test_volume_path_uses_environment_instead_of_powershell_interpolation(monkeypatch, tmp_path):
    import json
    path = tmp_path / "path with 'quote and $variable"
    path.mkdir()
    monkeypatch.setattr(guard.platform, "system", lambda: "Windows")
    def reply(command, **kwargs):
        assert str(path) == kwargs["env"]["SPHERE_RESOURCE_GUARD_PATH"]
        assert str(path) not in command[-1]
        assert "Get-Volume -FilePath $env:SPHERE_RESOURCE_GUARD_PATH" in command[-1]
        return subprocess.CompletedProcess(command, 0, json.dumps(healthy()), "")
    monkeypatch.setattr(guard.subprocess, "run", reply)
    snapshot = guard.collect(path)
    assert guard.evaluate(snapshot) == []
    assert not snapshot["deviceCommandsSent"] and not snapshot["mutationsPerformed"]
