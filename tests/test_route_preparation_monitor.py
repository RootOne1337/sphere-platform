"""Preparation supervision must not reject completed work or cache host memory."""

import json
from types import SimpleNamespace

import pytest

from scripts.pilot import route_resource_monitor
from scripts.pilot import route_workspace as workspace

HEALTHY = dict(system='Windows', freeDiskBytes=30*2**30,
               availableRamBytes=12*2**30, totalRamBytes=48*2**30,
               committedBytes=60*2**30, commitLimitBytes=96*2**30,
               volumeHealthStatus='Healthy', volumeOperationalStatus=['OK'])


@pytest.fixture
def supervision(tmp_path, monkeypatch):
    owner = workspace.RouteWorkspaces(tmp_path, tmp_path/'unused-python')
    job = tmp_path/('a'*32)
    folder = job/'navigation'/('b'*32)
    folder.mkdir(parents=True)
    (folder/'state.json').write_text('{"phase":"features"}', encoding='utf-8')
    (folder/'worker.private.log').write_bytes(b'')
    events, snapshots, instances = [], [], []

    class Monitor:
        def __init__(self, root):
            assert root == workspace.ROOT
            self.closed = False
            instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True
            events.append('monitor_closed')

        def sample(self):
            assert not self.closed
            events.append('sample')
            assert snapshots, 'unexpected resource sample'
            value = snapshots.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value

    class Child:
        returncode = None

        def poll(self):
            return self.returncode

        def stop(self, *, timeout):
            assert timeout == 10
            events.append('child_stopped')
            self.returncode = -1

        def close(self):
            events.append('child_closed')

    child = Child()
    owner.processes[job.name] = child
    monkeypatch.setattr(route_resource_monitor, 'TaskResourceMonitor', Monitor)
    monkeypatch.setattr(workspace, 'collect', lambda _: pytest.fail('recurring full collector was used'))
    monkeypatch.setattr(workspace.time, 'sleep', lambda _: None)
    return SimpleNamespace(job=job, folder=folder, owner=owner, child=child,
                           events=events, snapshots=snapshots, instances=instances)


def test_completed_child_during_sleep_keeps_result_without_another_resource_probe(supervision, monkeypatch):
    state = supervision

    def finish(_seconds):
        state.child.returncode = 0
        (state.folder/'state.json').write_text('{"phase":"ready"}', encoding='utf-8')

    monkeypatch.setattr(workspace.time, 'sleep', finish)
    state.owner._monitor(state.folder, state.child, workspace.route_resource_profile(state.job))
    assert json.loads((state.folder/'state.json').read_bytes()) == {'phase': 'ready'}
    assert state.events == ['monitor_closed', 'child_closed']
    assert state.instances[0].closed
    assert state.job.name not in state.owner.processes


def test_supervisor_rechecks_fresh_memory_and_closes_its_own_monitor(supervision):
    state = supervision
    state.snapshots.extend([dict(HEALTHY), dict(HEALTHY, availableRamBytes=5*2**30)])
    profile = workspace.route_resource_profile(state.job)
    state.owner._monitor(state.folder, state.child, profile)
    assert state.events == ['sample', 'sample', 'child_stopped', 'monitor_closed', 'child_closed']
    result = json.loads((state.folder/'state.json').read_bytes())
    assert result == {'phase': 'failed', 'error': 'resource_guard'}
    refusal = json.loads((state.folder/'resource-refusal.json').read_bytes())
    assert refusal['findings'] == ['ram_headroom_low']
    assert refusal['profile'] == profile
    assert state.instances[0].closed


@pytest.mark.parametrize('change,removed,finding', [
    ({}, ('volumeHealthStatus', 'volumeOperationalStatus'), 'volume_health_unavailable'),
    ({}, ('availableRamBytes',), 'memory_measurement_unavailable'),
    ({'committedBytes': 25*2**30, 'commitLimitBytes': 30*2**30}, (), 'commit_headroom_low'),
    ({'volumeHealthStatus': 'Warning'}, (), 'volume_not_ready'),
])
def test_cached_volume_policy_preserves_expiry_counter_and_absolute_commit_refusals(
        supervision, change, removed, finding):
    state = supervision
    snapshot = dict(HEALTHY, **change)
    for key in removed:
        snapshot.pop(key)
    state.snapshots.append(snapshot)
    state.owner._monitor(state.folder, state.child, workspace.route_resource_profile(state.job))
    refusal = json.loads((state.folder/'resource-refusal.json').read_bytes())
    assert finding in refusal['findings']
    assert state.events == ['sample', 'child_stopped', 'monitor_closed', 'child_closed']


@pytest.mark.parametrize('location', ['job', 'attempt'])
def test_cancel_precedes_resource_probe(supervision, location):
    state = supervision
    (getattr(state, 'job' if location == 'job' else 'folder')/'CANCEL').touch()
    state.owner._monitor(state.folder, state.child, workspace.route_resource_profile(state.job))
    assert json.loads((state.folder/'state.json').read_bytes()) == {'phase': 'cancelled', 'error': 'cancelled'}
    assert state.events == ['child_stopped', 'monitor_closed', 'child_closed']


def test_unexpected_monitor_failure_reaps_child_and_releases_slot(supervision):
    state = supervision
    state.snapshots.append(OSError('fresh counters unavailable'))
    state.owner._monitor(state.folder, state.child, workspace.route_resource_profile(state.job))
    assert json.loads((state.folder/'state.json').read_bytes()) == {'phase': 'failed', 'error': 'route_monitor_failed'}
    assert state.events == ['sample', 'monitor_closed', 'child_stopped', 'child_closed']
    assert state.job.name not in state.owner.processes


def test_terminal_child_still_obeys_final_cancel_fence(supervision):
    state = supervision
    state.child.returncode = 0
    (state.folder/'state.json').write_text('{"phase":"ready"}', encoding='utf-8')
    (state.job/'CANCEL').touch()
    state.owner._monitor(state.folder, state.child, workspace.route_resource_profile(state.job))
    assert json.loads((state.folder/'state.json').read_bytes()) == {'phase': 'cancelled', 'error': 'cancelled'}
    assert state.events == ['monitor_closed', 'child_closed']
