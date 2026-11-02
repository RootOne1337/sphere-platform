"""Actual job boundary regressions; no GPU, Android, browser or paid API."""
import hashlib
import json
import threading
import sys
from pathlib import Path
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from scripts.pilot import reconstruction_service as service


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'collect', lambda _: {})
    monkeypatch.setattr(service, 'evaluate', lambda *args,**kwargs: [])
    return service.Jobs(tmp_path / 'jobs', tmp_path / 'python.exe')


def create(jobs, identity='a' * 32):
    jobs.create(dict(id=identity, key='b' * 64, mask='game', steps=3000))
    return jobs.path(identity)


def test_route_features_use_live_runtime_instead_of_heavy_gpu_interpreter(jobs):
    assert jobs.navigation.python == Path(sys.executable)
    assert jobs.python != jobs.navigation.python


def test_creation_is_idempotent_and_only_one_active(jobs):
    job = create(jobs)
    assert create(jobs) == job
    with pytest.raises(ValueError, match='one_active'):
        create(jobs, 'c' * 32)
    assert json.loads((job / 'control.json').read_text())['key_sha256'] == hashlib.sha256(('b' * 64).encode()).hexdigest()
    assert 'b' * 64 not in (job / 'control.json').read_text()


def test_detail_profile_is_preserved_and_does_not_relax_exclusive_execution(jobs):
    request = dict(id='a' * 32, key='b' * 64, mask='none', steps=30000)
    jobs.create(request)
    assert jobs.authorize(jobs.path(request['id']), request['key'])['steps'] == 30000
    with pytest.raises(ValueError, match='one_active'):
        create(jobs, 'c' * 32)


def test_status_manifest_binding_is_absent_then_tracks_actual_uploaded_bytes(jobs):
    job = create(jobs)
    assert jobs.status(job)['source_manifest_sha256'] is None
    raw = b'{"capture":"first"}'
    jobs.upload(job, 'manifest.json', 0, raw)
    assert jobs.status(job)['source_manifest_sha256'] == hashlib.sha256(raw).hexdigest()
    (job/'input/manifest.json').write_bytes(b'{"capture":"changed"}')
    assert jobs.status(job)['source_manifest_sha256'] != hashlib.sha256(raw).hexdigest()
    assert jobs.status(job)['source_manifest_sha256'] == hashlib.sha256(
        (job/'input/manifest.json').read_bytes()).hexdigest()


def test_catalog_manifest_quota_does_not_read_oversized_source(jobs, monkeypatch):
    job = create(jobs)
    manifest = job/'input/manifest.json'
    manifest.write_bytes(b'x'*(service.LIMITS['manifest.json']+1))
    original_open = Path.open
    def bounded_open(path, *args, **kwargs):
        if path == manifest:
            pytest.fail('oversized manifest must not be read for catalog status')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', bounded_open)
    assert jobs.status(job)['source_manifest_sha256'] is None


def test_catalog_manifest_growing_during_read_remains_bounded(jobs, monkeypatch):
    import io

    job = create(jobs)
    manifest = job/'input/manifest.json'
    manifest.write_bytes(b'{}')
    original_open = Path.open
    read_sizes = []
    class Grew(io.BytesIO):
        def read(self, size=-1):
            read_sizes.append(size)
            return super().read(size)
    def changed_open(path, *args, **kwargs):
        if path == manifest:
            return Grew(b'x'*(service.LIMITS['manifest.json']+1))
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', changed_open)
    assert jobs.status(job)['source_manifest_sha256'] is None
    assert read_sizes == [service.LIMITS['manifest.json']+1]


@pytest.mark.parametrize('steps', [True, 30000.0, '30000', 30001, None])
def test_non_admitted_training_budget_is_refused_before_job_creation(jobs, steps):
    with pytest.raises(ValueError, match='invalid_processing_options'):
        jobs.create(dict(id='a' * 32, key='b' * 64, mask='none', steps=steps))
    assert not jobs.path('a' * 32).exists()


def test_upload_does_not_repeat_unknown_chunk_or_escape(jobs):
    job = create(jobs)
    assert jobs.upload(job, 'video.h264', 0, b'first')['offset'] == 5
    with pytest.raises(ValueError, match='offset_mismatch'):
        jobs.upload(job, 'video.h264', 0, b'first')
    for name in ('../escape', 'control.json', 'a/video.h264'):
        with pytest.raises(ValueError, match='invalid_upload'):
            jobs.upload(job, name, 0, b'x')
    assert (job / 'input/video.h264').read_bytes() == b'first'


def test_upload_quota_and_terminal_state(jobs):
    job = create(jobs)
    with pytest.raises(ValueError, match='quota'):
        jobs.upload(job, 'COMPLETE', 0, b'x' * 1025)
    service.write_json(job / 'state.json', {'phase': 'cancelled'})
    with pytest.raises(ValueError, match='upload_closed'):
        jobs.upload(job, 'COMPLETE', 0, b'x')


def test_start_needs_all_files_and_exclusive_intent(jobs, monkeypatch):
    job = create(jobs)
    control = jobs.authorize(job, 'b' * 64)
    with pytest.raises(ValueError, match='missing'):
        jobs.start(job, control)
    for name in service.LIMITS:
        jobs.upload(job, name, 0, b'x')
    (job / 'START').touch()
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('repeated process'))
    with pytest.raises(FileExistsError):
        jobs.start(job, control)


@pytest.mark.parametrize('platform,route_only,expected', [
    ('win32', True, 0x08004000), ('win32', False, 0x08000000),
    ('win32', 'true', 0x08000000), ('linux', True, 0), ('linux', False, 0)])
def test_only_explicit_windows_cpu_route_worker_gets_below_normal_priority(monkeypatch, platform, route_only, expected):
    monkeypatch.setattr(service.sys, 'platform', platform)
    monkeypatch.setattr(service.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(service.subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0x4000, raising=False)
    assert service.route_worker_creationflags(route_only) == expected


def test_cpu_worker_priority_flag_falls_back_without_changing_dense_default(monkeypatch):
    monkeypatch.setattr(service.sys, 'platform', 'win32')
    monkeypatch.delattr(service.subprocess, 'CREATE_NO_WINDOW', raising=False)
    monkeypatch.delattr(service.subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', raising=False)
    assert service.route_worker_creationflags(True) == 0
    assert service.route_worker_creationflags(False) == 0


@pytest.mark.parametrize('route_only,expected', [(True, 0x08004000), (False, 0x08000000)])
def test_job_start_passes_priority_only_to_its_owned_cpu_child(jobs, monkeypatch, route_only, expected):
    from types import SimpleNamespace

    jobs.create(dict(id='a' * 32, key='b' * 64, mask='game', steps=3000,
                     prepare_route=route_only, route_only=route_only))
    job = jobs.path('a' * 32)
    control = jobs.authorize(job, 'b' * 64)
    for name in service.LIMITS:
        jobs.upload(job, name, 0, b'x')
    monkeypatch.setattr(service.sys, 'platform', 'win32')
    monkeypatch.setattr(service.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(service.subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0x4000, raising=False)
    monkeypatch.setattr(jobs, 'status', lambda path: {'phase': json.loads((path / 'state.json').read_bytes())['phase']})
    observed = []
    process = SimpleNamespace(poll=lambda: None)
    def popen(command, **kwargs):
        observed.append((command, kwargs))
        return process
    monkeypatch.setattr(service.subprocess, 'Popen', popen)
    monkeypatch.setattr(service, 'spawn_owned', popen)
    monkeypatch.setattr(service.threading, 'Thread', lambda **_: SimpleNamespace(start=lambda: None))
    jobs.start(job, control)
    assert observed[0][1]['creationflags'] == expected
    assert ('--route-only' in observed[0][0]) is route_only
    assert jobs.processes[job.name] is process


def test_restart_fails_interrupted_and_preserves_input(jobs):
    job = create(jobs)
    jobs.upload(job, 'video.h264', 0, b'raw')
    restarted = service.Jobs(jobs.folder, jobs.python)
    assert restarted.status(job)['phase'] == 'failed'
    assert (job / 'input/video.h264').read_bytes() == b'raw'


def test_restart_signals_live_worker_and_fences_its_late_completion(jobs):
    """A real tiny child observes cancellation; its last write cannot undo it."""
    import subprocess
    import time

    job = create(jobs)
    jobs.upload(job, 'video.h264', 0, b'immutable source')
    service.write_json(job/'state.json', dict(phase='matching'))
    # Image indexing has already finished, so its restart settlement is not
    # responsible for signalling this still-running reconstruction worker.
    (job/'image-route-workspace').mkdir()
    service.write_json(job/'image-route-workspace/state.json', dict(phase='ready'))
    originals = {name: (job/name).read_bytes() for name in ('control.json', 'input/video.h264')}
    code = (
        "import sys,time,json;from pathlib import Path;from scripts.pilot.atomic_json import write_json;p=Path(sys.argv[1]);"
        "(p/'child-ready').touch();deadline=time.monotonic()+5\n"
        "while not (p/'CANCEL').exists() and time.monotonic()<deadline:time.sleep(.01)\n"
        "if not (p/'CANCEL').exists():sys.exit(2)\n"
        "(p/'cancel-observed').touch()\n"
        "while not (p/'allow-late-write').exists() and time.monotonic()<deadline:time.sleep(.01)\n"
        "if not (p/'allow-late-write').exists():sys.exit(3)\n"
        "write_json(p/'state.json',{'phase':'sparse_complete'})"
    )
    child = subprocess.Popen([sys._base_executable, '-B', '-c', code, str(job)],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        deadline = time.monotonic()+5
        while not (job/'child-ready').exists() and time.monotonic()<deadline:
            time.sleep(.01)
        assert (job/'child-ready').exists()
        restarted = service.Jobs(jobs.folder, jobs.python)
        (job/'allow-late-write').touch()
        assert child.wait(timeout=5) == 0
        assert (job/'cancel-observed').exists()
        assert json.loads((job/'state.json').read_bytes())['phase'] == 'sparse_complete'
        assert restarted.status(job)['error'] == 'worker_service_restarted'
        assert restarted.status(job)['phase'] == 'failed'
        assert originals == {name: (job/name).read_bytes() for name in originals}
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_restart_does_not_touch_existing_terminal_job_or_cancel(jobs):
    job = create(jobs)
    service.write_json(job/'state.json', dict(phase='failed', error='original_failure'))
    (job/'CANCEL').write_bytes(b'original cancel marker')
    paths = ('state.json', 'control.json', 'CANCEL')
    before = {name: ((job/name).read_bytes(), (job/name).stat().st_mtime_ns) for name in paths}
    service.Jobs(jobs.folder, jobs.python)
    assert before == {name: ((job/name).read_bytes(), (job/name).stat().st_mtime_ns) for name in paths}
    assert not (job/'service-interrupted.json').exists()


def test_terminal_worker_keeps_serial_slot_through_automatic_handoff(jobs, monkeypatch):
    from types import SimpleNamespace

    jobs.create(dict(id='a'*32, key='b'*64, mask='game', steps=3000, prepare_route=True, route_only=True))
    job = jobs.path('a'*32)
    for name in service.LIMITS:
        jobs.upload(job, name, 0, b'x')
    process = SimpleNamespace(poll=lambda: 0)
    monkeypatch.setattr(service, 'spawn_owned', lambda *a, **k: process)
    monkeypatch.setattr(service.threading, 'Thread', lambda **k: SimpleNamespace(start=lambda: None))
    jobs.start(job, jobs.authorize(job, 'b'*64))
    service.write_json(job/'state.json', dict(phase='sparse_complete'))
    service.write_json(job/'sparse-receipt.json', dict(placeholder=True))
    # The child has exited, but the monitor has not yet completed its handoff.
    with pytest.raises(ValueError, match='one_active_job_only'):
        create(jobs, 'c'*32)
    calls = []
    def prepare(target, body):
        assert target.name in jobs.processes
        with pytest.raises(ValueError, match='one_active_job_only'):
            create(jobs, 'c'*32)
        calls.append((target, body))
    monkeypatch.setattr(jobs.navigation, 'prepare', prepare)
    jobs.monitor(job, process)
    assert len(calls) == 1
    assert job.name not in jobs.processes
    assert not (job/'route-pipeline-refusal.json').exists()


@pytest.mark.parametrize('reason', ['resource_guard', 'worker_timeout', 'worker_log_quota'])
def test_guard_after_sparse_receipt_settles_auto_navigation(jobs, monkeypatch, reason):
    from types import SimpleNamespace

    jobs.create(dict(id='a'*32, key='b'*64, mask='game', steps=3000, prepare_route=True))
    job = jobs.path('a'*32)
    service.write_json(job/'state.json', dict(phase='training'))
    service.write_json(job/'sparse-receipt.json', dict(placeholder=True))
    (job/'worker.log').touch()
    process = SimpleNamespace(poll=lambda: None)
    jobs.processes[job.name] = process
    monkeypatch.setattr(service.time, 'sleep', lambda _: None)
    monkeypatch.setattr(jobs, '_stop_worker', lambda _: None)
    monkeypatch.setattr(jobs.navigation, 'prepare', lambda *a, **k: pytest.fail('guard must not start export'))
    if reason == 'resource_guard':
        monkeypatch.setattr(service, 'route_resource_findings', lambda *a, **k: ['ram_low'])
    elif reason == 'worker_timeout':
        from itertools import chain, repeat
        ticks = chain((0,), repeat(2401))
        monkeypatch.setattr(service.time, 'monotonic', lambda: next(ticks))
    else:
        stat = Path.stat
        monkeypatch.setattr(Path, 'stat', lambda path, *a, **k: SimpleNamespace(st_size=33*1024**2)
                            if path == job/'worker.log' else stat(path, *a, **k))
    jobs.monitor(job, process)
    navigation = jobs.status(job)['navigation']
    assert navigation['phase'] == 'not_prepared'
    assert navigation['error'] == reason
    assert job.name not in jobs.processes


def test_cancel_at_worker_exit_wins_over_sparse_completion(jobs, monkeypatch):
    from types import SimpleNamespace

    jobs.create(dict(id='a'*32, key='b'*64, mask='game', steps=3000, prepare_route=True))
    job = jobs.path('a'*32)
    service.write_json(job/'state.json', dict(phase='sparse_complete'))
    service.write_json(job/'sparse-receipt.json', dict(placeholder=True))
    (job/'CANCEL').touch()
    monkeypatch.setattr(jobs.navigation, 'prepare', lambda *a, **k: pytest.fail('cancelled export'))
    jobs.monitor(job, SimpleNamespace(poll=lambda: 0))
    assert jobs.status(job)['phase'] == 'cancelled'
    assert jobs.status(job)['navigation']['phase'] != 'pending_auto_prepare'


def test_log_launch_failure_releases_slot_and_keeps_one_shot_intent(jobs, monkeypatch):
    job = create(jobs)
    for name in service.LIMITS:
        jobs.upload(job, name, 0, b'x')
    (job/'worker.log').touch()
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('log failure precedes launch'))
    with pytest.raises(FileExistsError):
        jobs.start(job, jobs.authorize(job, 'b'*64))
    assert job.name not in jobs.processes
    assert jobs.status(job)['phase'] == 'failed'
    assert (job/'START').exists()
    create(jobs, 'c'*32)


def test_thread_launch_failure_stops_owned_worker_and_releases_slot(jobs, monkeypatch):
    from types import SimpleNamespace

    job = create(jobs)
    for name in service.LIMITS:
        jobs.upload(job, name, 0, b'x')
    events = []
    process = SimpleNamespace(poll=lambda: None, stop=lambda timeout: events.append('stopped'),
                              close=lambda: events.append('closed'))
    monkeypatch.setattr(service, 'spawn_owned', lambda *a, **k: process)
    class FailedThread:
        def __init__(self, **kwargs): pass
        def start(self): raise RuntimeError('thread unavailable')
    monkeypatch.setattr(service.threading, 'Thread', FailedThread)
    with pytest.raises(RuntimeError, match='thread unavailable'):
        jobs.start(job, jobs.authorize(job, 'b'*64))
    assert events == ['stopped', 'closed']
    assert job.name not in jobs.processes
    assert jobs.status(job)['error'] == 'worker_start_not_confirmed'
    create(jobs, 'c'*32)


@pytest.mark.parametrize('cancelled', [False, True])
def test_forced_stop_settles_only_unfinished_diagnostic_sidecars(jobs, monkeypatch, cancelled):
    from types import SimpleNamespace

    job = create(jobs)
    service.write_json(job/'state.json', dict(phase='image_route_indexing'))
    for directory, phase in (('image-route-workspace', 'running'), ('telemetry', 'ready')):
        (job/directory).mkdir()
        service.write_json(job/directory/'state.json', dict(phase=phase))
    completed = (job/'telemetry/state.json').read_bytes()
    (job/'worker.log').touch()
    if cancelled:
        (job/'CANCEL').touch()
    monkeypatch.setattr(service.time, 'sleep', lambda _: None)
    monkeypatch.setattr(jobs, '_stop_worker', lambda _: None)
    monkeypatch.setattr(service, 'route_resource_findings', lambda *a, **k: ['ram_low'])
    jobs.monitor(job, SimpleNamespace(poll=lambda: None))
    state = json.loads((job/'image-route-workspace/state.json').read_bytes())
    assert state == dict(phase='cancelled' if cancelled else 'failed',
                         error='cancelled' if cancelled else 'resource_guard')
    assert (job/'telemetry/state.json').read_bytes() == completed


def test_automatic_export_refusal_keeps_resource_cause(jobs, monkeypatch):
    from types import SimpleNamespace

    jobs.create(dict(id='a'*32, key='b'*64, mask='game', steps=3000, prepare_route=True))
    job = jobs.path('a'*32)
    service.write_json(job/'state.json', dict(phase='sparse_complete'))
    service.write_json(job/'sparse-receipt.json', dict(placeholder=True))
    def refused(*args, **kwargs):
        raise RuntimeError('resource_guard')
    monkeypatch.setattr(jobs.navigation, 'prepare', refused)
    jobs.monitor(job, SimpleNamespace(poll=lambda: 0))
    assert jobs.status(job)['navigation']['error'] == 'resource_guard'
    assert jobs.status(job)['navigation']['phase'] == 'not_prepared'


def test_cancellation_while_waiting_for_handoff_lock_wins(jobs, monkeypatch):
    from types import SimpleNamespace

    jobs.create(dict(id='a'*32, key='b'*64, mask='game', steps=3000, prepare_route=True))
    job = jobs.path('a'*32)
    service.write_json(job/'state.json', dict(phase='sparse_complete'))
    service.write_json(job/'sparse-receipt.json', dict(placeholder=True))
    class CancelBeforeHandoff:
        def __enter__(self): (job/'CANCEL').touch()
        def __exit__(self, *args): pass
    jobs.lock = CancelBeforeHandoff()
    monkeypatch.setattr(jobs.navigation, 'prepare', lambda *a, **k: pytest.fail('cancel wins'))
    jobs.monitor(job, SimpleNamespace(poll=lambda: 0))
    assert jobs.status(job)['phase'] == 'cancelled'
    assert jobs.status(job)['navigation']['phase'] != 'pending_auto_prepare'


def test_automatic_route_preparation_is_observable_and_restart_does_not_repeat(jobs, monkeypatch):
    jobs.create(dict(id='a' * 32, key='b' * 64, mask='none', steps=30000, prepare_route=True))
    job = jobs.path('a' * 32)
    service.write_json(job / 'state.json', {'phase': 'complete'})
    (job / 'COMPLETE').touch()
    monkeypatch.setattr(jobs, 'appearance', lambda _: {'summary': {'state': 'passed'}, 'views': []})
    assert jobs.status(job)['navigation']['phase'] == 'pending_auto_prepare'
    restarted = service.Jobs(jobs.folder, jobs.python)
    monkeypatch.setattr(restarted, 'appearance', lambda _: {'summary': {'state': 'passed'}, 'views': []})
    result = restarted.status(job)['navigation']
    assert result['phase'] == 'not_prepared'
    assert result['error'] == 'route_preparation_interrupted'
    assert not (job / 'navigation/active.json').exists()


def test_sparse_receipt_allows_one_automatic_preparation_after_dense_failure(jobs, monkeypatch):
    jobs.create(dict(id='a' * 32, key='b' * 64, mask='none', steps=30000, prepare_route=True))
    job = jobs.path('a' * 32)
    service.write_json(job / 'state.json', {'phase': 'failed', 'error': 'brush_failed_see_local_log'})
    service.write_json(job / 'sparse-receipt.json', {'placeholder': True})
    calls = []
    monkeypatch.setattr(jobs.navigation, 'prepare', lambda target, body: calls.append((target, body)))
    class Exited:
        def poll(self): return 1
    jobs.monitor(job, Exited())
    assert len(calls) == 1 and calls[0][0] == job
    assert len(calls[0][1]['id']) == 32
    assert jobs.status(job)['sparse_available'] is True


def test_sparse_receipt_does_not_restart_preparation_after_service_restart(jobs):
    jobs.create(dict(id='a' * 32, key='b' * 64, mask='none', steps=30000, prepare_route=True))
    job = jobs.path('a' * 32)
    service.write_json(job / 'state.json', {'phase': 'failed', 'error': 'brush_failed_see_local_log'})
    service.write_json(job / 'sparse-receipt.json', {'placeholder': True})
    assert jobs.status(job)['navigation']['phase'] == 'pending_auto_prepare'
    restarted = service.Jobs(jobs.folder, jobs.python)
    assert restarted.status(job)['navigation']['error'] == 'route_preparation_interrupted'
    assert not (job / 'navigation/active.json').exists()


def test_route_only_request_is_explicit_and_does_not_enable_input(jobs):
    jobs.create(dict(id='a' * 32, key='b' * 64, mask='none', steps=30000,
                     prepare_route=True, route_only=True))
    job = jobs.path('a' * 32)
    control = jobs.authorize(job, 'b' * 64)
    assert control['route_only'] is True and control['prepare_route'] is True
    service.write_json(job / 'sparse-receipt.json', {'placeholder': True})
    service.write_json(job / 'state.json', {'phase': 'sparse_complete'})
    status = jobs.status(job)
    assert status['sparse_available'] and not status['dense_available']
    assert status['navigation']['phase'] == 'pending_auto_prepare'
    assert status['navigation']['executionQualified'] is False


def test_sparse_scene_source_frame_is_bound_and_visible_without_dense_render(jobs):
    import io
    from PIL import Image
    from scripts.pilot.sparse_scene_receipt import FILES, create_sparse_receipt
    job = create(jobs)
    for name in FILES:
        path = job/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'camera-data')
    manifest = job/'input/manifest.json'
    manifest.write_text('{}')
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    image = io.BytesIO()
    Image.new('RGB', (64, 48), 'red').save(image, 'PNG')
    path = job/'prepared/images/00000000.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image.getvalue())
    service.write_json(job/'prepared/reconstruction-input.json', {'source_manifest_sha256': manifest_sha,
        'images': [{'image': 'images/00000000.png', 'png_sha256': hashlib.sha256(image.getvalue()).hexdigest()}]})
    service.write_json(job/'geometry.json', {'source_manifest_sha256': manifest_sha})
    service.write_json(job/'quality.json', {'registered': 10, 'selected': 10, 'points': 300,
        'mean_reprojection_px': 1, 'conditioning': {'passed': True}, 'intrinsics_condition': {'passed': True}})
    create_sparse_receipt(job)
    assert jobs.source_preview(job, '00000000.png').startswith(b'\xff\xd8')
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='source_preview_changed'):
        jobs.source_preview(job, '00000000.png')


@pytest.mark.parametrize('route_only,prepare_route', [(True, False), ('true', True), (1, True)])
def test_route_only_rejects_ambiguous_or_unprepared_mode(jobs, route_only, prepare_route):
    with pytest.raises(ValueError, match='invalid_route_pipeline_option'):
        jobs.create(dict(id='a' * 32, key='b' * 64, mask='none', steps=30000,
                         prepare_route=prepare_route, route_only=route_only))


def test_old_complete_export_is_not_automatically_a_verified_scene(jobs):
    job = create(jobs)
    service.write_json(job / 'state.json', dict(phase='complete'))
    (job / 'COMPLETE').touch()
    result = jobs.status(job)
    assert result['phase'] == 'review_required'
    assert result['appearance']['state'] == 'unverified'
    assert result['dense_available']


def test_route_resource_refusal_is_an_explicit_preflight_error(jobs, monkeypatch):
    job = create(jobs)
    service.write_json(job / 'state.json', dict(phase='failed', error='camera_quality_gate_failed'))
    def refuse(*_args):
        raise RuntimeError('resource_guard')
    monkeypatch.setattr(jobs.navigation, 'prepare', refuse)
    server = ThreadingHTTPServer(('127.0.0.1', 0), service.handler(jobs, 'http://127.0.0.1:3015', 3342))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f'http://127.0.0.1:{server.server_port}/jobs/{job.name}/navigation/prepare',
            data=json.dumps({'id': 'd' * 32}).encode(), method='POST',
            headers={'Host': '127.0.0.1:3342', 'Origin': 'http://127.0.0.1:3015',
                     'X-Sphere-Reconstruction': '1', 'X-Job-Key': 'b' * 64})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request)
        assert exc.value.code == 409
        assert json.load(exc.value) == {'error': 'resource_guard'}
        assert not (job / 'navigation/active.json').exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_rejected_reference_views_are_bound_and_images_cannot_escape(jobs):
    from scripts.pilot.reconstruction_quality import reference_quality

    job = create(jobs)
    service.write_json(job / 'state.json', dict(phase='complete'))
    (job / 'COMPLETE').touch()
    service.write_json(job / 'result.json', dict(ply_sha256='c' * 64, geometry_sha256='d' * 64))
    (job / 'reference-evaluation').mkdir()
    rows = []
    for i in range(3):
        row = dict(image=f'{i:08}.png', psnr=13., ssim=.6)
        for kind in ('source', 'render'):
            name = f'reference-evaluation/{i:08}-{kind}.png'
            (job / name).write_bytes(b'verified-image')
            row[kind] = dict(file=name, bytes=14, sha256=hashlib.sha256(b'verified-image').hexdigest())
        rows.append(row)
    summary = reference_quality(dict(schema='sphere-reference-render-evaluation-v1', training=False,
                                     held_out=False, resolution_limit=960, views=rows))
    receipt = dict(schema='sphere-scene-appearance-v1', summary=summary, views=rows,
                   ply_sha256='c' * 64, geometry_sha256='d' * 64)
    service.write_json(job / 'appearance.json', receipt)
    assert jobs.status(job)['phase'] == 'quality_rejected'
    assert jobs.reference_image(job, 0, 'render') == b'verified-image'
    for row in rows:
        row.update(psnr=24., ssim=.8)
    receipt['summary'] = reference_quality(dict(schema='sphere-reference-render-evaluation-v1', training=False,
        held_out=False, resolution_limit=960, views=rows))
    service.write_json(job / 'appearance.json', receipt)
    service.write_json(job / 'quality.json', dict(registered=2, selected=3))
    assert jobs.status(job)['phase'] == 'partial_scene'
    assert jobs.status(job)['dense_available']
    (job / rows[0]['render']['file']).write_bytes(b'tampered-image')
    with pytest.raises(ValueError, match='changed'):
        jobs.reference_image(job, 0, 'render')
    rows[0]['source']['file'] = '../private.png'
    service.write_json(job / 'appearance.json', receipt)
    assert jobs.status(job)['appearance']['state'] == 'unverified'
    with pytest.raises(ValueError, match='unavailable'):
        jobs.reference_image(job, 0, 'source')


def test_http_origin_host_capability_and_cors(jobs):
    job = create(jobs)
    server = ThreadingHTTPServer(('127.0.0.1', 0), service.handler(jobs, 'http://127.0.0.1:3015', 3342))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'

    def request(path, **headers):
        return urllib.request.Request(base + path, headers={'Host': '127.0.0.1:3342', 'X-Sphere-Reconstruction': '1', **headers})

    try:
        with urllib.request.urlopen(request('/health', Origin='http://127.0.0.1:3015')) as response:
            assert response.headers['Access-Control-Allow-Origin'] == 'http://127.0.0.1:3015'
            health=json.load(response)
            assert health['route_camera_pipeline']=='vehicle_geometry_v3_hud'
            assert health['creation_recovery_contract']=='confirmed_absence_v1'
            assert health['route_lifecycle_contract']=='owned_serial_handoff_v1'
            assert health['job_source_binding_contract']=='manifest_sha256_status_v1'
        for headers in ({'Origin': 'https://evil.example'}, {'Host': 'evil.example:3342'}, {'X-Sphere-Reconstruction': ''}):
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(request('/health', **headers))
            assert exc.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request('/jobs/' + job.name))
        assert exc.value.code == 403
        with urllib.request.urlopen(request('/jobs/' + job.name, **{'X-Job-Key': 'b' * 64})) as response:
            assert json.load(response)['phase'] == 'uploading'
        before={p.relative_to(jobs.folder):p.read_bytes() for p in jobs.folder.rglob('*') if p.is_file()}
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request('/jobs/' + job.name, **{'X-Job-Key': 'f' * 64}))
        assert exc.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request('/jobs/' + 'c' * 32))
        assert exc.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request('/jobs/' + 'c' * 32, **{'X-Job-Key': 'b' * 64}))
        assert exc.value.code == 404
        assert json.load(exc.value) == {'error': 'job_not_found'}
        assert not jobs.path('c' * 32).exists()
        assert before=={p.relative_to(jobs.folder):p.read_bytes() for p in jobs.folder.rglob('*') if p.is_file()}
        partial=jobs.path('d' * 32);partial.mkdir();(partial/'partial.txt').write_bytes(b'keep')
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request('/jobs/' + partial.name, **{'X-Job-Key': 'b' * 64}))
        assert exc.value.code == 409
        assert json.load(exc.value) == {'error':'job_not_found'}
        assert sorted(p.name for p in partial.iterdir())==['partial.txt']
        assert (partial/'partial.txt').read_bytes()==b'keep'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_file_sharing_denial_is_not_reported_as_lost_job_credentials(jobs,monkeypatch):
    job=create(jobs)
    def blocked(_):raise PermissionError('private-path-must-not-be-exposed')
    monkeypatch.setattr(jobs,'status',blocked)
    server=ThreadingHTTPServer(('127.0.0.1',0),service.handler(jobs,'http://127.0.0.1:3015',3342))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/jobs/{job.name}',
        headers={'Host':'127.0.0.1:3342','Origin':'http://127.0.0.1:3015',
                 'X-Sphere-Reconstruction':'1','X-Job-Key':'b'*64})
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:urllib.request.urlopen(request)
        assert exc.value.code==503
        assert json.load(exc.value)=={'error':'local_file_unavailable_inspect_job_status'}
    finally:
        server.shutdown();server.server_close();thread.join(3)


def test_http_resource_refusal_missing_then_same_creation_is_idempotent(jobs,monkeypatch):
    calls=[]
    def gate(*_args,**_kwargs):
        calls.append(1)
        return ['resource_guard'] if len(calls)==1 else []
    monkeypatch.setattr(service,'route_resource_findings',gate)
    server=ThreadingHTTPServer(('127.0.0.1',0),service.handler(jobs,'http://127.0.0.1:3015',3342))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    identity,key='e'*32,'b'*64
    body=json.dumps(dict(id=identity,key=key,mask='game',steps=30000,prepare_route=True,route_only=True)).encode()
    headers={'Host':'127.0.0.1:3342','X-Sphere-Reconstruction':'1','Content-Type':'application/json'}
    def post():return urllib.request.Request(base+'/jobs',data=body,headers=headers,method='POST')
    def get():return urllib.request.Request(base+'/jobs/'+identity,headers={**headers,'X-Job-Key':key})
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:urllib.request.urlopen(post())
        assert exc.value.code==409 and json.load(exc.value)=={'error':'resource_guard'}
        with pytest.raises(urllib.error.HTTPError) as exc:urllib.request.urlopen(get())
        assert exc.value.code==404 and json.load(exc.value)=={'error':'job_not_found'}
        assert not jobs.path(identity).exists()
        with urllib.request.urlopen(post()) as response:assert json.load(response)['phase']=='uploading'
        with urllib.request.urlopen(post()) as response:assert json.load(response)['phase']=='uploading'
        with urllib.request.urlopen(get()) as response:assert json.load(response)['phase']=='uploading'
        assert len(calls)==2
        control=json.loads((jobs.path(identity)/'control.json').read_text())
        assert control['mask']=='game' and control['steps']==30000 and control['route_only'] is True
        assert not (jobs.path(identity)/'START').exists()
    finally:
        server.shutdown();server.server_close();thread.join(3)


def test_walk_summaries_require_job_capability_and_never_overwrite_another_attempt(jobs):
    job = create(jobs)
    server = ThreadingHTTPServer(('127.0.0.1', 0), service.handler(jobs, 'http://127.0.0.1:3015', 3342))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    body = dict(schema='sphere-walk-summary-v1', id='c'*32, clip='d'*32, release='closed',
        stopReason='contact_video_stale', inputFailure='contact_video_stale', stopFrameAgeMs=281.7,
        stopFrameSequence=1472, executionQualified=False, inputSummary=dict(submitted=2, applied=2, events=9),
        stages=[], observations=[])
    def request(key=None):
        return urllib.request.Request(f'http://127.0.0.1:{server.server_port}/jobs/{job.name}/navigation/walk-report',
            method='POST', data=json.dumps(body).encode(), headers={'Host':'127.0.0.1:3342',
                'Origin':'http://127.0.0.1:3015','X-Sphere-Reconstruction':'1',**({'X-Job-Key':key} if key else {})})
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request())
        assert error.value.code == 403
        assert not (job/'walk-reports').exists()
        with urllib.request.urlopen(request('b'*64)) as response:
            assert json.load(response)['state'] == 'saved'
        body['stopReason'] = 'walk_manual_stop'
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request('b'*64))
        assert error.value.code == 409
        assert json.loads((job/'walk-reports'/('c'*32+'.json')).read_bytes())['stopReason'] == 'contact_video_stale'
    finally:
        server.shutdown();server.server_close();thread.join(3)


def test_cancelled_browser_request_does_not_attempt_a_second_response(jobs):
    from types import SimpleNamespace
    from unittest.mock import Mock
    handler = object.__new__(service.handler(jobs, 'http://127.0.0.1:3015', 3342))
    handler.connection = SimpleNamespace(settimeout=lambda _: None)
    handler.headers = {'Host':'127.0.0.1:3342','Origin':'http://127.0.0.1:3015','X-Sphere-Reconstruction':'1'}
    handler.path = '/health'
    handler.reply = Mock(side_effect=ConnectionAbortedError('client_cancelled'))
    handler.dispatch('GET')
    assert handler.reply.call_count == 1
    assert handler.close_connection


def test_binary_observation_keeps_capability_origin_metadata_and_byte_quotas(jobs,monkeypatch):
    job=create(jobs);seen=[]
    def observe(path,binding,raw):
        seen.append((path,binding,raw))
        return dict(physicalActions=0,jpegSha256=hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(jobs.navigation,'observe_jpeg',observe)
    server=ThreadingHTTPServer(('127.0.0.1',0),service.handler(jobs,'http://127.0.0.1:3015',3342))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}/jobs/{job.name}/navigation/observe-jpeg'
    raw=b'jpeg-body'*100
    headers={'Host':'127.0.0.1:3342','Origin':'http://127.0.0.1:3015','X-Sphere-Reconstruction':'1',
             'X-Job-Key':'b'*64,'Content-Type':'image/jpeg','X-Route-Session':'c'*32,
             'X-Capture-Epoch':'e'*32,'X-Frame-Sequence':'4'}
    try:
        for changed,payload,expected in [({'X-Job-Key':''},raw,403),({'Origin':'https://other.example'},raw,403),
                ({'Content-Type':'image/png'},raw,409),({'X-Frame-Sequence':'4.5'},raw,409),
                ({'X-Walk-Motion':'true'},raw,409),({},b'x'*(384*1024+1),409)]:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base,data=payload,headers=headers|changed))
            assert error.value.code==expected
        assert not seen
        with urllib.request.urlopen(urllib.request.Request(base,data=raw,headers=headers)) as response:
            assert json.load(response)['jpegSha256']==hashlib.sha256(raw).hexdigest()
        assert seen==[(job,dict(id='c'*32,captureEpoch='e'*32,sequence=4),raw)]
        with urllib.request.urlopen(urllib.request.Request(base,data=raw,headers=headers|{'X-Walk-Motion':'1'})) as response:
            assert json.load(response)['physicalActions']==0
        assert seen[-1]==(job,dict(id='c'*32,captureEpoch='e'*32,sequence=4,motionActive=True),raw)
        with urllib.request.urlopen(urllib.request.Request(base,method='OPTIONS',headers=headers)) as response:
            assert 'X-Frame-Sequence' in response.headers['Access-Control-Allow-Headers']
            assert 'X-Walk-Motion' in response.headers['Access-Control-Allow-Headers']
            assert response.headers['Access-Control-Max-Age']=='600'
    finally:
        server.shutdown();server.server_close();thread.join(3)
