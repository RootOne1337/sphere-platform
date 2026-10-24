"""Actual job boundary regressions; no GPU, Android, browser or paid API."""
import hashlib
import json
import threading
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


def test_creation_is_idempotent_and_only_one_active(jobs):
    job = create(jobs)
    assert create(jobs) == job
    with pytest.raises(ValueError, match='one_active'):
        create(jobs, 'c' * 32)
    assert json.loads((job / 'control.json').read_text())['key_sha256'] == hashlib.sha256(('b' * 64).encode()).hexdigest()
    assert 'b' * 64 not in (job / 'control.json').read_text()


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
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
