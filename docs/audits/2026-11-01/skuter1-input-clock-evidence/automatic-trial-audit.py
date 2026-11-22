"""Read-only residual audit of the isolated actual helper output; no solve."""
import ctypes
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pycolmap as p

from scripts.pilot.atomic_json import write_json
from scripts.pilot.resource_guard import windows_memory
from scripts.pilot.route_component_merge import _child_affinity

out = Path('.local-pilot/skuter1-automatic-postprocess-20261101-v1').resolve()
assert not (out / 'outcome.json').exists()
began = time.monotonic()
_child_affinity(os.getpid())

def check():
    memory = windows_memory()
    assert memory['availableRamBytes'] >= 2 * 2**30
    assert memory['commitLimitBytes'] - memory['committedBytes'] >= 2 * 2**30
    assert memory['committedBytes'] / memory['commitLimitBytes'] < .9
    assert time.monotonic() - began <= 30

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def summary(values):
    values = np.asarray(values)
    assert np.isfinite(values).all() and len(values)
    return dict(count=len(values), mean=float(values.mean()), median=float(np.median(values)),
        p95=float(np.percentile(values, 95)), maximum=float(values.max()),
        above4=int((values > 4).sum()))

merge_receipt = json.loads((out / 'merge-receipt.json').read_bytes())
endpoint_receipt = json.loads((out / 'endpoints-receipt.json').read_bytes())
assert merge_receipt['status'] == endpoint_receipt['status'] == 'completed'
assert merge_receipt['source_before'] == merge_receipt['source_after'] == endpoint_receipt['source_before'] == endpoint_receipt['source_after']
check()
merged, final = p.Reconstruction(out / 'merge-chosen'), p.Reconstruction(out / 'final-chosen')
new_ids = set(final.reg_image_ids()) - set(merged.reg_image_ids())
all_errors, endpoint_errors = [], []
negative = nonfinite = 0
for image_id in final.reg_image_ids():
    check()
    image = final.images[image_id]
    observations = [obs for obs in image.points2D if obs.has_point3D()]
    xyz = np.asarray([final.points3D[v.point3D_id].xyz for v in observations])
    pose = image.cam_from_world()
    camera_xyz = xyz @ pose.rotation.matrix().T + pose.translation
    errors = np.linalg.norm(final.cameras[image.camera_id].img_from_cam(camera_xyz)
                            - np.asarray([v.xy for v in observations]), axis=1)
    negative += int((camera_xyz[:, 2] <= 0).sum())
    nonfinite += int((~np.isfinite(errors)).sum())
    all_errors.extend(errors)
    if image_id in new_ids:
        endpoint_errors.extend(errors)
max_pose_delta = max(float(np.max(np.abs(merged.images[i].cam_from_world().matrix()
                                        - final.images[i].cam_from_world().matrix()))) for i in merged.reg_image_ids())
max_xyz_delta = max(float(np.max(np.abs(v.xyz - final.points3D[k].xyz))) for k, v in merged.points3D.items())
assert negative == nonfinite == max_pose_delta == max_xyz_delta == 0
assert 'torch' not in sys.modules
outcome = dict(schema='sphere-automatic-postprocess-trial-v1', status='completed',
    scope='ISOLATED_OFFLINE_GEOMETRY_ONLY', selected=173, merged_registered=169,
    final_registered=173, points=final.num_points3D(),
    helper_source_sha256=dict(merge=merge_receipt['helper_sha256'], endpoint=endpoint_receipt['helper_sha256']),
    helper_receipts=dict(merge=dict(path='merge-receipt.json', sha256=sha(out / 'merge-receipt.json')),
                         endpoints=dict(path='endpoints-receipt.json', sha256=sha(out / 'endpoints-receipt.json'))),
    source_manifest_sha256=endpoint_receipt['source_before']['input/manifest.json'],
    source_video_sha256=endpoint_receipt['source_before']['input/video.h264'],
    source_unchanged=True, protected_source_file_count=len(endpoint_receipt['source_before']),
    model_files={path.relative_to(out).as_posix(): sha(path) for path in (out / 'final-chosen').iterdir()},
    endpoint_namespace='ENDPOINT_LK', further_original_db_matching=False,
    added_source_indices=[f['source_index'] for f in endpoint_receipt['helper_result']['frames'] if f['accepted']],
    source_start_seconds=0., source_end_seconds=36.903,
    source_coverage=endpoint_receipt['assessment']['source_coverage'],
    scene_admissible=endpoint_receipt['assessment']['scene_admissible'],
    route_admissible=endpoint_receipt['assessment']['route_admissible'],
    observation_support=endpoint_receipt['assessment']['observation_support']['summary'],
    structural=endpoint_receipt['structural'],
    all_observation_reprojection_px=summary(all_errors),
    new_endpoint_observation_reprojection_px=summary(endpoint_errors),
    stored_mean_point_error_px=final.compute_mean_reprojection_error(),
    stored_point_error_caveat='COLMAP point.error is unchanged on add_observation; use explicitly recomputed residuals above.',
    existing_pose_max_abs_delta=max_pose_delta, existing_xyz_max_abs_delta=max_xyz_delta,
    worker_seconds_sum=merge_receipt['seconds'] + endpoint_receipt['seconds'],
    peak_worker_rss_bytes=max(merge_receipt['peak_own_rss_bytes'], endpoint_receipt['peak_own_rss_bytes']),
    minimum_host_ram_bytes=min(merge_receipt['min_host_available_bytes'], endpoint_receipt['min_host_available_bytes']),
    cpu_affinity_limit=2, feature_extractions=0, mapping_repeats=0, bundle_adjustment_runs=0,
    gpu_used=False, torch_imported=False, physical_actions=0, execution_qualified=False,
    navigation_qualified=False, poses_interpolated=False, metric_scale=None,
    production_publication=False, independent_ground_truth_available=False,
    caveat='Measured in-sample geometry and same-record endpoint heldout landmarks; no independent pose/scale/navigation validation.',
    residual_audit_seconds=time.monotonic()-began)
check()
write_json(out / 'outcome.json', outcome)
print(json.dumps(outcome, indent=2))
