"""Resolve preparation masks from the selected geometry's recorded provenance.

Older jobs and alternative native bundles have no source-bound mask plan. Their
existing preparation behaviour is retained and labelled as unrecorded; a job's
recipe must never be attributed to a different alternative geometry.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.pilot.route_masks import WATERMARK, capture_mask_plan
from scripts.pilot.route_reconstruction_recipe import SCHEMA as RECIPE_SCHEMA


def _digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('route_mask_plan_source_binding')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def preparation_control(job):
    """Read a bounded control snapshot, retaining its exact bytes for the fence."""
    path = Path(job) / 'control.json'
    if not path.exists() and not path.is_symlink():
        return {}, None
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
        raise ValueError('route_mask_plan_source_binding')
    try:
        raw = path.read_bytes()
        if not 0 < len(raw) <= 65536:
            raise ValueError()
        control = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('route_mask_plan_source_binding') from exc
    if not isinstance(control, dict):
        raise ValueError('route_mask_plan_source_binding')
    return control, hashlib.sha256(raw).hexdigest()


def preparation_mask(job, selected, manifest, control, *, manifest_bytes):
    """Return exclusions and an explicit provenance record for a new attempt."""
    job = Path(job)
    if not isinstance(selected, dict) or not isinstance(manifest, dict) or not isinstance(control, dict):
        raise ValueError('route_mask_plan_invalid')
    if not isinstance(manifest_bytes, bytes):
        raise ValueError('route_mask_plan_source_binding')
    try:
        decoded_manifest = json.loads(manifest_bytes, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ValueError('route_mask_plan_source_binding') from exc
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if decoded_manifest != manifest or _digest(job / 'input/manifest.json') != manifest_hash:
        raise ValueError('route_mask_plan_source_binding')
    mode = control.get('mask', 'none')
    recipe_path = job / 'reconstruction-recipe.json'
    recipe = None
    status = 'historical_recipe_unrecorded'
    if selected.get('binding') is not None:
        # A parent recipe's geometry hash says nothing about an alternate's
        # independently produced native model, even if the capture is shared.
        status = 'alternative_recipe_unrecorded'
    elif recipe_path.exists() or recipe_path.is_symlink():
        if recipe_path.is_symlink() or not recipe_path.is_file() or recipe_path.stat().st_size > 256 * 1024:
            raise ValueError('route_mask_plan_invalid')
        try:
            recipe = json.loads(recipe_path.read_bytes(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError('route_mask_plan_invalid') from exc
        if not isinstance(recipe, dict) or recipe.get('schema') != RECIPE_SCHEMA:
            raise ValueError('route_mask_plan_invalid')
        has_plan = 'mask_plan' in recipe
        has_hash = 'mask_plan_sha256' in recipe
        if has_plan != has_hash:
            raise ValueError('route_mask_plan_invalid')
        if not has_plan:
            recipe = None
            status = 'historical_plan_unrecorded'

    if recipe is None:
        try:
            plan = capture_mask_plan(mode, manifest)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError('route_mask_plan_invalid') from exc
    else:
        source = recipe.get('source')
        if not isinstance(source, dict):
            raise ValueError('route_mask_plan_source_binding')
        bindings = {'manifest_sha256': job / 'input/manifest.json',
                    'reconstruction_input_sha256': job / 'prepared/reconstruction-input.json',
                    'geometry_sha256': Path(selected['geometry_path'])}
        if source.get('manifest_sha256') != manifest_hash or any(
            source.get(key) != _digest(path) for key, path in bindings.items()
        ):
            raise ValueError('route_mask_plan_source_binding')
        plan = recipe['mask_plan']
        if not isinstance(plan, dict) or not isinstance(plan.get('sha256'), str):
            raise ValueError('route_mask_plan_invalid')
        unsigned = {key: value for key, value in plan.items() if key != 'sha256'}
        try:
            actual = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':'),
                                               allow_nan=False).encode()).hexdigest()
            policy = plan.get('policy_id')
            expected = capture_mask_plan(mode, manifest, policy_id=None if policy == 'generic_rect_v1' else policy)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError('route_mask_plan_invalid') from exc
        if plan['sha256'] != actual or recipe['mask_plan_sha256'] != actual or plan != expected:
            raise ValueError('route_mask_plan_invalid')
        status = 'source_bound_recipe'

    # Schema v1 profiles require at least one exclusion, including mode=none.
    exclusions = tuple(tuple(rect) for rect in plan['excluded_rectangles'])
    fallback_watermark = not exclusions
    return exclusions or (WATERMARK,), dict(status=status, policy_id=plan['policy_id'],
        mask_plan_sha256=plan['sha256'], profile_watermark_fallback=fallback_watermark,
        scope='base_reconstruction_mask_only', endpoint_resection_mask_parity='unverified')
