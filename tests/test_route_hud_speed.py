import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.pilot import route_hud_speed as hud


def test_conservative_acceptance():
    assert hud.accepted_speed('85', 91) == 85
    assert hud.accepted_speed('14', 99) is None
    assert hud.accepted_speed('4', 95) is None
    assert hud.accepted_speed('85', 49.9) is None
    assert hud.accepted_speed('８５', 99) is None
    for value in (float('nan'), float('inf'), -float('inf')):
        assert hud.accepted_speed('85', value) is None


def test_tsv_requires_one_word_and_valid_confidence():
    header = 'level\tconf\ttext\n'
    assert hud.parse_tsv(header + '5\t89.1\t85\n') == ('85', 89.1)
    for body in ('5\t89.1\t85\n5\t90\t4\n', '5\tbad\t85\n',
                 '5\tnan\t85\n', '5\tinf\t85\n', '5\t101\t85\n', '5\t85\n'):
        assert hud.parse_tsv(header + body) == ('', -1.0)


@pytest.fixture
def setup_capture(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'video.h264').write_bytes(b'video')
    (source / 'manifest.json').write_bytes(b'manifest')
    exe = tmp_path / 'ocr.exe'
    exe.write_bytes(b'fake executable')
    exe.chmod(0o755)
    capture = SimpleNamespace(geometry=(1920, 1080), originals={'manifest.json': b'manifest'})
    monkeypatch.setattr(hud, '_initialize', lambda: None)
    monkeypatch.setattr(hud, '_validate', lambda _: capture)
    monkeypatch.setattr(hud, '_decode', lambda _: iter([
        ({'index': i, 'relative_ticks_90k': i * 3000}, object()) for i in range(7)]))
    monkeypatch.setattr(hud, '_ocr', lambda frame, executable, env, timeout: ('85', 90.0))
    return source, exe, capture


def test_receipt_binds_source_and_csv_and_sampling(tmp_path, setup_capture):
    source, exe, _ = setup_capture
    out = tmp_path / 'output.csv'
    receipt = hud.run(source, out, exe, step=3)
    assert receipt['source_video_sha256'] == hashlib.sha256(b'video').hexdigest()
    assert receipt['source_manifest_sha256'] == hashlib.sha256(b'manifest').hexdigest()
    assert receipt['output_csv_sha256'] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert (receipt['selected_count'], receipt['accepted_count'], receipt['unknown_count']) == (3, 3, 0)
    assert receipt['units'] == 'game_hud_kmh' and receipt['world_metric'] is False
    assert receipt['source_modified'] is False and receipt['unselected_frames'] == 'unknown'
    assert json.loads(Path(str(out) + '.receipt.json').read_text()) == receipt


def test_unknown_and_no_overwrite(tmp_path, setup_capture, monkeypatch):
    source, exe, _ = setup_capture
    out = tmp_path / 'output.csv'
    monkeypatch.setattr(hud, '_ocr', lambda *args: ('14', 99.0))
    receipt = hud.run(source, out, exe)
    assert receipt['accepted_count'] == 0 and receipt['unknown_count'] == 3
    old = out.read_bytes()
    with pytest.raises(FileExistsError):
        hud.run(source, out, exe)
    assert out.read_bytes() == old
    second = tmp_path / 'second.csv'
    Path(str(second) + '.receipt.json').write_text('preserve')
    with pytest.raises(FileExistsError):
        hud.run(source, second, exe)
    assert not second.exists()
    assert Path(str(second) + '.receipt.json').read_text() == 'preserve'


def test_cancel_and_changed_source_leave_no_outputs(tmp_path, setup_capture, monkeypatch):
    source, exe, _ = setup_capture
    out = tmp_path / 'output.csv'
    def cancel(*args):
        raise InterruptedError('cancel')
    monkeypatch.setattr(hud, '_ocr', cancel)
    with pytest.raises(InterruptedError):
        hud.run(source, out, exe)
    assert not out.exists() and not Path(str(out) + '.receipt.json').exists()
    def mutate(*args):
        (source / 'video.h264').write_bytes(b'changed')
        return '85', 90.0
    monkeypatch.setattr(hud, '_ocr', mutate)
    with pytest.raises(RuntimeError, match='source changed'):
        hud.run(source, out, exe)
    assert not out.exists() and not Path(str(out) + '.receipt.json').exists()


def test_quotas_geometry_and_source_output(tmp_path, setup_capture):
    source, exe, capture = setup_capture
    out = tmp_path / 'output.csv'
    for step in (0, 31, True, 1.5):
        with pytest.raises(ValueError):
            hud.run(source, out, exe, step=step)
    for seconds in (0, 91, float('nan'), float('inf'), True):
        with pytest.raises(ValueError):
            hud.run(source, out, exe, max_seconds=seconds)
    with pytest.raises(ValueError):
        hud.run(source, source / 'out.csv', exe)
    capture.geometry = (1280, 720)
    with pytest.raises(ValueError, match='geometry'):
        hud.run(source, out, exe)
    assert not out.exists()


def test_checkpoint_cancel_and_missing_binary(tmp_path, setup_capture, monkeypatch):
    source, exe, _ = setup_capture
    out = tmp_path / 'output.csv'
    with pytest.raises(ValueError, match='executable'):
        hud.run(source, out, tmp_path / 'missing.exe')
    state = {'cancel': False}

    def checkpoint():
        if state['cancel']:
            raise InterruptedError('cancelled')

    def ocr(*args):
        state['cancel'] = True
        return '85', 90.0

    monkeypatch.setattr(hud, '_ocr', ocr)
    with pytest.raises(InterruptedError, match='cancelled'):
        hud.run(source, out, exe, checkpoint=checkpoint)
    assert not out.exists() and not Path(str(out) + '.receipt.json').exists()


def test_manifest_binding_rejected(tmp_path, setup_capture):
    source, exe, capture = setup_capture
    capture.originals['manifest.json'] = b'different'
    out = tmp_path / 'output.csv'
    with pytest.raises(ValueError, match='metadata changed'):
        hud.run(source, out, exe)
    assert not out.exists()
