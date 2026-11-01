"""HUD job integration boundaries; no Android, GPU, or external service."""
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts.pilot import check_route_first_run as first_run
from scripts.pilot import reconstruct_route as route
from scripts.pilot import reconstruction_service as service
from scripts.pilot import route_hud_workspace as hud


def legacy_capture():
    return SimpleNamespace(manifest={'config': {}},
                           frames=[{'relative_ticks_90k': 0}, {'relative_ticks_90k': 450000}])


@pytest.mark.parametrize(('raw', 'public'), [
    ('pending', 'processing'), ('running', 'processing'), ('invalid', 'failed'),
    ('cancelled', 'failed'), ('unavailable', 'unavailable'), ('ready', 'ready')])
def test_jobs_status_normalizes_telemetry_and_binds_manifest(tmp_path, monkeypatch, raw, public):
    monkeypatch.setattr(service, 'collect', lambda _: {})
    monkeypatch.setattr(service, 'route_resource_findings', lambda *a, **k: [])
    jobs = service.Jobs(tmp_path / 'jobs', tmp_path / 'python.exe')
    jobs.create({'id': 'a'*32, 'key': 'b'*64, 'mask': 'game', 'steps': 3000})
    job = jobs.path('a'*32)
    (job / 'input/manifest.json').write_bytes(b'manifest')
    monkeypatch.setattr(hud, 'read_status', lambda _: {'phase': raw})
    status = jobs.status(job)
    assert status['telemetry']['phase'] == public
    assert status['telemetry']['source_manifest_sha256'] == hashlib.sha256(b'manifest').hexdigest()


def test_jobs_status_has_no_telemetry_for_walking_or_absent_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'collect', lambda _: {})
    monkeypatch.setattr(service, 'route_resource_findings', lambda *a, **k: [])
    jobs = service.Jobs(tmp_path / 'jobs', tmp_path / 'python.exe')
    jobs.create({'id': 'a'*32, 'key': 'b'*64, 'mask': 'game', 'steps': 3000})
    job = jobs.path('a'*32)
    monkeypatch.setattr(hud, 'read_status', lambda _: None)
    assert 'telemetry' not in jobs.status(job)


def test_optional_hud_start_failure_does_not_break_route(tmp_path, monkeypatch):
    monkeypatch.setattr(route, 'checkpoint', lambda _: None)
    monkeypatch.setattr(route, 'validate_browser', lambda _: legacy_capture())
    def fail(*args):
        raise OSError('sensitive stderr')
    monkeypatch.setattr(hud, 'start', fail)
    monkeypatch.setattr(route, '_reconstruct', lambda *a, **k: 'route_complete')
    assert route.reconstruct(tmp_path, 'game', 3000) == 'route_complete'


def test_cpu_guard_runs_before_any_hud_child(tmp_path, monkeypatch):
    def guard(_):
        raise RuntimeError('resource_guard')
    monkeypatch.setattr(route, 'checkpoint', guard)
    monkeypatch.setattr(hud, 'start', lambda *a: pytest.fail('HUD must not start'))
    with pytest.raises(RuntimeError, match='resource_guard'):
        route.reconstruct(tmp_path, 'game', 3000)


def test_failed_route_cancels_owned_hud_and_preserves_failure(tmp_path, monkeypatch):
    (tmp_path/'telemetry').mkdir()
    monkeypatch.setattr(route, 'checkpoint', lambda _: None)
    monkeypatch.setattr(route, 'validate_browser', lambda _: legacy_capture())
    class Child:
        def __init__(self): self.done = False; self.waits = []
        def poll(self): return 0 if self.done else None
        def wait(self, timeout):
            self.waits.append(timeout)
            assert (tmp_path/'telemetry/CANCEL').exists()
            self.done = True
        def terminate(self): pytest.fail('cooperative stop should work')
    child = Child()
    monkeypatch.setattr(hud, 'start', lambda *a: child)
    settled = []
    monkeypatch.setattr(hud, 'settle_child', lambda job, cancelled: settled.append(cancelled))
    def fail(*a, **kw): raise RuntimeError('route_failure')
    monkeypatch.setattr(route, '_reconstruct', fail)
    with pytest.raises(RuntimeError, match='route_failure'):
        route.reconstruct(tmp_path, 'game', 3000)
    assert child.waits == [6] and settled == [True]
    assert not (tmp_path/'CANCEL').exists()


def test_unresponsive_hud_child_is_terminated_then_killed(tmp_path, monkeypatch):
    (tmp_path/'telemetry').mkdir()
    (tmp_path/'CANCEL').touch()
    monkeypatch.setattr(route, 'checkpoint', lambda _: None)
    monkeypatch.setattr(route, 'validate_browser', lambda _: legacy_capture())
    class Child:
        def __init__(self): self.done = False; self.actions = []
        def poll(self): return 0 if self.done else None
        def wait(self, timeout):
            self.actions.append('wait')
            if not self.done: raise subprocess.TimeoutExpired('hud', timeout)
        def terminate(self): self.actions.append('terminate')
        def kill(self): self.actions.append('kill'); self.done = True
    child = Child()
    monkeypatch.setattr(hud, 'start', lambda *a: child)
    monkeypatch.setattr(hud, 'settle_child', lambda *a, **k: None)
    monkeypatch.setattr(route, '_reconstruct', lambda *a, **kw: 'ok')
    assert route.reconstruct(tmp_path, 'game', 3000) == 'ok'
    assert child.actions == ['wait', 'terminate', 'wait', 'kill', 'wait']


def test_recipe_includes_telemetry_sources():
    assert {'scripts/pilot/route_hud_speed.py', 'scripts/pilot/route_hud_workspace.py',
            'scripts/pilot/route_speed_consistency.py'} <= set(first_run.RECIPE)
