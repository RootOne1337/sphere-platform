"""Mask placement precedes feature extraction and keeps original pixels intact."""
import hashlib
import json

import pytest


def test_sparse_only_seals_before_finishing_without_starting_dense(tmp_path, monkeypatch):
    from scripts.pilot import reconstruct_route, sparse_scene_receipt
    calls = []
    monkeypatch.setattr(sparse_scene_receipt, 'create_sparse_receipt', lambda job: calls.append(('seal', job)))
    monkeypatch.setattr(reconstruct_route, 'train_dense', lambda *args, **kwargs: calls.append(('dense', args)))
    reconstruct_route.finish_sparse(tmp_path, tmp_path, {}, {}, 'none', None, 30000, route_only=True)
    assert calls == [('seal', tmp_path)]
    assert json.loads((tmp_path/'state.json').read_text())['phase'] == 'sparse_complete'

from scripts.pilot.reconstruct_route import (
    brush_dataset,
    masked_inputs,
    preserve_checkpoint,
    validate_splats,
)


def test_separate_masks_preserve_source_and_exclude_avatar(tmp_path):
    image_module = pytest.importorskip('PIL.Image')
    images = tmp_path / 'images'
    images.mkdir()
    source = images / '000.png'
    image_module.new('RGB', (960, 540), (11, 22, 33)).save(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert masked_inputs(tmp_path, 'none') is None
    folder = masked_inputs(tmp_path, 'game')
    with image_module.open(folder / '000.png.png') as mask:
        assert mask.size == (960, 540)
        assert mask.getpixel((20, 20)) == 0
        assert mask.getpixel((480, 400)) == 0
        assert mask.getpixel((300, 300)) == 255
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def ply(path, *, nan=False):
    import struct

    fields = ['x', 'y', 'z', 'opacity', 'scale_0', 'scale_1', 'scale_2',
              'rot_0', 'rot_1', 'rot_2', 'rot_3', 'f_dc_0', 'f_dc_1', 'f_dc_2']
    header = 'ply\nformat binary_little_endian 1.0\nelement vertex 400\n'
    header += ''.join('property float ' + name + '\n' for name in fields) + 'end_header\n'
    values = [1.] * (400 * len(fields))
    if nan:
        values[-1] = float('nan')
    path.write_bytes(header.encode() + struct.pack('<' + 'f' * len(values), *values))


def test_all_exported_floats_are_validated(tmp_path):
    pytest.importorskip('numpy')
    path = tmp_path / 'scene.ply'
    ply(path)
    assert validate_splats(path)['vertices'] == 400
    ply(path, nan=True)
    with pytest.raises(RuntimeError, match='nonfinite'):
        validate_splats(path)
    ply(path)
    path.write_bytes(path.read_bytes()[:-4])
    with pytest.raises(RuntimeError, match='invalid_layout'):
        validate_splats(path)


def test_detail_checkpoints_fit_existing_disk_budget_at_full_splat_capacity():
    from scripts.pilot.reconstruction_quality import export_interval

    # The current degree-2 native PLY uses 38 float32 properties per splat.
    # Include a conservative 64 KiB header for each worst-case checkpoint.
    bytes_per_export = 750000 * 38 * 4 + 65536
    assert (30000 // export_interval(30000)) * bytes_per_export <= 2**31
    assert (30000 // 1000) * bytes_per_export > 2**31


def test_resource_refusal_retains_measurement_and_does_not_modify_input(tmp_path, monkeypatch):
    import json

    from scripts.pilot import reconstruct_route as route

    source = tmp_path / 'original.h264'
    source.write_bytes(b'original capture')
    snapshot = dict(availableRamBytes=2 * 1024**3, measurement='test fixture')
    monkeypatch.setattr(route, 'collect', lambda _: snapshot)
    monkeypatch.setattr(route, 'evaluate', lambda measured: ['ram_headroom_low'])
    with pytest.raises(RuntimeError, match='resource_guard'):
        route.checkpoint(tmp_path)
    receipt = json.loads((tmp_path / 'resource-refusal.json').read_text())
    assert receipt == dict(snapshot=snapshot, findings=['ram_headroom_low'])
    assert source.read_bytes() == b'original capture'


def test_failed_training_preserves_latest_valid_checkpoint_without_complete(tmp_path):
    import json

    pytest.importorskip('numpy')
    (tmp_path / 'dense').mkdir()
    ply(tmp_path / 'dense/scene_1000.ply')
    ply(tmp_path / 'dense/scene_2000.ply', nan=True)
    preserve_checkpoint(tmp_path, 5000)
    checkpoint = json.loads((tmp_path / 'checkpoint.json').read_text())
    assert checkpoint['steps'] == 1000 and checkpoint['partial'] is True
    assert not (tmp_path / 'COMPLETE').exists()


def test_brush_receives_only_one_model_and_only_its_registered_images(tmp_path):
    prepared = tmp_path / 'prepared'
    (prepared / 'images').mkdir(parents=True)
    (prepared / 'sparse/0').mkdir(parents=True)
    (prepared / 'models/1').mkdir(parents=True)
    (prepared / 'masks').mkdir()
    for name in ('cameras.bin', 'images.bin', 'points3D.bin'):
        (prepared / 'sparse/0' / name).write_bytes(b'selected')
        (prepared / 'models/1' / name).write_bytes(b'wrong-component')
    for name in ('00000001.png', '00000002.png'):
        (prepared / 'images' / name).write_bytes(b'RGB')
        (prepared / 'masks' / name).write_bytes(b'mask')
    folder = brush_dataset(tmp_path, prepared, ['00000001.png'])
    assert len(list(folder.rglob('points3D.bin'))) == 1
    assert (folder / 'sparse/0/points3D.bin').read_bytes() == b'selected'
    assert [path.name for path in (folder / 'images').iterdir()] == ['00000001.png']
    assert not (folder / 'models').exists()
