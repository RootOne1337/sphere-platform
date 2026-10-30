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
    monkeypatch.setattr(service, 'evaluate', lambda _: [])
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


def test_restart_fails_interrupted_and_preserves_input(jobs):
    job = create(jobs)
    jobs.upload(job, 'video.h264', 0, b'raw')
    restarted = service.Jobs(jobs.folder, jobs.python)
    assert restarted.status(job)['phase'] == 'failed'
    assert (job / 'input/video.h264').read_bytes() == b'raw'


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
        for headers in ({'Origin': 'https://evil.example'}, {'Host': 'evil.example:3342'}, {'X-Sphere-Reconstruction': ''}):
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(request('/health', **headers))
            assert exc.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request('/jobs/' + job.name))
        assert exc.value.code == 403
        with urllib.request.urlopen(request('/jobs/' + job.name, **{'X-Job-Key': 'b' * 64})) as response:
            assert json.load(response)['phase'] == 'uploading'
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request('/jobs/' + 'c' * 32, **{'X-Job-Key': 'b' * 64}))
        assert exc.value.code == 409
        assert json.load(exc.value) == {'error': 'job_not_found'}
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
                ({},b'x'*(384*1024+1),409)]:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base,data=payload,headers=headers|changed))
            assert error.value.code==expected
        assert not seen
        with urllib.request.urlopen(urllib.request.Request(base,data=raw,headers=headers)) as response:
            assert json.load(response)['jpegSha256']==hashlib.sha256(raw).hexdigest()
        assert seen==[(job,dict(id='c'*32,captureEpoch='e'*32,sequence=4),raw)]
        with urllib.request.urlopen(urllib.request.Request(base,method='OPTIONS',headers=headers)) as response:
            assert 'X-Frame-Sequence' in response.headers['Access-Control-Allow-Headers']
            assert response.headers['Access-Control-Max-Age']=='600'
    finally:
        server.shutdown();server.server_close();thread.join(3)
