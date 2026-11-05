import hashlib
import json

import pytest

from scripts.pilot.route_masks import (
    LEGACY_SCOOTER_POLICY,
    PRECISE_SCOOTER_POLICY,
    WATERMARK,
    capture_mask_plan,
)
from scripts.pilot.route_preparation_mask import preparation_control, preparation_mask
from scripts.pilot.route_reconstruction_recipe import SCHEMA

MANIFEST = {'config': {'profile': {'mode': 'vehicle_buttons',
                                   'hudProfile': 'black_russia_scooter_v1'}}}


def resolve(job, selected, manifest, control):
    return preparation_mask(job, selected, manifest, control,
                            manifest_bytes=(job / 'input/manifest.json').read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_job(tmp_path, policy=LEGACY_SCOOTER_POLICY):
    (tmp_path / 'input').mkdir()
    (tmp_path / 'prepared').mkdir()
    (tmp_path / 'input/manifest.json').write_text(json.dumps(MANIFEST))
    (tmp_path / 'prepared/reconstruction-input.json').write_text('{}')
    (tmp_path / 'geometry.json').write_text('{"geometry":1}')
    plan = capture_mask_plan('game', MANIFEST, policy_id=policy)
    recipe = {'schema': SCHEMA, 'source': {
        'manifest_sha256': digest(tmp_path / 'input/manifest.json'),
        'reconstruction_input_sha256': digest(tmp_path / 'prepared/reconstruction-input.json'),
        'geometry_sha256': digest(tmp_path / 'geometry.json'),
    }, 'mask_plan': plan, 'mask_plan_sha256': plan['sha256']}
    (tmp_path / 'reconstruction-recipe.json').write_text(json.dumps(recipe))
    return recipe, {'binding': None, 'geometry_path': tmp_path / 'geometry.json'}


def write_recipe(job, recipe):
    (job / 'reconstruction-recipe.json').write_text(json.dumps(recipe))


def test_recorded_legacy_policy_wins_over_current_default(tmp_path):
    recipe, selected = make_job(tmp_path)
    excluded, provenance = resolve(tmp_path, selected, MANIFEST, {'mask': 'game'})
    assert excluded == tuple(map(tuple, recipe['mask_plan']['excluded_rectangles']))
    assert provenance['status'] == 'source_bound_recipe'
    assert provenance['policy_id'] == LEGACY_SCOOTER_POLICY
    assert provenance['scope'] == 'base_reconstruction_mask_only'
    assert provenance['endpoint_resection_mask_parity'] == 'unverified'
    assert capture_mask_plan('game', MANIFEST)['policy_id'] == PRECISE_SCOOTER_POLICY


@pytest.mark.parametrize('change', ['hash', 'plan', 'mode', 'geometry', 'manifest', 'prepared', 'incomplete'])
def test_bad_or_mismatched_recorded_plan_refuses_preparation(tmp_path, change):
    recipe, selected = make_job(tmp_path)
    control = {'mask': 'game'}
    if change == 'hash':
        recipe['mask_plan_sha256'] = '0' * 64
    elif change == 'plan':
        recipe['mask_plan']['excluded_rectangles'][0][0] = .123
    elif change == 'mode':
        control['mask'] = 'avatar'
    elif change == 'geometry':
        (tmp_path / 'geometry.json').write_text('{"geometry":2}')
    elif change == 'manifest':
        (tmp_path / 'input/manifest.json').write_text('{}')
    elif change == 'prepared':
        (tmp_path / 'prepared/reconstruction-input.json').write_text('{"changed":true}')
    elif change == 'incomplete':
        recipe.pop('mask_plan_sha256')
    write_recipe(tmp_path, recipe)
    with pytest.raises(ValueError, match='route_mask_plan_'):
        resolve(tmp_path, selected, MANIFEST, control)


def test_unrecorded_and_legacy_none_remain_explicit(tmp_path):
    _, selected = make_job(tmp_path)
    (tmp_path / 'reconstruction-recipe.json').unlink()
    excluded, provenance = resolve(tmp_path, selected, MANIFEST, {'mask': 'none'})
    assert excluded == (WATERMARK,)
    assert provenance['status'] == 'historical_recipe_unrecorded'
    assert provenance['profile_watermark_fallback'] is True


def test_unrecorded_plan_in_older_recipe_remains_explicit(tmp_path):
    recipe, selected = make_job(tmp_path)
    del recipe['mask_plan'], recipe['mask_plan_sha256']
    write_recipe(tmp_path, recipe)
    _, provenance = resolve(tmp_path, selected, MANIFEST, {'mask': 'game'})
    assert provenance['status'] == 'historical_plan_unrecorded'


def test_rehashed_altered_policy_is_rejected(tmp_path):
    recipe, selected = make_job(tmp_path)
    plan = recipe['mask_plan']
    plan['excluded_rectangles'][0][0] = .123
    content = {key: value for key, value in plan.items() if key != 'sha256'}
    plan['sha256'] = hashlib.sha256(json.dumps(
        content, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    recipe['mask_plan_sha256'] = plan['sha256']
    write_recipe(tmp_path, recipe)
    with pytest.raises(ValueError, match='route_mask_plan_invalid'):
        resolve(tmp_path, selected, MANIFEST, {'mask': 'game'})


def test_alternative_does_not_inherit_parent_geometry_recipe(tmp_path):
    recipe, _ = make_job(tmp_path)
    selected = {'binding': {'alternative_id': 'another-model'},
                'geometry_path': tmp_path / 'alternative-geometry.json'}
    excluded, provenance = resolve(tmp_path, selected, MANIFEST, {'mask': 'game'})
    assert provenance['status'] == 'alternative_recipe_unrecorded'
    assert provenance['policy_id'] == PRECISE_SCOOTER_POLICY
    assert excluded != tuple(map(tuple, recipe['mask_plan']['excluded_rectangles']))


def test_present_corrupt_recipe_does_not_fall_back(tmp_path):
    _, selected = make_job(tmp_path)
    (tmp_path / 'reconstruction-recipe.json').write_text('{broken')
    with pytest.raises(ValueError, match='route_mask_plan_invalid'):
        resolve(tmp_path, selected, MANIFEST, {'mask': 'game'})


@pytest.mark.parametrize('historical', [True, False])
def test_invalid_control_mode_uses_stable_error(tmp_path, historical):
    _, selected = make_job(tmp_path)
    if historical:
        (tmp_path / 'reconstruction-recipe.json').unlink()
    with pytest.raises(ValueError, match='^route_mask_plan_invalid$'):
        resolve(tmp_path, selected, MANIFEST, {'mask': 'invalid'})


def test_capture_snapshot_and_current_manifest_are_bound(tmp_path):
    _, selected = make_job(tmp_path)
    original = (tmp_path / 'input/manifest.json').read_bytes()
    # Even if a recipe is modified to bind new disk bytes, the parsed capture
    # snapshot must not be used with those new bytes.
    (tmp_path / 'input/manifest.json').write_text(json.dumps(MANIFEST, indent=2))
    with pytest.raises(ValueError, match='route_mask_plan_source_binding'):
        preparation_mask(tmp_path, selected, MANIFEST, {'mask': 'game'}, manifest_bytes=original)


def test_control_snapshot_detects_changed_bytes_and_absence(tmp_path):
    assert preparation_control(tmp_path) == ({}, None)
    path = tmp_path / 'control.json'
    path.write_text('{"mask":"game"}')
    first, first_digest = preparation_control(tmp_path)
    path.write_text('{ "mask": "game" }')
    second, second_digest = preparation_control(tmp_path)
    assert first == second == {'mask': 'game'}
    assert first_digest != second_digest
