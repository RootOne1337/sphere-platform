"""Bounded reconstruction provenance; never an authorization to drive.

Keep the executed recipe separate from map-support and live-control admission.
Historical geometry without a recipe stays inspectable, with unknown provenance.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from scripts.pilot.atomic_json import write_json

SCHEMA = 'sphere-route-reconstruction-recipe-v1'
RECIPE_ID = 'video-fb-lk-incremental-colmap-v1'
RECOVERY_SCHEMA = 'sphere-fused-route-recovery-v1'


def _digest(path):
    if not path.is_file() or path.is_symlink():
        return None
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def route_recipe(job, prepared, *, vehicle, fused_enabled):
    """Describe this worker's route-only path, not a historical experiment."""
    root = Path(__file__).resolve().parents[2]
    producer_names = ('reconstruct_route.py', 'route_video_tracks.py',
                      'route_motion_sampling.py', 'route_fused_recovery.py',
                      'route_native_track_policy.py', 'route_reconstruction_recipe.py')
    return dict(schema=SCHEMA, recipe_id=RECIPE_ID,
        source=dict(manifest_sha256=_digest(job/'input/manifest.json'),
                    reconstruction_input_sha256=_digest(prepared/'reconstruction-input.json')),
        producer_sources={name: _digest(root/'scripts/pilot'/name) for name in producer_names},
        features=dict(method='source_video_corner_tracks', wide_tracking=vehicle),
        mapping=dict(method='incremental_mapping', pycolmap_version='4.2.1',
                     random_seed=17, maximum_models=4),
        fused_recovery=dict(schema=RECOVERY_SCHEMA, enabled=fused_enabled,
                            attempted=False, accepted=False, reason='not_evaluated'),
        execution_qualified=False)


def record_fused_decision(recipe, decision):
    """Only include bounded declared outcomes, never raw matching tables."""
    recipe['fused_recovery'] = {key: decision.get(key) for key in
        ('schema', 'enabled', 'attempted', 'accepted', 'reason', 'matcher')}


def bind_geometry(recipe, geometry_path):
    recipe['source']['geometry_sha256'] = _digest(geometry_path)


def persist_progress(job, recipe, decision):
    """Leave an honest first-pass receipt if an optional candidate is aborted."""
    record_fused_decision(recipe, decision)
    write_json(job/'reconstruction-recipe.json', recipe)
    path = job/'quality.json'
    if path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 65536:
        quality = json.loads(path.read_bytes())
        quality.update(reconstruction_recipe=recipe, fused_recovery=recipe['fused_recovery'])
        write_json(path, quality)


def admission_ladder(job, result, *, read_json, digest):
    """Summarize existing gates. This helper cannot change a gate outcome.

    Never infer that a visually dense model, known recipe or source-time coverage
    proves localization on unseen frames, input delivery, or route completion.
    """
    recipe_summary = dict(status='unknown', reason='historical_recipe_unrecorded')
    geometry = dict(status='unknown', reason='geometry_not_bound_to_recipe')
    quality_path = job/'quality.json'
    try:
        quality = read_json(quality_path) if quality_path.is_file() else {}
        if not isinstance(quality, dict):
            raise ValueError('recipe_quality_not_object')
        recipe = quality.get('reconstruction_recipe')
        if isinstance(recipe, dict) and recipe.get('schema') == SCHEMA:
            source = recipe.get('source') if isinstance(recipe.get('source'), dict) else {}
            bindings = (('manifest_sha256', job/'input/manifest.json'),
                        ('reconstruction_input_sha256', job/'prepared/reconstruction-input.json'),
                        ('geometry_sha256', job/'geometry.json'))
            bound = all(isinstance(source.get(key), str) and path.is_file()
                        and source[key] == digest(path) for key, path in bindings)
            recipe_summary = dict(status='recorded' if bound else 'source_changed',
                                  recipe_id=recipe.get('recipe_id'),
                                  reason='recorded_source_bound_recipe' if bound else 'recipe_source_binding_mismatch')
            if bound:
                selection = quality.get('selection') or {}
                accepted = selection.get('route_admissible') is True and quality.get('first_pass_only') is not True
                geometry = dict(status='accepted' if accepted else 'not_admitted',
                                reason='native_geometry_gate' if accepted else 'native_geometry_incomplete_or_rejected')
                for key in ('registered', 'selected', 'points'):
                    value = quality.get(key)
                    if type(value) is int and 0 <= value <= 10_000_000:
                        geometry[key] = value
    except (OSError, ValueError, TypeError, KeyError):
        recipe_summary = dict(status='unknown', reason='recipe_receipt_unreadable')
    phase = result.get('phase')
    runtime = dict(status='accepted' if phase == 'ready' else 'not_admitted',
                   reason='runtime_map_gate' if phase == 'ready' else result.get('error', phase))
    summary = result.get('summary') if isinstance(result.get('summary'), dict) else {}
    support = summary.get('map_support') if isinstance(summary.get('map_support'), dict) else {}
    coverage = summary.get('source_coverage') if isinstance(summary.get('source_coverage'), dict) else {}
    feature_pipeline = summary.get('pipeline_sha256')
    if (isinstance(feature_pipeline, str) and len(feature_pipeline) == 64
            and all(value in '0123456789abcdef' for value in feature_pipeline)):
        runtime['feature_pipeline_sha256'] = feature_pipeline
    for key in ('views_below_24', 'neighborhoods_below_24', 'min_correspondences_required'):
        if type(support.get(key)) is int and 0 <= support[key] <= 10_000_000:
            runtime[key] = support[key]
    for key in ('all_reference_neighborhoods_supported', 'all_reference_intervals_observed'):
        if type(support.get(key)) is bool:
            runtime[key] = support[key]
    if type(coverage.get('endpoints_observed')) is bool:
        runtime['endpoints_observed'] = coverage['endpoints_observed']
    # Display only measured numeric intervals and a fixed number of rows.
    intervals = []
    rows = support.get('unobserved_intervals')
    for row in (rows if isinstance(rows, list) else [])[:12]:
        if not isinstance(row, dict):
            continue
        start, end = row.get('start_seconds'), row.get('end_seconds')
        if (type(start) in {int, float} and type(end) in {int, float}
                and math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
            intervals.append(dict(start_seconds=start, end_seconds=end))
    if intervals:
        runtime['unobserved_intervals'] = intervals
    return dict(schema='sphere-route-admission-ladder-v1', recipe=recipe_summary,
                geometry=geometry, runtime_map=runtime,
                route_execution=dict(status='not_validated'), execution_qualified=False)
