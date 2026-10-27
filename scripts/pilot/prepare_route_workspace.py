"""One explicit offline preparation of an existing scene for manual localization."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_workspace import ID, ROOT, checked_json, resource_checkpoint


def prepare(job, attempt):
    import cv2

    from motor_worker.browser_teach import validate_browser
    from motor_worker.landmarks import RouteViewProfile
    from scripts.pilot.export_route_localization import export
    from scripts.pilot.reconstruct_surface import source_model
    from scripts.pilot.route_motion_audit import audit

    if not ID.fullmatch(attempt):
        raise ValueError('route_preparation_id')
    folder = job/'navigation'/attempt
    if checked_json(folder/'intent.json')['id'] != attempt:
        raise ValueError('route_intent_missing')
    resource_checkpoint(folder)
    sys.path.insert(0, str(ROOT/'.local-pilot/reconstruction-tools/pycolmap-4.2.1'))
    cv2.setNumThreads(8)
    model, _ = source_model(job)
    geometry_raw = (job/'geometry.json').read_bytes()
    geometry = json.loads(geometry_raw)
    motion = audit(geometry)
    if motion['rapid_reversals'] or motion['speed_outliers']:
        raise ValueError('route_camera_motion_requires_review')
    capture = validate_browser(job/'input')
    width, height = capture.geometry
    profile = RouteViewProfile(str(uuid.uuid4()), width, height, (0., 0., 1., 1.), ((0., .975, 1., 1.),))
    write_json(folder/'state.json', dict(phase='features'))
    receipt = export(model, job/'prepared/reconstruction-input.json', job/'prepared/images',
        folder/'route.json', profile=profile, world_revision=str(uuid.uuid4()), checkpoint_fn=resource_checkpoint)
    receipt['geometry_sha256'] = hashlib.sha256(geometry_raw).hexdigest()
    if hashlib.sha256((job/'geometry.json').read_bytes()).hexdigest() != receipt['geometry_sha256']:
        raise ValueError('route_source_changed')
    write_json(folder/'receipt.json', receipt)
    supported = receipt['map_support']['all_reference_neighborhoods_supported']
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
                   'camera_intrinsics_degenerate'}
        reason = str(exc) if str(exc) in allowed else 'route_preparation_failed_inspect_local_log'
        write_json(job/'navigation'/args.attempt/'state.json', dict(phase='failed', error=reason))
        raise


if __name__ == '__main__':
    main()
