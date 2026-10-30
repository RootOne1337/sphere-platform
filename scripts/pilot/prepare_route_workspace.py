"""One explicit offline preparation of an existing scene for manual localization."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_workspace import ID, ROOT, checked_json, resource_checkpoint, route_resource_profile


def source_endpoint_coverage(frames, first_seconds, last_seconds):
    """A sparse model cannot silently stop before the recorded passage ends."""
    from motor_worker.route_localization import MAX_REFERENCE_INTERVAL_SECONDS

    if not frames:
        raise ValueError('route_source_frames_missing')
    start = frames[0]['relative_ticks_90k'] / 90000
    end = frames[-1]['relative_ticks_90k'] / 90000
    missing_start = max(0., first_seconds-start)
    missing_end = max(0., end-last_seconds)
    return dict(recording_start_seconds=start, recording_end_seconds=end,
                uncovered_start_seconds=missing_start, uncovered_end_seconds=missing_end,
                limit_seconds=MAX_REFERENCE_INTERVAL_SECONDS,
                endpoints_observed=missing_start <= MAX_REFERENCE_INTERVAL_SECONDS
                and missing_end <= MAX_REFERENCE_INTERVAL_SECONDS)


def route_source_model(job):
    """Prefer hash-bound sparse geometry; retain legacy complete scenes."""
    from scripts.pilot.sparse_scene_receipt import verify_sparse_receipt
    if (job/'sparse-receipt.json').exists():
        verify_sparse_receipt(job)
        return job/'prepared/sparse/0'
    from scripts.pilot.reconstruct_surface import source_model
    return source_model(job)[0]


def prepare(job, attempt):
    import cv2

    from motor_worker.browser_teach import validate_browser
    from motor_worker.landmarks import RouteViewProfile
    from scripts.pilot.export_route_localization import export
    from scripts.pilot.route_motion_audit import audit

    if not ID.fullmatch(attempt):
        raise ValueError('route_preparation_id')
    folder = job/'navigation'/attempt
    if checked_json(folder/'intent.json')['id'] != attempt:
        raise ValueError('route_intent_missing')
    profile_budget = route_resource_profile(job)
    bounded = lambda target: resource_checkpoint(target, profile=profile_budget)
    bounded(folder)
    sys.path.insert(0, str(ROOT/'.local-pilot/reconstruction-tools/pycolmap-4.2.1'))
    cv2.setNumThreads(2)
    model = route_source_model(job)
    geometry_raw = (job/'geometry.json').read_bytes()
    geometry = json.loads(geometry_raw)
    motion = audit(geometry)
    if motion['rapid_reversals'] or motion['speed_outliers']:
        raise ValueError('route_camera_motion_requires_review')
    capture = validate_browser(job/'input')
    width, height = capture.geometry
    from scripts.pilot.route_masks import excluded_rectangles, WATERMARK
    control = checked_json(job/'control.json') if (job/'control.json').exists() else {}
    excluded = excluded_rectangles(control.get('mask', 'none')) or (WATERMARK,)
    profile = RouteViewProfile(str(uuid.uuid4()), width, height, (0., 0., 1., 1.), excluded)
    write_json(folder/'state.json', dict(phase='features'))
    receipt = export(model, job/'prepared/reconstruction-input.json', job/'prepared/images',
        folder/'route.json', profile=profile, world_revision=str(uuid.uuid4()), checkpoint_fn=bounded)
    receipt['source_coverage'] = source_endpoint_coverage(capture.frames, receipt['first_seconds'], receipt['last_seconds'])
    receipt['geometry_sha256'] = hashlib.sha256(geometry_raw).hexdigest()
    if route_source_model(job) != model:
        raise ValueError('route_source_changed')
    if hashlib.sha256((job/'geometry.json').read_bytes()).hexdigest() != receipt['geometry_sha256']:
        raise ValueError('route_source_changed')
    write_json(folder/'receipt.json', receipt)
    supported = (receipt['map_support']['all_reference_neighborhoods_supported']
                 and receipt['map_support']['all_reference_intervals_observed']
                 and receipt['source_coverage']['endpoints_observed'])
    write_json(folder/'state.json', dict(phase='ready' if supported else 'rejected',
        error=None if supported else 'route_map_has_unobserved_sections',
        cameraTraceOnly=True, executionQualified=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    job = args.job.resolve(strict=True)
    if not ID.fullmatch(args.attempt):
        raise ValueError('route_preparation_id')
    try:
        prepare(job, args.attempt)
    except Exception as exc:
        # Keep fixed error names; never include arbitrary local paths/records.
        allowed = {'resource_guard', 'cancelled', 'route_camera_motion_requires_review',
                   'route_map_has_unobserved_sections', 'sparse_export_time_quota', 'route_source_changed',
                   'camera_intrinsics_degenerate', 'sparse_receipt_invalid', 'sparse_source_changed',
                   'sparse_source_missing_or_symlink', 'sparse_quality_gate_failed'}
        reason = str(exc) if str(exc) in allowed else 'route_preparation_failed_inspect_local_log'
        write_json(job/'navigation'/args.attempt/'state.json', dict(phase='failed', error=reason))
        raise


if __name__ == '__main__':
    main()
