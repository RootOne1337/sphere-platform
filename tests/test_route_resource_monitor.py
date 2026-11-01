"""Task-scoped volume proof and owned-probe lifecycle, using deterministic time."""

import json
import subprocess
import threading
from types import SimpleNamespace

import pytest

from scripts.pilot import resource_guard as guard
from scripts.pilot import route_resource_monitor as monitor

HEALTHY = dict(volumeHealthStatus='Healthy', volumeOperationalStatus=['OK'])
WARNING = dict(volumeHealthStatus='Warning', volumeOperationalStatus=['Full Repair Needed'])


class Clock:
    value = 0.

    def __call__(self):
        return self.value


class Probe:
    def __init__(self, outcome):
        self.outcome = outcome
        self.returncode = None
        self.killed = False
        self.communications = 0
        self.waits = 0
        self.entered, self.released = threading.Event(), threading.Event()

    def communicate(self, *, timeout):
        self.communications += 1
        self.entered.set()
        if self.killed:
            return b'', b''
        if self.outcome == 'timeout':
            raise subprocess.TimeoutExpired('volume_probe', timeout)
        if self.outcome == 'pending':
            assert self.released.wait(2), 'test must close its owned probe'
            return b'', b''
        self.returncode = 0
        return (json.dumps(self.outcome).encode() if isinstance(self.outcome, dict)
                else self.outcome), b''

    def kill(self):
        self.killed, self.returncode = True, -9
        self.released.set()

    def poll(self):
        return self.returncode

    def wait(self, *, timeout):
        self.waits += 1
        assert self.returncode is not None
        return self.returncode


@pytest.fixture
def host(monkeypatch):
    clock = Clock()
    values = dict(availableRamBytes=12 * guard.GIB, totalRamBytes=48 * guard.GIB,
                  committedBytes=45 * guard.GIB, commitLimitBytes=90 * guard.GIB)
    identity = dict(value='volume-a')
    outcomes, probes, commands = [], [], []
    monkeypatch.setattr(monitor.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(monitor, 'windows_volume_identity', lambda _: identity['value'])
    monkeypatch.setattr(monitor.shutil, 'disk_usage', lambda _: SimpleNamespace(free=30 * guard.GIB))
    monkeypatch.setattr(guard, 'windows_memory', lambda: dict(values))

    def popen(command, **kwargs):
        assert command[0] == 'powershell.exe'
        assert kwargs['stdin'] == subprocess.DEVNULL
        assert kwargs['stdout'] == kwargs['stderr'] == subprocess.PIPE
        assert kwargs['env']['SPHERE_RESOURCE_GUARD_PATH'] not in command[-1]
        assert outcomes, 'unexpected extra probe'
        outcome = outcomes.pop(0)
        commands.append((command, kwargs))
        if isinstance(outcome, Exception):
            raise outcome
        probe = Probe(outcome)
        probes.append(probe)
        return probe

    monkeypatch.setattr(monitor.subprocess, 'Popen', popen)
    return SimpleNamespace(clock=clock, values=values, identity=identity,
                           outcomes=outcomes, probes=probes, commands=commands)


def finish(task):
    task._worker.join(1)
    assert not task._worker.is_alive()
    return task.sample()


def test_admission_is_fresh_then_only_volume_is_cached_ram_and_commit_are_fresh(host, tmp_path):
    host.outcomes.append(HEALTHY)
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        first = task.sample()
        assert first['volumeMeasurement'] == 'fresh'
        assert guard.evaluate(first) == []
        host.clock.value = 1.
        host.values['availableRamBytes'] = 2 * guard.GIB
        host.values['committedBytes'] = 80 * guard.GIB
        second = task.sample()
        assert second['volumeMeasurement'] == 'task_cache'
        assert second['volumeProofAgeMs'] == 1000
        assert second['availableRamBytes'] == 2 * guard.GIB
        assert guard.evaluate(second) == ['ram_headroom_low', 'commit_headroom_low']
        assert len(host.commands) == 1
        assert second['volumeProofScope'] == 'task_and_volume'
        assert second['memoryMeasurement'] == 'GetPerformanceInfo'


def test_refresh_timeout_uses_only_unexpired_task_proof_and_then_recovers(host, tmp_path):
    host.outcomes.extend([HEALTHY, 'timeout', 'timeout', HEALTHY])
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        task.sample()
        host.clock.value = 10.
        task.sample()
        failed = finish(task)
        assert failed['volumeHealthStatus'] == 'Healthy'
        assert failed['volumeProofAgeMs'] == 10000
        assert failed['collectionErrors'] == [dict(component='volume_probe', errorType='TimeoutExpired')]
        assert guard.evaluate(failed) == []
        host.clock.value = 31.
        expired = task.sample()
        assert 'volumeHealthStatus' not in expired
        assert guard.evaluate(expired) == ['volume_health_unavailable']
        finish(task)
        host.clock.value = 42.
        task.sample()
        recovered = finish(task)
        assert recovered['volumeHealthStatus'] == 'Healthy'
        assert recovered['volumeProofAgeMs'] == 0
        assert 'collectionErrors' not in recovered
        assert guard.evaluate(recovered) == []


def test_new_warning_immediately_replaces_healthy_cache_and_failure_cannot_restore_it(host, tmp_path):
    host.outcomes.extend([HEALTHY, WARNING, 'timeout'])
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        task.sample()
        host.clock.value = 10.
        task.sample()
        warning = finish(task)
        assert warning['volumeHealthStatus'] == 'Warning'
        assert guard.evaluate(warning) == ['volume_not_ready']
        host.clock.value = 20.
        task.sample()
        failed = finish(task)
        assert failed.get('volumeHealthStatus') != 'Healthy'
        assert failed['lastVolumeHealthStatus'] == 'Warning'
        assert guard.evaluate(failed) == ['volume_health_unavailable']


def test_proof_expires_while_one_refresh_is_still_pending_and_close_kills_only_owned_probe(host, tmp_path):
    host.outcomes.extend([HEALTHY, 'pending'])
    task = monitor.TaskResourceMonitor(tmp_path, clock=host.clock)
    task.sample()
    host.clock.value = 10.
    task.sample()
    assert host.probes[-1].entered.wait(1)
    for _ in range(20):
        task.sample()
    assert len(host.probes) == 2
    host.clock.value = 31.
    expired = task.sample()
    assert guard.evaluate(expired) == ['volume_health_unavailable']
    task.close()
    assert host.probes[-1].killed
    assert not host.probes[0].killed
    assert not task._worker.is_alive()
    assert task._process is None
    with pytest.raises(RuntimeError, match='resource_monitor_closed'):
        task.sample()


def test_new_task_cannot_borrow_another_tasks_healthy_proof(host, tmp_path):
    host.outcomes.extend([HEALTHY, 'timeout'])
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as first:
        a = first.sample()
        with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as second:
            b = second.sample()
            assert a['resourceMonitorTask'] != b['resourceMonitorTask']
            assert 'volumeHealthStatus' not in b
            assert guard.evaluate(b) == ['volume_health_unavailable']
            assert len(host.commands) == 2


def test_volume_identity_change_is_latched_even_if_original_mount_returns(host, tmp_path):
    host.outcomes.append(HEALTHY)
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        task.sample()
        host.identity['value'] = 'volume-b'
        changed = task.sample()
        assert 'volumeHealthStatus' not in changed
        assert guard.evaluate(changed) == ['volume_health_unavailable']
        host.identity['value'] = 'volume-a'
        assert guard.evaluate(task.sample()) == ['volume_health_unavailable']
        assert len(host.commands) == 1


def test_resolved_root_change_cannot_redirect_an_existing_task_proof(host, tmp_path):
    host.outcomes.append(HEALTHY)
    other = tmp_path / 'other'
    other.mkdir()
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        task.sample()
        task.requested_root = other
        assert guard.evaluate(task.sample()) == ['volume_health_unavailable']
        task.requested_root = task.root
        assert guard.evaluate(task.sample()) == ['volume_health_unavailable']


def test_native_ram_failure_drops_all_previous_memory_counters(host, tmp_path, monkeypatch):
    host.outcomes.append(HEALTHY)
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        task.sample()
        def unavailable():
            raise OSError('secret detail')
        monkeypatch.setattr(guard, 'windows_memory', unavailable)
        sample = task.sample()
        assert 'availableRamBytes' not in sample and 'committedBytes' not in sample
        assert guard.evaluate(sample) == ['memory_measurement_unavailable', 'commit_measurement_unavailable']
        assert 'secret' not in str(sample)


@pytest.mark.parametrize('bad', [b'not-json', b'[]', b'x' * 8193, b'{}',
                               b'{"volumeHealthStatus":"Healthy","volumeOperationalStatus":[]}'])
def test_bad_admission_volume_response_never_seeds_a_healthy_cache(host, tmp_path, bad):
    host.outcomes.append(bad)
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        sample = task.sample()
        assert 'volumeHealthStatus' not in sample
        assert guard.evaluate(sample) == ['volume_health_unavailable']
        assert sample['availableRamBytes'] == 12 * guard.GIB


def test_clock_regression_is_not_a_longer_cache_ttl(host, tmp_path):
    host.outcomes.append(HEALTHY)
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        task.sample()
        host.clock.value = -1.
        with pytest.raises(RuntimeError, match='clock_regressed'):
            task.sample()


def test_exact_ttl_boundary_cannot_extend_while_probe_is_pending(host, tmp_path):
    host.outcomes.extend([HEALTHY, 'pending'])
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        task.sample()
        host.clock.value = 10.
        task.sample()
        assert host.probes[-1].entered.wait(1)
        host.clock.value = 30.
        assert guard.evaluate(task.sample()) == []
        host.clock.value = 30.00001
        assert guard.evaluate(task.sample()) == ['volume_health_unavailable']


def test_returned_snapshot_cannot_mutate_a_stored_volume_proof(host, tmp_path):
    measured = dict(volumeHealthStatus='Healthy', volumeOperationalStatus=['OK', 'Full Repair Needed'])
    host.outcomes.append(measured)
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        first = task.sample()
        assert guard.evaluate(first) == ['volume_not_ready']
        first['volumeOperationalStatus'][:] = ['OK']
        assert guard.evaluate(task.sample()) == ['volume_not_ready']


def test_linux_uses_fresh_linux_collection_and_never_creates_windows_probe(host, tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.platform, 'system', lambda: 'Linux')
    calls = []
    def collect(path):
        calls.append(path)
        return dict(system='Linux', availableRamBytes=len(calls) * guard.GIB)
    monkeypatch.setattr(guard, 'collect', collect)
    with monitor.TaskResourceMonitor(tmp_path, clock=host.clock) as task:
        assert task.sample()['availableRamBytes'] == guard.GIB
        assert task.sample()['availableRamBytes'] == 2 * guard.GIB
    assert len(calls) == 2 and not host.commands


def test_native_volume_api_uses_mount_root_and_guid_not_drive_letter_cache(monkeypatch, tmp_path):
    def mount(path, buffer, size):
        assert path == str(tmp_path)
        assert size == 32768
        buffer.value = 'C:\\Mounted\\Disk\\'
        return 1
    def name(path, buffer, size):
        assert path == 'C:\\Mounted\\Disk\\'
        assert size == 64
        buffer.value = '\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\'
        return 1
    def load(name, **kwargs):
        assert name == 'kernel32.dll' and kwargs == dict(use_last_error=True, winmode=0x800)
        return SimpleNamespace(GetVolumePathNameW=mount, GetVolumeNameForVolumeMountPointW=name_api)
    name_api = name
    monkeypatch.setattr(monitor.ctypes, 'WinDLL', load, raising=False)
    assert monitor.windows_volume_identity(tmp_path) == '\\\\?\\volume{12345678-1234-1234-1234-123456789abc}\\'
