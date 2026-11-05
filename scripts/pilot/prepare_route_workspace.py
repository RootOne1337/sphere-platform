"""One explicit offline preparation of an existing scene for manual localization."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_resource_monitor import TaskResourceMonitor
from scripts.pilot.route_workspace import (
    ID,
    ROOT,
    checked_json,
    resource_checkpoint,
    route_resource_profile,
)


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


def route_source_model(job, alternative_id=None):
    """Prefer hash-bound sparse geometry; retain legacy complete scenes."""
    if alternative_id is not None:
        from scripts.pilot.route_preparation_source import resolve_alternative_source
        return resolve_alternative_source(job, alternative_id)['model_path']
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
    intent = checked_json(folder/'intent.json')
    if intent['id'] != attempt:
        raise ValueError('route_intent_missing')
    task_folder = folder.resolve(strict=True)
    from scripts.pilot.route_preparation_source import attempt_cancelled
    profile_budget = route_resource_profile(job)
    # One preparation owns one volume proof. Every callback still reads fresh
    # native RAM/commit/disk; a monitor never survives this call or feeds live
    # sessions. Its context closes/reaps its own probe on every exit path.
    with TaskResourceMonitor(ROOT) as monitor:
        def bounded(target):
            if Path(target).resolve() != task_folder or folder.resolve() != task_folder:
                raise RuntimeError('route_resource_task_mismatch')
            # Check before sampling so cancellation cannot start a health probe.
            if attempt_cancelled(job, folder, intent=intent):
                raise RuntimeError('cancelled')
            snapshot = monitor.sample()
            if attempt_cancelled(job, folder, intent=intent):
                raise RuntimeError('cancelled')
            resource_checkpoint(target, profile=profile_budget, snapshot=snapshot)

        bounded(folder)
        sys.path.insert(0, str(ROOT/'.local-pilot/reconstruction-tools/pycolmap-4.2.1'))
        cv2.setNumThreads(2)
        from scripts.pilot.route_preparation_source import attempt_source
        selected = attempt_source(job, folder)
        model = selected['model_path'] or route_source_model(job)
        geometry_raw = selected['geometry_path'].read_bytes()
        geometry = json.loads(geometry_raw)
        motion = audit(geometry)
        if motion['rapid_reversals'] or motion['speed_outliers']:
            raise ValueError('route_camera_motion_requires_review')
        capture = validate_browser(job/'input')
        width, height = capture.geometry
        from scripts.pilot.route_preparation_mask import preparation_control, preparation_mask
        control, control_digest = preparation_control(job)
        manifest_bytes = capture.originals['manifest.json']
        excluded, mask_provenance = preparation_mask(
            job, selected, capture.manifest, control, manifest_bytes=manifest_bytes)
        profile = RouteViewProfile(str(uuid.uuid4()), width, height, (0., 0., 1., 1.), excluded)
        write_json(folder/'state.json', dict(phase='features'))
        if selected['binding'] is not None:
            from scripts.pilot.route_reference_lk_export import export as export_reference_lk
            receipt = export_reference_lk(model, job/'prepared/reconstruction-input.json', job/'prepared/images',
                folder/'route.json', profile=profile, world_revision=str(uuid.uuid4()), checkpoint_fn=bounded,
                source_geometry_sha256=selected['binding']['geometry_sha256'],
                source_model_sha256=selected['binding']['model_sha256'],
                source_capture_sha256=selected['binding']['source_manifest_sha256'],
                source_geometry_path=selected['geometry_path'])
            receipt['source_binding'] = selected['binding']
        else:
            receipt = export(model, job/'prepared/reconstruction-input.json', job/'prepared/images',
                folder/'route.json', profile=profile, world_revision=str(uuid.uuid4()), checkpoint_fn=bounded)
        bounded(folder)
        receipt['mask_provenance'] = mask_provenance
        receipt['source_coverage'] = source_endpoint_coverage(capture.frames, receipt['first_seconds'], receipt['last_seconds'])
        receipt['geometry_sha256'] = hashlib.sha256(geometry_raw).hexdigest()
        if attempt_source(job, folder) != selected:
            raise ValueError('route_source_changed')
        current_control, current_control_digest = preparation_control(job)
        if (current_control_digest != control_digest or current_control != control
                or preparation_mask(job, selected, capture.manifest, current_control,
                                    manifest_bytes=manifest_bytes) != (excluded, mask_provenance)):
            raise ValueError('route_mask_plan_source_binding')
        if selected['binding'] is None and route_source_model(job) != model:
            raise ValueError('route_source_changed')
        if hashlib.sha256(selected['geometry_path'].read_bytes()).hexdigest() != receipt['geometry_sha256']:
            raise ValueError('route_source_changed')
        bounded(folder)
        write_json(folder/'receipt.json', receipt)
        supported = (receipt['map_support']['all_reference_neighborhoods_supported']
                     and receipt['map_support']['all_reference_intervals_observed']
                     and receipt['source_coverage']['endpoints_observed'])
        phase = ('awaiting_qualification' if selected['binding'] is not None else 'ready') if supported else 'rejected'
        write_json(folder/'state.json', dict(phase=phase,
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
                   'sparse_source_missing_or_symlink', 'sparse_quality_gate_failed', 'route_resource_task_mismatch',
                   'route_preparation_source_changed', 'route_preparation_source_binding',
                   'route_alternative_native_missing', 'route_alternative_native_changed',
                   'route_alternative_native_binding', 'route_alternative_native_layout',
                   'route_alternative_native_evidence', 'route_alternative_geometry_not_admitted',
                   'route_mask_plan_invalid', 'route_mask_plan_source_binding'}
        reason = str(exc) if str(exc) in allowed else 'route_preparation_failed_inspect_local_log'
        write_json(job/'navigation'/args.attempt/'state.json', dict(phase='failed', error=reason))
        raise


if __name__ == '__main__':
    main()
