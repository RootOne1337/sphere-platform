import builtins
import hashlib
import json

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from motor_worker.landmarks import RouteViewProfile
from motor_worker.route_localization import feature_mask
from scripts.pilot.reconstruct_route import masked_inputs
from scripts.pilot.route_mask_raster import POLICY, raster_provenance, reconstruction_mask
from scripts.pilot.route_masks import LEGACY_SCOOTER_POLICY, capture_exclusions, capture_mask_plan
from scripts.pilot.route_reconstruction_recipe import route_recipe

VEHICLE = {'config': {'profile': {'mode': 'vehicle_buttons', 'hudProfile': 'black_russia_scooter_v1'}}}


def test_legacy_runtime_golden_is_unchanged():
    excluded = capture_exclusions('game', VEHICLE, policy_id=LEGACY_SCOOTER_POLICY)
    profile = RouteViewProfile('f6b07080-9380-40d9-90e8-b4405924c8cb', 1920, 1080,
                               (0., 0., 1., 1.), excluded)
    expected = feature_mask(profile)
    assert hashlib.sha256(expected.tobytes()).hexdigest() == '4fc84e852a6d26135c22a84e1f8cf86959f79ccf361c1db675911c29659580b2'
    assert np.array_equal(reconstruction_mask(excluded, (960, 540)), expected)


@pytest.mark.parametrize('size', [(1920, 1080), (1280, 720), (960, 540), (480, 270)])
def test_scaled_pixels_never_admit_an_excluded_canonical_cell(size):
    excluded = capture_exclusions('game', VEHICLE)
    canonical = reconstruction_mask(excluded, (960, 540))
    scaled = reconstruction_mask(excluded, size)
    width, height = size
    assert scaled.shape == (height, width)
    # Test cell overlap independently, including boundaries and a spread of pixels.
    rng = np.random.default_rng(17)
    for x, y in zip(rng.integers(0, width, 1000), rng.integers(0, height, 1000)):
        x0, x1 = x*960//width, ((x+1)*960+width-1)//width
        y0, y1 = y*540//height, ((y+1)*540+height-1)//height
        assert (scaled[y, x] == 255) == np.all(canonical[y0:y1, x0:x1] == 255)
    # Known HUD and world landmarks remain on the correct side of the domain.
    assert scaled[int(.07*height), int(.08*width)] == 0
    assert scaled[int(.4*height), int(.5*width)] == 255


def test_integer_upscale_preserves_runtime_mask_and_original_image(tmp_path):
    images = tmp_path/'images'
    images.mkdir()
    path = images/'frame.png'
    Image.new('RGB', (1920, 1080), (11, 22, 33)).save(path)
    original = path.read_bytes()
    output = masked_inputs(tmp_path, 'game', manifest=VEHICLE, route_only=True)
    image_mask = np.array(Image.open(output/'frame.png.png'))
    runtime = reconstruction_mask(capture_exclusions('game', VEHICLE), (960, 540))
    assert np.array_equal(image_mask, cv2.resize(runtime, (1920, 1080), interpolation=cv2.INTER_NEAREST))
    assert np.array_equal(cv2.resize(image_mask, (960, 540), interpolation=cv2.INTER_NEAREST), runtime)
    assert path.read_bytes() == original


def test_classic_mask_preserves_pil_rectangles_without_opencv(tmp_path, monkeypatch):
    images = tmp_path/'images'
    images.mkdir()
    size = (321, 181)
    Image.new('RGB', size).save(images/'frame.png')
    original_import = builtins.__import__

    def import_without_opencv(name, *args, **kwargs):
        if name == 'cv2' or name == 'scripts.pilot.route_mask_raster':
            raise ImportError(f'unavailable in classic environment: {name}')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', import_without_opencv)
    output = masked_inputs(tmp_path, 'game', manifest=VEHICLE)
    expected = Image.new('L', size, 255)
    draw = ImageDraw.Draw(expected)
    for a, b, c, d in capture_exclusions('game', VEHICLE):
        draw.rectangle((int(size[0]*a), int(size[1]*b), int(size[0]*c), int(size[1]*d)), fill=0)
    with Image.open(output/'frame.png.png') as actual:
        assert actual.tobytes() == expected.tobytes()


def test_none_preserves_unmasked_reconstruction_and_recipe_scopes_version(tmp_path):
    assert np.all(reconstruction_mask((), (480, 270)) == 255)
    (tmp_path/'input').mkdir()
    (tmp_path/'prepared').mkdir()
    (tmp_path/'input/manifest.json').write_text(json.dumps(VEHICLE))
    (tmp_path/'prepared/reconstruction-input.json').write_text('{}')
    (tmp_path/'control.json').write_text('{"mask":"game"}')
    before = capture_mask_plan('game', VEHICLE)
    recipe = route_recipe(tmp_path, tmp_path/'prepared', vehicle=True, fused_enabled=False)
    assert recipe['mask_plan'] == before == capture_mask_plan('game', VEHICLE)
    assert recipe['mask_rasterization'] == raster_provenance()
    assert recipe['mask_rasterization']['policy'] == POLICY
    assert recipe['mask_rasterization']['endpoint_resection'] == 'independent_mask_unverified'
    assert recipe['producer_sources']['route_mask_raster.py']
