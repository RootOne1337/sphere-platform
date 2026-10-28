"""One bounded automatic geometry repair within the original reconstruction job.

The baseline remains available. A candidate replaces it only after independent
coverage, conditioning, reprojection and temporal checks; motion is never drawn
in by interpolation or smoothing. This module never opens Android input.
"""
from __future__ import annotations

import math
import threading
import time

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_motion_audit import audit


def needs_repair(geometry, selected):
    motion = audit(geometry)
    return (len(geometry['cameras']) < selected or bool(motion['rapid_reversals'])
            or bool(motion['speed_outliers']))


def repair_temporally(job, prepared, database, baseline, selected, check, progress):
    import pycolmap as p
    from scripts.pilot.learned_route_features import verify_pairs
    from scripts.pilot.reconstruct_route import model_geometry
    from scripts.pilot.reconstruction_quality import pinhole_condition, sparse_condition
    from scripts.pilot.temporal_route_matches import filter_video_matches

    folder = prepared/'temporal-repair'
    if folder.exists():
        raise RuntimeError('temporal_repair_existing_intent')
    folder.mkdir()
    (folder/'models').mkdir()
    write_json(folder/'intent.json', dict(schema='sphere-temporal-repair-intent-v1',
        selected=selected, scope='OFFLINE_GEOMETRY_ONLY', physicalActions=0))
    target = folder/'database.db'
    progress('temporal_tracking')
    tracks = filter_video_matches(job, prepared, database, target, check, max_lag=8,
        on_progress=lambda done,total:progress('temporal_tracking',done,total))
    cameras = set()
    with p.Database.open(target) as db:
        for identity, reference in baseline.cameras.items():
            camera = db.read_camera(identity)
            camera.params = reference.params.copy()
            db.update_camera(camera)
            cameras.add(identity)
    pairs = folder/'pairs.txt'
    pairs.write_text(''.join(row['first']+' '+row['second']+'\n' for row in tracks['pairs'] if row['written']), encoding='ascii')
    token, done, reasons = p.CancellationToken(), threading.Event(), []

    def watch():
        deadline = time.monotonic()+210
        while not done.wait(3):
            try:
                check()
                if time.monotonic()>deadline:
                    raise RuntimeError('temporal_mapping_timeout')
            except RuntimeError as error:
                reasons.append(str(error)); token.cancel(); return

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        progress('temporal_verification')
        verify_pairs(target, pairs, token)
        if reasons:
            raise RuntimeError(reasons[0])
        progress('temporal_cameras')
        options = p.IncrementalPipelineOptions(num_threads=2, random_seed=17,
            max_runtime_seconds=180, max_num_models=4, constant_cameras=cameras,
            ba_refine_focal_length=False, ba_refine_extra_params=False,
            structure_less_registration_fallback=False, ba_refine_sensor_from_rig=False)
        options.mapper.abs_pose_refine_focal_length = False
        options.mapper.abs_pose_refine_extra_params = False
        models = p.incremental_mapping(target, prepared/'images', folder/'models',
            options=options, cancellation_token=token)
    finally:
        done.set(); thread.join(5)
    if reasons:
        raise RuntimeError(reasons[0])
    checked, eligible = [], []
    for identity, model in models.items():
        geometry = model_geometry(model, prepared)
        motion = audit(geometry)
        error = model.compute_mean_reprojection_error()
        intrinsic = geometry['cameras'][0]['intrinsics']
        condition = sparse_condition([camera['center'] for camera in geometry['cameras']],
                                     [point.xyz for point in model.points3D.values()])
        passed = (model.num_reg_images()==selected and model.num_points3D()>=300
                  and math.isfinite(error) and error<=3 and condition['passed']
                  and not motion['rapid_reversals'] and not motion['speed_outliers']
                  and pinhole_condition(intrinsic['width'],intrinsic['height'],intrinsic['fx'],intrinsic['fy'])['passed'])
        checked.append(dict(id=identity,cameras=model.num_reg_images(),points=model.num_points3D(),
                            reprojectionPx=error,rapidReversals=len(motion['rapid_reversals']),
                            speedOutliers=len(motion['speed_outliers']),accepted=passed))
        if passed:
            eligible.append(model)
    report = dict(schema='sphere-temporal-repair-result-v1',accepted=bool(eligible),
                  baselineCameras=baseline.num_reg_images(),decodedFrames=tracks['decodedFrames'],
                  models=checked,physicalActions=0,sourceModified=False,posesInterpolated=False)
    write_json(folder/'result.json',report)
    return (min(eligible,key=lambda model:model.compute_mean_reprojection_error()) if eligible else baseline),report
