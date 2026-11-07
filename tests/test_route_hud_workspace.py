import csv
import hashlib
import json
from types import SimpleNamespace

import pytest
from scripts.pilot import route_hud_workspace as ws


def test_dead_child_state_is_terminal_but_completed_sidecar_is_preserved(tmp_path):
    folder=tmp_path/'telemetry';folder.mkdir()
    (folder/'state.json').write_text('{"phase":"running"}')
    ws.settle_child(tmp_path)
    assert json.loads((folder/'state.json').read_bytes())['phase']=='failed'
    (folder/'state.json').write_text('{"phase":"pending"}')
    ws.settle_child(tmp_path,cancelled=True)
    assert json.loads((folder/'state.json').read_bytes())['phase']=='cancelled'
    (folder/'state.json').write_text('{"phase":"ready"}')
    ws.settle_child(tmp_path)
    assert json.loads((folder/'state.json').read_bytes())['phase']=='ready'


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def setup_job(tmp_path, monkeypatch):
    ws._CACHE.clear()
    job = tmp_path / 'job'
    source = job / 'input'
    source.mkdir(parents=True)
    for name, data in {'manifest.json': b'manifest', 'video.h264': b'video',
                       'frames.jsonl': b'frames', 'inputs.jsonl': b'inputs', 'COMPLETE': b'complete'}.items():
        (source / name).write_bytes(data)
    capture = SimpleNamespace(originals={'manifest.json': b'manifest'}, geometry=(1920, 1080),
        frames=[{'relative_ticks_90k': i * 3000} for i in range(7)],
        manifest={'config': {'profile': {'hudProfile': ws.PROFILE, 'mode': 'vehicle_buttons'},
                             'hud_hidden_declared': False}})
    monkeypatch.setattr(ws, 'validate_browser', lambda _: capture)
    python = tmp_path / 'python.exe'
    tess = tmp_path / 'tess.exe'
    for path in (python, tess):
        path.write_bytes(b'executable')
        path.chmod(0o755)
    monkeypatch.setattr(ws, 'PYTHON', python)
    monkeypatch.setattr(ws, 'TESSERACT', tess)
    return job, capture


def seed(job):
    folder = job / 'telemetry'
    folder.mkdir(exist_ok=True)
    (folder / 'intent.json').write_text(json.dumps({'schema': 'route-hud-intent-v1',
        'preset': ws.PRESET, 'source_manifest_sha256': sha(b'manifest')}))
    (folder / 'state.json').write_text(json.dumps({'phase': 'ready'}))
    path = folder / 'speed.csv'
    with path.open('w', newline='', encoding='utf8') as f:
        w = csv.writer(f)
        w.writerow(['frame_index','relative_ticks_90k','seconds','hud_kmh','ocr_text','ocr_confidence','status'])
        w.writerow([0,0,'0.000000','85','85',90,'accepted'])
        w.writerow([3,9000,'0.100000','','14',90,'unknown'])
        w.writerow([6,18000,'0.200000','70','70',90,'accepted'])
    receipt = {'preset': ws.PRESET, 'source_manifest_sha256': sha(b'manifest'),
        'source_video_sha256': sha(b'video'), 'output_csv_sha256': sha(path.read_bytes()),
        'geometry': [1920,1080], 'sampling_step': 3, 'source_modified': False,
        'units': 'game_hud_kmh', 'world_metric': False, 'selected_count': 3,
        'accepted_count': 2, 'unknown_count': 1}
    (folder / 'speed.csv.receipt.json').write_text(json.dumps(receipt))


def test_start_requires_explicit_preset_and_is_exclusive(setup_job, monkeypatch):
    job, capture = setup_job
    capture.manifest['config']['profile'].pop('hudProfile')
    assert ws.start(job, capture) is None
    assert not (job / 'telemetry').exists()
    capture.manifest['config']['profile']['hudProfile'] = ws.PROFILE
    calls = []
    marker = object()
    monkeypatch.setattr(ws.subprocess, 'Popen', lambda *a, **k: calls.append((a, k)) or marker)
    assert ws.start(job, capture) is marker
    assert len(calls) == 1 and calls[0][0][0][0] == str(ws.PYTHON)
    assert json.loads((job / 'telemetry/intent.json').read_text())['source_manifest_sha256'] == sha(b'manifest')
    with pytest.raises(FileExistsError):
        ws.start(job, capture)


def test_walking_or_hidden_hud_never_starts_telemetry(setup_job, monkeypatch):
    job, capture = setup_job
    monkeypatch.setattr(ws.subprocess, 'Popen', lambda *a, **k: pytest.fail('unexpected child'))
    capture.manifest['config']['profile']['mode'] = 'walk'
    assert ws.start(job, capture) is None
    capture.manifest['config']['profile']['mode'] = 'vehicle_buttons'
    capture.manifest['config']['hud_hidden_declared'] = True
    assert ws.start(job, capture) is None
    assert not (job / 'telemetry').exists()


def test_unavailable_and_cancel_start(setup_job):
    job, capture = setup_job
    ws.TESSERACT.unlink()
    assert ws.start(job, capture) is None
    assert ws.read_status(job) == {'phase': 'unavailable'}


def test_ready_summary_binding_cache_and_tamper(setup_job, monkeypatch):
    job, capture = setup_job
    # Historical, explicitly seeded artifacts are valid without a new preset flag.
    capture.manifest['config']['profile'].pop('hudProfile')
    seed(job)
    status = ws.read_status(job)
    assert status['phase'] == 'ready'
    assert [s['hud_kmh'] for s in status['samples']] == [85, None, 70]
    assert (status['selected_count'], status['accepted_count'], status['unknown_count']) == (3,2,1)
    status['samples'][0]['hud_kmh'] = 0
    monkeypatch.setattr(ws, 'validate_browser', lambda _: pytest.fail('cache miss'))
    assert ws.read_status(job)['samples'][0]['hud_kmh'] == 85
    # Any source fingerprint change invalidates the cached public result.
    (job / 'input/video.h264').write_bytes(b'modified')
    monkeypatch.setattr(ws, 'validate_browser', lambda _: capture)
    assert ws.read_status(job) == {'phase': 'invalid'}


def test_csv_tamper_and_no_private_data(setup_job):
    job, _ = setup_job
    seed(job)
    (job / 'telemetry/speed.csv').write_text('tampered')
    assert ws.read_status(job) == {'phase': 'invalid'}


def test_bucket_preserves_unknown_and_gap():
    samples = ws._samples([(i*9000, None if i == 1 else 80) for i in range(1202)])
    assert len(samples) <= 601 and samples[0]['hud_kmh'] is None
    samples = ws._samples([(0,80), (25000,80)])
    assert samples[1]['gap_before'] and samples[1]['hud_kmh'] is None


def test_worker_cancel_before_run(setup_job, monkeypatch):
    job, capture = setup_job
    monkeypatch.setattr(ws.subprocess, 'Popen', lambda *a, **k: object())
    ws.start(job, capture)
    (job / 'CANCEL').touch()
    ws._worker(job)
    assert ws.read_status(job) == {'phase': 'cancelled'}
    assert not (job / 'telemetry/speed.csv').exists()
