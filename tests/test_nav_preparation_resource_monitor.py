"""Navigation preparation uses one task proof, fresh counters and unchanged gates."""
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from scripts.pilot import prepare_route_workspace as preparation
from scripts.pilot import route_workspace as workspace

GIB = 2**30
BUDGET = dict(kind='route_features', minRamGiB=6.25, minDiskGiB=20, maxCommitPercent=85)


def healthy():
    return dict(system='Windows', freeDiskBytes=100*GIB, totalRamBytes=48*GIB, availableRamBytes=20*GIB,
                committedBytes=20*GIB, commitLimitBytes=100*GIB,
                volumeHealthStatus='Healthy', volumeOperationalStatus=['OK'])


@pytest.fixture
def environment(tmp_path, monkeypatch):
    import cv2

    from motor_worker import browser_teach
    from scripts.pilot import export_route_localization, route_motion_audit

    monkeypatch.setattr(preparation, 'ROOT', tmp_path)
    monkeypatch.setattr(workspace, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    monkeypatch.setattr(cv2, 'setNumThreads', lambda _: None)
    monkeypatch.setattr(preparation, 'route_resource_profile', lambda job: dict(BUDGET))
    monkeypatch.setattr(preparation, 'route_source_model', lambda job: job/'prepared/model')
    monkeypatch.setattr(route_motion_audit, 'audit', lambda _: dict(rapid_reversals=[], speed_outliers=[]))
    capture = SimpleNamespace(geometry=(1920, 1080), manifest={},
        frames=[dict(relative_ticks_90k=0), dict(relative_ticks_90k=90000)])
    monkeypatch.setattr(browser_teach, 'validate_browser', lambda _: capture)
    env = dict(root=tmp_path, monitors=[], sequences=[], export_hook=None, calls=[])

    class Monitor:
        def __init__(self, root):
            self.root = root
            self.task = f'preparation-{len(env["monitors"])}'
            self.queue = iter(env['sequences'].pop(0) if env['sequences'] else [])
            self.samples, self.close_count = [], 0
            self.last = healthy()
            env['monitors'].append(self)

        def __enter__(self):
            return self

        def sample(self):
            self.last = next(self.queue, self.last)
            value = copy.deepcopy(self.last)
            value['memoryObservedAt'] = f'fresh-native-{len(self.samples)}'
            value['resourceMonitorTask'] = self.task
            self.samples.append(value)
            return value

        def close(self):
            self.close_count += 1

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(preparation, 'TaskResourceMonitor', Monitor)
    env['monitor_class'] = Monitor
    monkeypatch.setattr(workspace, 'collect', lambda _: pytest.fail('preparation discarded task snapshot'))

    def export(_model, _provenance, _images, output, *, profile, world_revision, checkpoint_fn):
        env['calls'].append((output, profile, world_revision))
        if env['export_hook']:
            env['export_hook'](checkpoint_fn, output.parent)
        else:
            for _ in range(10):
                checkpoint_fn(output.parent)
        output.write_text('{}')
        return dict(first_seconds=0., last_seconds=1., map_support=dict(
            all_reference_neighborhoods_supported=True, all_reference_intervals_observed=True))

    monkeypatch.setattr(export_route_localization, 'export', export)

    def job(label='one', attempt='a'*32):
        target = tmp_path/label
        folder = target/'navigation'/attempt
        folder.mkdir(parents=True)
        (folder/'intent.json').write_text(json.dumps(dict(id=attempt)))
        (target/'geometry.json').write_text('{}')
        return target, attempt, folder

    env['job'] = job
    return env


def test_preparation_uses_one_monitor_and_fresh_snapshot_for_every_callback(environment):
    env = environment
    job, attempt, folder = env['job']()
    preparation.prepare(job, attempt)
    assert len(env['monitors']) == 1
    monitor = env['monitors'][0]
    assert monitor.root == env['root'] and monitor.close_count == 1
    assert len(monitor.samples) == 13  # admission, ten callbacks, two publication fences
    assert len({s['memoryObservedAt'] for s in monitor.samples}) == 13
    assert json.loads((folder/'state.json').read_text())['phase'] == 'ready'
    assert not json.loads((folder/'state.json').read_text())['executionQualified']
    assert (job/'geometry.json').read_text() == '{}'


@pytest.mark.parametrize('phase', ['admission', 'callback'])
@pytest.mark.parametrize('bad,expected', [
    ({'availableRamBytes': 6*GIB}, 'ram_headroom_low'),
    ({'committedBytes': 86*GIB}, 'commit_headroom_low'),
    ({'freeDiskBytes': 19*GIB}, 'disk_headroom_low'),
    ({'committedBytes': 15*GIB, 'commitLimitBytes': 20*GIB}, 'commit_headroom_low'),
])
def test_fresh_resource_drop_keeps_all_existing_gates(environment, phase, bad, expected):
    env = environment
    job, attempt, folder = env['job']()
    bad_snapshot = healthy() | bad
    env['sequences'].append([bad_snapshot] if phase == 'admission' else [healthy(), bad_snapshot])
    with pytest.raises(RuntimeError, match='resource_guard'):
        preparation.prepare(job, attempt)
    monitor = env['monitors'][0]
    assert monitor.close_count == 1
    refusal = json.loads((folder/'resource-refusal.json').read_text())
    assert expected in refusal['findings']
    assert refusal['snapshot']['memoryObservedAt'] == f'fresh-native-{len(monitor.samples)-1}'
    assert refusal['profile'] == BUDGET
    assert not (folder/'receipt.json').exists()
    assert len(env['calls']) == (0 if phase == 'admission' else 1)


def test_expired_volume_proof_does_not_reuse_earlier_health(environment):
    env = environment
    job, attempt, folder = env['job']()
    expired = healthy()
    expired.pop('volumeHealthStatus')
    expired.pop('volumeOperationalStatus')
    expired.update(volumeProofAgeMs=30001, volumeMeasurement='unavailable', collectionError='TimeoutExpired')
    env['sequences'].append([healthy(), expired])
    with pytest.raises(RuntimeError, match='resource_guard'):
        preparation.prepare(job, attempt)
    refusal = json.loads((folder/'resource-refusal.json').read_text())
    assert refusal['findings'] == ['volume_health_unavailable']
    assert refusal['snapshot']['availableRamBytes'] == 20*GIB
    assert env['monitors'][0].close_count == 1


def test_preparations_cannot_share_volume_proof_across_jobs(environment):
    env = environment
    job1, attempt1, _ = env['job']('one')
    job2, attempt2, _ = env['job']('two', 'b'*32)
    missing_health = healthy()
    missing_health.pop('volumeHealthStatus')
    missing_health.pop('volumeOperationalStatus')
    env['sequences'].extend([[healthy()], [missing_health]])
    preparation.prepare(job1, attempt1)
    with pytest.raises(RuntimeError, match='resource_guard'):
        preparation.prepare(job2, attempt2)
    first, second = env['monitors']
    assert first is not second and first.task != second.task
    assert len(second.samples) == 1
    assert first.close_count == second.close_count == 1


@pytest.mark.parametrize('scope', ['job', 'attempt'])
def test_existing_cancellation_closes_without_starting_a_probe(environment, scope):
    env = environment
    job, attempt, folder = env['job']()
    marker = (job if scope == 'job' else folder)/'CANCEL'
    marker.write_bytes(b'')
    with pytest.raises(RuntimeError, match='cancelled'):
        preparation.prepare(job, attempt)
    assert env['monitors'][0].samples == []
    assert env['monitors'][0].close_count == 1 and marker.exists()
    assert env['calls'] == []


@pytest.mark.parametrize('scope', ['job', 'attempt'])
def test_mid_export_cancellation_releases_monitor_and_preserves_marker(environment, scope):
    env = environment
    job, attempt, folder = env['job']()
    marker = (job if scope == 'job' else folder)/'CANCEL'

    def cancel(callback, target):
        callback(target)
        marker.write_bytes(b'')
        callback(target)

    env['export_hook'] = cancel
    with pytest.raises(RuntimeError, match='cancelled'):
        preparation.prepare(job, attempt)
    assert len(env['monitors'][0].samples) == 2
    assert env['monitors'][0].close_count == 1 and marker.exists()
    assert not (folder/'receipt.json').exists()


def test_cancellation_after_export_return_cannot_publish_ready(environment):
    env = environment
    job, attempt, folder = env['job']()
    env['export_hook'] = lambda *_: (job/'CANCEL').write_bytes(b'')
    with pytest.raises(RuntimeError, match='cancelled'):
        preparation.prepare(job, attempt)
    assert env['monitors'][0].close_count == 1
    assert not (folder/'receipt.json').exists()
    assert json.loads((folder/'state.json').read_text())['phase'] == 'features'


def test_job_cancellation_during_admission_probe_prevents_export(environment, monkeypatch):
    env = environment
    job, attempt, _ = env['job']()
    original = env['monitor_class'].sample

    def cancel_during_sample(monitor):
        value = original(monitor)
        (job/'CANCEL').write_bytes(b'')
        return value

    monkeypatch.setattr(env['monitor_class'], 'sample', cancel_during_sample)
    with pytest.raises(RuntimeError, match='cancelled'):
        preparation.prepare(job, attempt)
    assert env['calls'] == []
    assert env['monitors'][0].close_count == 1


@pytest.mark.parametrize('wrong_scope', ['other_job', 'sibling_attempt'])
def test_callback_cannot_borrow_task_proof_for_another_target(environment, wrong_scope):
    env = environment
    job, attempt, _ = env['job']()
    if wrong_scope == 'other_job':
        _, _, other = env['job']('other', 'b'*32)
    else:
        other = job/'navigation'/('b'*32)
        other.mkdir()
        (other/'intent.json').write_text(json.dumps(dict(id='b'*32)))
    before = {f.name: f.read_bytes() for f in other.iterdir() if f.is_file()}
    env['export_hook'] = lambda callback, _: callback(other)
    with pytest.raises(RuntimeError, match='route_resource_task_mismatch'):
        preparation.prepare(job, attempt)
    assert len(env['monitors'][0].samples) == 1  # Wrong target never samples/borrows proof.
    assert env['monitors'][0].close_count == 1
    assert {f.name: f.read_bytes() for f in other.iterdir() if f.is_file()} == before


def test_export_exception_closes_monitor_without_publishing_receipt(environment):
    env = environment
    job, attempt, folder = env['job']()

    def fail(*_):
        raise RuntimeError('export_failed')

    env['export_hook'] = fail
    with pytest.raises(RuntimeError, match='export_failed'):
        preparation.prepare(job, attempt)
    assert env['monitors'][0].close_count == 1
    assert not (folder/'receipt.json').exists()


def test_source_change_closes_monitor_and_keeps_existing_source_gate(environment):
    env = environment
    job, attempt, folder = env['job']()
    env['export_hook'] = lambda *_: (job/'geometry.json').write_text('{"changed":true}')
    with pytest.raises(ValueError, match='route_source_changed'):
        preparation.prepare(job, attempt)
    assert env['monitors'][0].close_count == 1
    assert not (folder/'receipt.json').exists()


def test_default_checkpoint_still_collects_fresh_full_snapshot(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(workspace, 'collect', lambda root: calls.append(root) or healthy())
    workspace.resource_checkpoint(tmp_path)
    workspace.resource_checkpoint(tmp_path, profile=BUDGET)
    assert calls == [workspace.ROOT, workspace.ROOT]


def test_injected_snapshot_never_causes_an_extra_full_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, 'collect', lambda _: pytest.fail('snapshot was discarded'))
    workspace.resource_checkpoint(tmp_path, profile=BUDGET, snapshot=healthy())
    with pytest.raises(ValueError, match='route_resource_snapshot'):
        workspace.resource_checkpoint(tmp_path, profile=BUDGET, snapshot=[])
