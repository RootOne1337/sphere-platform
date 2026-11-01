import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import cv2 as cv
import numpy as np
import pytest

from scripts.pilot import route_hud_profile as hud

FIXTURES = Path(__file__).parent / 'fixtures/hud_speed_font_v1'


def image_for(path):
    crop = cv.imread(str(path))
    image = np.zeros((540, 960, 3), np.uint8)
    image[465:485, 460:500] = crop
    return image


def observe(image, **kwargs):
    return hud.read_live_speed(image, epoch='capture-a', sequence=7, received_at=12.0,
                               jpeg_sha256='a' * 64, **kwargs)


def test_real_visible_hud_digits_include_stationary_and_legacy_unknown_values():
    rows = json.loads((FIXTURES / 'provenance.json').read_text())
    for row in rows:
        path = FIXTURES / row['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['crop_sha256']
        result = observe(image_for(path))
        assert result['status'] == 'accepted'
        assert result['speed_kmh'] == row['proposed_speed']
        assert result['epoch'] == 'capture-a' and result['sequence'] == 7
        assert result['received_at'] == 12.0 and result['jpeg_sha256'] == 'a' * 64
        assert result['hudProfile'] == hud.PROFILE and result['world_metric'] is False


def test_jpeg_variants_may_refuse_but_must_not_turn_reviewed_digits_into_other_speeds():
    for row in json.loads((FIXTURES / 'provenance.json').read_text()):
        image = image_for(FIXTURES / row['file'])
        for quality in (60, 75, 95):
            _, encoded = cv.imencode('.jpg', image, [cv.IMWRITE_JPEG_QUALITY, quality])
            result = observe(cv.imdecode(encoded, cv.IMREAD_COLOR))
            assert result['speed_kmh'] in (None, float(row['proposed_speed']))


def test_occlusion_empty_geometry_bad_metadata_and_processing_deadline_are_not_speeds(monkeypatch):
    image = np.zeros((540, 960, 3), np.uint8)
    assert observe(image)['speed_kmh'] is None
    image[465:485, 460:500] = 255
    assert observe(image)['speed_kmh'] is None
    assert observe(image[:200])['status'] == 'unsupported_geometry'
    with pytest.raises(ValueError, match='frame_binding'):
        hud.read_live_speed(image, epoch='x', sequence=True, received_at=1, jpeg_sha256='a' * 64)
    clock = iter((1.0, 1.2))
    monkeypatch.setattr(hud.time, 'perf_counter', lambda: next(clock))
    assert observe(image_for(FIXTURES / '00-0000.png'))['status'] == 'processing_deadline'


def test_font_hash_is_pinned_and_failure_does_not_supply_fallback_speed(tmp_path, monkeypatch):
    bad = tmp_path / 'bank.json'
    bad.write_bytes(b'{}')
    hud._bank.cache_clear()
    monkeypatch.setattr(hud, 'BANK_PATH', bad)
    try:
        result = observe(image_for(FIXTURES / '00-0000.png'))
        assert result['status'] == 'font_unavailable' and result['speed_kmh'] is None
    finally:
        hud._bank.cache_clear()


def test_reference_interpolates_only_bracketed_observations_and_preserves_gaps_and_zero():
    reference = hud.SpeedReference((0, 9000, 18000, 45000, 54000), (0., 10., None, 30., 20.), {})
    assert reference.sample(0) == 0
    assert reference.sample(4500) == 5
    assert reference.sample(13500) is None and reference.sample(18000) is None
    assert reference.sample(36000) is None and reference.sample(-1) is None
    assert reference.sample(54001) is None
    assert reference.sample(True) is None and reference.sample(float('nan')) is None
    assert reference.preview(0, 9000) == 0
    assert reference.preview(0, 18000) is None
    assert reference.preview(45000, 9000) == 20
    separated = hud.SpeedReference((0, 18001), (20., 20.), {})
    assert separated.sample(9000) is None


@pytest.fixture
def source_job(tmp_path, monkeypatch):
    from motor_worker import browser_teach
    job = tmp_path / 'job'
    source = job / 'input'
    source.mkdir(parents=True)
    for name in ('manifest.json', 'video.h264', 'frames.jsonl', 'inputs.jsonl', 'COMPLETE'):
        (source / name).write_bytes(name.encode())
    frames = [dict(index=i, relative_ticks_90k=i * 9000) for i in range(3)]
    capture = SimpleNamespace(geometry=(1920, 1080), frames=frames,
        manifest=dict(config=dict(profile=dict(hudProfile=hud.PROFILE, mode='vehicle_buttons'),
                                  hud_hidden_declared=False)))
    image = cv.cvtColor(cv.resize(image_for(FIXTURES / '00-0000.png'), (1920, 1080),
                                 interpolation=cv.INTER_NEAREST), cv.COLOR_BGR2RGB)
    frame = SimpleNamespace(to_ndarray=lambda **_: image)
    monkeypatch.setattr(browser_teach, 'validate_browser', lambda _: capture)
    monkeypatch.setattr(browser_teach, 'decoded_browser', lambda _: iter((row, frame) for row in frames))
    return job, capture


def test_source_profile_seals_exact_rows_does_not_overwrite_and_detects_source_tamper(source_job):
    job, _ = source_job
    before = {p.name: p.read_bytes() for p in (job / 'input').iterdir()}
    receipt = hud.prepare_speed_reference(job)
    reference = hud.load_speed_reference(job)
    assert receipt['selected_count'] == 3 and reference.sample(0) == 0
    assert reference.receipt['commands_observed'] is False
    assert before == {p.name: p.read_bytes() for p in (job / 'input').iterdir()}
    with pytest.raises(FileExistsError):
        hud.prepare_speed_reference(job)
    (job / 'input/video.h264').write_bytes(b'changed')
    with pytest.raises(ValueError, match='source_changed'):
        hud.load_speed_reference(job)


@pytest.mark.parametrize('case', ['missing_marker', 'profile_bytes', 'frame_boolean', 'bad_value'])
def test_profile_integrity_and_frame_validation(source_job, case):
    job, _ = source_job
    hud.prepare_speed_reference(job)
    folder = job / 'vehicle-speed-reference'
    if case == 'missing_marker':
        (folder / 'COMPLETE').unlink()
    elif case == 'profile_bytes':
        (folder / 'profile.json').write_bytes(b'{}')
    else:
        profile = json.loads((folder / 'profile.json').read_text())
        if case == 'frame_boolean':
            profile['rows'][1]['index'] = True
        else:
            profile['rows'][0]['speed_kmh'] = float('nan')
        (folder / 'profile.json').write_text(json.dumps(profile))
        receipt = json.loads((folder / 'receipt.json').read_text())
        receipt['profile_sha256'] = hud._sha(folder / 'profile.json')
        (folder / 'receipt.json').write_text(json.dumps(receipt))
        (folder / 'COMPLETE').write_text(hud._sha(folder / 'receipt.json'))
    with pytest.raises(ValueError):
        hud.load_speed_reference(job)


def test_cancel_and_ineligible_source_never_create_profile(source_job):
    job, capture = source_job
    capture.manifest['config']['hud_hidden_declared'] = True
    assert hud.prepare_speed_reference(job) is None
    assert not (job / 'vehicle-speed-reference').exists()
    capture.manifest['config']['hud_hidden_declared'] = False
    (job / 'CANCEL').touch()
    with pytest.raises(InterruptedError):
        hud.prepare_speed_reference(job)
    assert not (job / 'vehicle-speed-reference').exists()
