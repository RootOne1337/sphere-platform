"""Mask placement precedes feature extraction and keeps original pixels intact."""
import hashlib

import pytest

from scripts.pilot.reconstruct_route import masked_inputs


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
