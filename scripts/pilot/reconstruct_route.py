"""Bounded, offline COLMAP -> Brush reconstruction of a completed browser clip.

Camera paths remain in arbitrary SfM units. No Android input, network, automatic
metric scale, collision map or motor-policy qualification is granted here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from motor_worker.browser_teach import browser_units, prepare_browser, validate_browser
from scripts.pilot.atomic_json import write_json
from scripts.pilot.learned_route_features import available as learned_features_available
from scripts.pilot.learned_route_features import extract_and_match
from scripts.pilot.reconstruction_quality import (
    TRAINING_STEPS,
    export_interval,
    pinhole_condition,
    reference_quality,
    sparse_condition,
)
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.route_loop_completion import complete_partial

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / '.local-pilot/reconstruction-tools'
BRUSH_SHA = 'b68e3e9cf052d51bf3ee30776fa5a364de7f2ba13b58443128ff797bb7bcfcd6'
_TASK_RESOURCES = None
_TASK_RESOURCE_JOB = None


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def _checkpoint_snapshot(job, snapshot, *, learned=False):
    from scripts.pilot.route_reconstruction_resources import profile,findings as route_findings
    control=json.loads((job/'control.json').read_bytes()) if (job/'control.json').is_file() else {}
    budget=profile(job,route_only=control.get('route_only') is True and not learned)
    findings = route_findings(snapshot,budget,evaluate_fn=evaluate)
    if findings:
        if job.is_dir():
            refusal=dict(snapshot=snapshot, findings=findings)
            if budget is not None:refusal['profile']=budget
            write_json(job / 'resource-refusal.json', refusal)
        raise RuntimeError('resource_guard')


def checkpoint(job, *, learned=False):
    if (job / 'CANCEL').exists():
        raise RuntimeError('cancelled')
    if _TASK_RESOURCES is not None and Path(job).resolve() != _TASK_RESOURCE_JOB:
        raise RuntimeError('route_resource_task_mismatch')
    snapshot = _TASK_RESOURCES.sample() if _TASK_RESOURCES is not None else collect(ROOT)
    _checkpoint_snapshot(job, snapshot, learned=learned)


def make_observation_checkpoint(job, *, learned=False):
    """Fresh RAM/disk; task-owned route volume proof or legacy 3s refresh."""
    monitor = _TASK_RESOURCES
    if monitor is not None:
        if Path(job).resolve() != _TASK_RESOURCE_JOB:
            raise RuntimeError('route_resource_task_mismatch')
        def task_check():
            if (job/'CANCEL').exists():
                raise RuntimeError('cancelled')
            _checkpoint_snapshot(job, monitor.sample(), learned=learned)
        return task_check
    from scripts.pilot.resource_guard import windows_memory
    snapshot = None
    refreshed = None
    def check():
        nonlocal snapshot, refreshed
        if (job / 'CANCEL').exists():
            raise RuntimeError('cancelled')
        now = time.monotonic()
        if snapshot is None or refreshed is None or now - refreshed >= 3:
            try:
                current = collect(ROOT)
            except (OSError, ValueError):
                current = {'system': platform.system()}
            _checkpoint_snapshot(job, current, learned=learned)
            snapshot = current
            refreshed = now
            return
        current = dict(snapshot)
        # Never inherit memory/disk counters when a fresh measurement fails.
        for key in ('freeDiskBytes', 'availableRamBytes', 'totalRamBytes',
                    'committedBytes', 'commitLimitBytes'):
            current.pop(key, None)
        try:
            current['freeDiskBytes'] = shutil.disk_usage(ROOT).free
            if current.get('system') == 'Windows':
                current.update(windows_memory())
            elif current.get('system') == 'Linux':
                values = {}
                for line in Path('/proc/meminfo').read_text().splitlines():
                    key, value = line.split(':', 1)
                    if key in {'MemTotal', 'MemAvailable'}:
                        values[key] = int(value.split()[0]) * 1024
                current.update(totalRamBytes=values.get('MemTotal'),
                               availableRamBytes=values.get('MemAvailable'))
        except (OSError, ValueError, IndexError, TypeError):
            pass
        _checkpoint_snapshot(job, current, learned=learned)
    return check


def state(job, phase, **details):
    write_json(job / 'state.json', dict(phase=phase, updated_at=time.time(), **details))


def masked_inputs(prepared, mode, *, manifest=None):
    """Keep original RGB; a separate documented exclusion mask precedes SfM.

    This fixed game preset excludes HUD and the usual third-person avatar. It
    does not detect arbitrary moving players/cars and is never a collision mask.
    """
    from PIL import Image, ImageDraw
    from scripts.pilot.route_masks import capture_exclusions

    rectangles = capture_exclusions(mode, manifest or {})
    if not rectangles:
        return None
    folder = prepared / 'masks'
    folder.mkdir()
    for path in (prepared / 'images').glob('*.png'):
        with Image.open(path) as rgb:
            width, height = rgb.size
        mask = Image.new('L', (width, height), 255)
        draw = ImageDraw.Draw(mask)
        for a,b,c,d in rectangles:
            draw.rectangle((int(width*a), int(height*b), int(width*c), int(height*d)), fill=0)
        mask.save(folder / (path.name + '.png'))  # COLMAP image.png.png convention
    return folder


def model_geometry(rec, prepared):
    """Actual recovered COLMAP poses, ordered by original frame provenance."""
    import numpy as np

    provenance = json.loads((prepared / 'reconstruction-input.json').read_text('utf-8'))
    order = {Path(row['image']).name: row for row in provenance['images']}
    cameras = []
    for image_id in rec.reg_image_ids():
        image = rec.images[image_id]
        pose = image.cam_from_world().inverse().matrix()
        if not np.isfinite(pose).all():
            raise RuntimeError('nonfinite_camera_pose')
        camera = rec.cameras[image.camera_id]
        calibration = camera.calibration_matrix()
        cameras.append(dict(image=image.name, center=pose[:, 3].tolist(),
                            camera_to_world=pose.tolist(),
                            intrinsics=dict(width=camera.width, height=camera.height,
                                            fx=float(calibration[0, 0]), fy=float(calibration[1, 1]),
                                            cx=float(calibration[0, 2]), cy=float(calibration[1, 2])),
                            ticks_90k=order[image.name]['relative_ticks_90k']))
    cameras.sort(key=lambda camera: camera['ticks_90k'])
    points = []
    # Bound browser payload; the full binary sparse map is retained separately.
    for point in list(rec.points3D.values())[::max(1, rec.num_points3D() // 50000)]:
        if np.isfinite(point.xyz).all() and point.error <= 4:
            points.append([*point.xyz.tolist(), *point.color.tolist()])
    length = sum(math.dist(a['center'], b['center']) for a, b in zip(cameras, cameras[1:]))
    return dict(schema='sphere-recovered-scene-v1', cameras=cameras, points=points,
                camera_path_units=length, metric_scale=None, camera_body_transform=None,
                collision_map=False, execution_qualified=False,
                source_manifest_sha256=provenance['source_manifest_sha256'])


def model_assessment(rec, prepared, selected, source_start, source_end, *, check=None):
    """Assess a measured component before allowing its camera count to rank it."""
    from scripts.pilot.route_geometry_selection import evaluate_candidate
    from scripts.pilot.route_observation_support import compact_observation_support, observation_support

    geometry = model_geometry(rec, prepared)
    try:
        condition = sparse_condition([camera['center'] for camera in geometry['cameras']],
                                     [point.xyz for point in rec.points3D.values()])
    except ValueError:
        condition = dict(passed=False, reason='sparse_geometry_invalid')
    intrinsic = geometry['cameras'][0]['intrinsics'] if geometry['cameras'] else {}
    try:
        calibration = pinhole_condition(*(intrinsic[key] for key in ('width','height','fx','fy')))
    except (ValueError,KeyError):
        calibration = dict(passed=False, physical_calibration_verified=False)
    report = evaluate_candidate(geometry, selected=selected, points=rec.num_points3D(),
        reprojection_px=rec.compute_mean_reprojection_error(), conditioning=condition,
        intrinsics_condition=calibration, source_start=source_start, source_end=source_end)
    report.update(conditioning=condition,intrinsics_condition=calibration,
                  observation_support=compact_observation_support(observation_support(rec, geometry['cameras'], check=check)))
    return geometry, report


def reconstruct(job, mask, steps, *, route_only=False):
    """Keep a volume proof inside one CPU route task, never across jobs."""
    global _TASK_RESOURCES, _TASK_RESOURCE_JOB
    if _TASK_RESOURCES is not None:
        raise RuntimeError('route_resource_task_already_active')
    if not route_only:
        return _reconstruct_with_telemetry(job,mask,steps,route_only=False)
    from scripts.pilot.route_resource_monitor import TaskResourceMonitor
    with TaskResourceMonitor(ROOT) as monitor:
        _TASK_RESOURCES=monitor
        _TASK_RESOURCE_JOB=Path(job).resolve()
        try:
            return _reconstruct_with_telemetry(job,mask,steps,route_only=True)
        finally:
            _TASK_RESOURCES=None
            _TASK_RESOURCE_JOB=None


def _reconstruct_with_telemetry(job, mask, steps, *, route_only=False):
    """Own the optional telemetry child through completion/cancellation."""
    from scripts.pilot.route_hud_workspace import start as start_hud
    checkpoint(job)
    capture=validate_browser(job/'input')
    # The image index is useful even if the independent global SfM later fails.
    # Run it serially in the small CPU runtime, without granting route input.
    from scripts.pilot.image_route_workspace import run_optional as prepare_image_review
    state(job, 'image_route_indexing')
    prepare_image_review(job, mask, check=make_observation_checkpoint(job))
    checkpoint(job)  # A service-restart cancellation must not continue to SfM.
    began=time.monotonic()
    try:
        hud_process=start_hud(job,capture)
    except Exception:
        # Telemetry is optional. An existing or unavailable sidecar must not
        # prevent the independent route reconstruction from proceeding.
        hud_process=None
    try:
        return _reconstruct(job,mask,steps,route_only=route_only)
    finally:
        if hud_process is not None:
            failed = sys.exc_info()[0] is not None
            if failed:
                try:
                    (job/'telemetry'/'CANCEL').touch(exist_ok=True)
                except OSError:
                    pass
            while hud_process.poll() is None:
                if failed or (job/'CANCEL').exists() or time.monotonic()-began>100:
                    # Let the worker's five-second OCR timeout and cooperative
                    # checkpoint release its own child before forcing it down.
                    try:
                        hud_process.wait(timeout=6)
                    except subprocess.TimeoutExpired:
                        try:
                            hud_process.terminate()
                            hud_process.wait(timeout=6)
                        except subprocess.TimeoutExpired:
                            try:
                                hud_process.kill()
                                hud_process.wait(timeout=6)
                            except (OSError, subprocess.TimeoutExpired):
                                pass
                        except OSError:
                            pass
                    except OSError:
                        pass
                    break
                try:
                    hud_process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    pass
            from scripts.pilot.route_hud_workspace import settle_child
            if hud_process.poll() is not None:
                settle_child(job,cancelled=failed or (job/'CANCEL').exists())


def _reconstruct(job, mask, steps, *, route_only=False):
    checkpoint(job)
    sys.path.insert(0, str(TOOLS / 'pycolmap-4.2.1'))
    state(job, 'verifying')
    capture = validate_browser(job / 'input')
    vehicle=(capture.manifest.get('config',{}).get('profile') or {}).get('mode')=='vehicle_buttons'
    duration = capture.frames[-1]['relative_ticks_90k'] / 90000
    if duration < 5:
        raise RuntimeError('clip_too_short_minimum_5_seconds')
    if (vehicle and capture.manifest['config'].get('hud_hidden_declared') is False
            and capture.manifest['config']['profile'].get('hudProfile') == 'black_russia_scooter_v1'):
        # Observe the original speed display before SfM; never infer pedal
        # presses or convert this HUD unit into a metric world calibration.
        from scripts.pilot.route_hud_profile import load_speed_reference, prepare_speed_reference
        state(job, 'vehicle_speed_reference')
        if (job/'vehicle-speed-reference').exists():
            load_speed_reference(job)  # Reuse only a completely source-bound artifact.
        else:
            # The per-frame callback uses fresh native memory counters while
            # throttling the expensive Windows volume-health subprocess.
            prepare_speed_reference(job, checkpoint=make_observation_checkpoint(job))
        checkpoint(job)
    state(job, 'extracting', source_frames=len(capture.frames))
    prepared = job / 'prepared'
    selected_indices=None
    if route_only:
        from scripts.pilot.route_motion_sampling import sample_video
        state(job,'motion_sampling',source_frames=len(capture.frames))
        selected_indices,motion_sampling=sample_video(capture,mask,lambda:checkpoint(job),
            lambda done,total:state(job,'motion_sampling',completed_items=done,total_items=total))
        write_json(job/'motion-sampling.json',motion_sampling)
        state(job,'extracting',source_frames=len(capture.frames),selected_views=len(selected_indices))
    prepare_browser(job / 'input', prepared, interval=max(.25 if route_only else .5, duration / 230),
                    max_images=240, max_bytes=2**31, selected_indices=selected_indices)
    images = list((prepared / 'images').glob('*.png'))
    if len(images) < 10:
        raise RuntimeError('insufficient_selected_views')
    masks = masked_inputs(prepared, mask, manifest=capture.manifest)
    checkpoint(job)
    import pycolmap as p

    if p.__version__ != '4.2.1':
        raise RuntimeError('pycolmap_version_mismatch')
    token = p.CancellationToken()
    finished = threading.Event()
    aborted = []

    def watchdog():
        deadline = time.monotonic() + 900
        while not finished.wait(3):
            try:
                checkpoint(job)
                if time.monotonic() > deadline:
                    raise RuntimeError('sfm_timeout')
            except RuntimeError as error:
                aborted.append(str(error))
                token.cancel()
                return

    guard = threading.Thread(target=watchdog, daemon=True)
    guard.start()
    try:
        # Screen captures have square pixels and no physical lens distortion.
        # A shared focal parameter avoids independent fx/fy collapsing along
        # a mostly forward route; no metric calibration is claimed.
        reader = p.ImageReaderOptions(camera_model='SIMPLE_PINHOLE')
        if masks:
            reader.mask_path = str(masks)
        database = prepared / 'database.db'
        learned = learned_features_available(ROOT) and not route_only
        state(job, 'features', selected_views=len(images), masks=mask,
              method='source_video_corner_tracks' if route_only else 'opencv-rootsift-lightglue' if learned else 'classical-sift')
        if route_only:
            # A route is a time-ordered video, not an unordered photo collection.
            # Preserve each observed corner's identity through intervening frames
            # instead of choosing a visually similar window in a later image.
            from scripts.pilot.route_video_tracks import build_video_track_database
            from scripts.pilot.learned_route_features import verify_pairs
            skeleton=prepared/'camera-index.db'
            p.Database.open(skeleton).close()
            p.import_images(skeleton,prepared/'images',camera_mode=p.CameraMode.SINGLE,options=reader)
            tracks=build_video_track_database(job,prepared,skeleton,database,lambda:checkpoint(job),
                wide_tracking=vehicle,
                progress=lambda done,total:state(job,'features',method='source_video_corner_tracks',selected_views=len(images),completed_items=done,total_items=total))
            pair_file=prepared/'video-track-pairs.txt'
            pair_file.write_text(''.join(row['first']+' '+row['second']+'\n' for row in tracks['pairs']),encoding='ascii')
            state(job,'matching',selected_views=len(images),method='video_tracks_geometric_verification')
            verify_pairs(database,pair_file,token,filter_stationary=True)
            write_json(prepared/'features.json',dict(method='source_video_corner_tracks',sourceFrames=tracks['decodedFrames'],
                observations=tracks['observations'],pairs=len(tracks['pairs']),seconds=tracks['seconds'],
                neuralModelLoaded=False,geometric_verification_complete=True))
        elif learned:
            extract_and_match(ROOT, prepared, database, reader, token, lambda: checkpoint(job),
                progress=lambda phase,done,total:state(job,phase,selected_views=len(images),completed_items=done,total_items=total))
        else:
            features = p.FeatureExtractionOptions(num_threads=4, use_gpu=False, max_image_size=1920)
            features.sift.max_num_features = 8192
            p.extract_features(database, prepared / 'images', camera_mode=p.CameraMode.SINGLE,
                               reader_options=reader, extraction_options=features,
                               device=p.Device.cpu, cancellation_token=token)
            checkpoint(job)
            state(job, 'matching', selected_views=len(images))
            pairing = p.SequentialPairingOptions(overlap=12, loop_detection=False, num_threads=4)
            matching = p.FeatureMatchingOptions(num_threads=4, use_gpu=False)
            p.match_sequential(database, matching_options=matching, pairing_options=pairing,
                               device=p.Device.cpu, cancellation_token=token)
        checkpoint(job)
        state(job, 'cameras', selected_views=len(images))
        sparse = prepared / 'models'
        sparse.mkdir()
        options = p.IncrementalPipelineOptions(num_threads=4, random_seed=17,
                                               max_runtime_seconds=600, max_num_models=4,
                                               ignore_watermarks=True,
                                               structure_less_registration_fallback=False,
                                               ba_refine_sensor_from_rig=False)
        models = p.incremental_mapping(database, prepared / 'images', sparse,
                                       options=options, cancellation_token=token)
    finally:
        finished.set()
        guard.join(5)
    if aborted:
        raise RuntimeError(aborted[0])
    checkpoint(job)
    from scripts.pilot.route_geometry_selection import candidate_rank
    source_start=capture.frames[0]['relative_ticks_90k']/90000
    source_end=capture.frames[-1]['relative_ticks_90k']/90000
    observation_check=make_observation_checkpoint(job)
    candidates=[]
    for identity, model in models.items():
        geometry, assessment=model_assessment(model,prepared,len(images),source_start,source_end,check=observation_check)
        candidates.append((model,geometry,dict(assessment,model=identity)))
    write_json(job/'geometry-candidates.json',dict(schema='sphere-geometry-candidates-v1',
        models=[report for _,_,report in candidates],source_start_seconds=source_start,
        source_end_seconds=source_end,execution_qualified=False))
    winner=max(candidates,key=lambda row:candidate_rank(row[2])) if candidates else None
    rec=winner[0] if winner else None
    cached_assessment=(winner[1],winner[2]) if winner else None
    recovery=None
    component_merge=None
    if rec is not None:
        first_geometry,first_assessment=cached_assessment
        # Preserve inspectable evidence even if a later optional model load is
        # refused. This unsealed first pass never authorizes navigation.
        write_json(job/'geometry.json',first_geometry)
        write_json(job/'quality.json',dict(registered=rec.num_reg_images(),selected=len(images),
            coverage=rec.num_reg_images()/len(images),points=rec.num_points3D(),
            mean_reprojection_px=rec.compute_mean_reprojection_error(),components=len(models),
            conditioning=first_assessment['conditioning'],intrinsics_condition=first_assessment['intrinsics_condition'],
            selection=first_assessment,first_pass_only=True))
    if route_only and len(models)>1 and (rec is None or not cached_assessment[1]['route_admissible']):
        # Native mapping may return overlapping reconstructions of one route.
        # Check their actual camera/observation identities before loading an
        # additional learned matcher or dropping an already recovered prefix.
        from scripts.pilot.route_component_merge import merge_components
        rec,component_merge=merge_components(job,prepared,models,rec,len(images),source_start,source_end,
            lambda:checkpoint(job),
            lambda _phase,done,total:state(job,'cameras',method='compatible_component_merge',selected_views=len(images),completed_items=done,total_items=total),
            assessment_check=observation_check)
        if component_merge.get('accepted'):
            cached_assessment=model_assessment(rec,prepared,len(images),source_start,source_end,check=observation_check)
    if route_only and (rec is None or not cached_assessment[1]['route_admissible']):
        from scripts.pilot.route_learned_recovery import recover_with_learned
        rec,recovery=recover_with_learned(job,prepared,rec,len(images),source_start,source_end,reader,
            lambda:checkpoint(job,learned=True),lambda phase,done=0,total=0:state(job,phase,selected_views=len(images),completed_items=done,total_items=total),
            assessment_check=make_observation_checkpoint(job,learned=True))
        cached_assessment=None
    if rec is None:
        raise RuntimeError('no_connected_cameras_need_translation_and_overlap')
    if learned and .7 <= rec.num_reg_images() / len(images) < 1 and rec.num_points3D() >= 300:
        initial_condition = sparse_condition(
            [image.cam_from_world().inverse().translation for image in rec.images.values() if image.has_pose],
            [point.xyz for point in rec.points3D.values()])
        from scripts.pilot.route_motion_audit import audit
        initial_motion=audit(model_geometry(rec,prepared))
        if initial_condition['passed'] and not initial_motion['rapid_reversals'] and not initial_motion['speed_outliers']:
            state(job, 'matching', selected_views=len(images), method='anchored-loop-completion')
            rec = complete_partial(ROOT, prepared, database, rec, lambda: checkpoint(job))
            cached_assessment=None
    if cached_assessment is None:
        cached_assessment=model_assessment(rec,prepared,len(images),source_start,source_end,check=observation_check)
    geometry,initial_assessment = cached_assessment
    temporal_repair = None
    from scripts.pilot.route_temporal_repair import needs_repair, repair_temporally
    if learned and needs_repair(geometry,len(images),conditioning=initial_assessment['conditioning']):
        # Keep the baseline for inspection even if bounded repair is inconclusive.
        # Resource/cancellation fences still terminate the whole task.
        try:
            rec,temporal_repair=repair_temporally(job,prepared,database,rec,len(images),lambda:checkpoint(job),
                lambda phase,done=0,total=0:state(job,phase,selected_views=len(images),completed_items=done,total_items=total))
        except RuntimeError as failure:
            if str(failure) in {'resource_guard','cancelled'}:
                raise
            temporal_repair=dict(accepted=False,reason='temporal_repair_inconclusive',errorType=type(failure).__name__)
        cached_assessment=model_assessment(rec,prepared,len(images),source_start,source_end,check=observation_check)
        geometry=cached_assessment[0]
    endpoint_resection=None
    if route_only and rec.num_reg_images()<len(images):
        # All matching against the original database must finish first. New
        # endpoint observations have a separate, recorded ENDPOINT_LK namespace.
        from scripts.pilot.route_endpoint_resection import repair_endpoints
        rec,endpoint_resection=repair_endpoints(job,prepared,rec,len(images),source_start,source_end,
            lambda:checkpoint(job),
            lambda _phase,done,total:state(job,'cameras',method='endpoint_resection',selected_views=len(images),completed_items=done,total_items=total),
            assessment_check=observation_check)
        if endpoint_resection.get('accepted'):
            cached_assessment=model_assessment(rec,prepared,len(images),source_start,source_end,check=observation_check)
            geometry=cached_assessment[0]
    write_json(job / 'geometry.json', geometry)
    coverage = rec.num_reg_images() / len(images)
    error = rec.compute_mean_reprojection_error()
    quality = dict(registered=rec.num_reg_images(), selected=len(images), coverage=coverage,
                   points=rec.num_points3D(), mean_reprojection_px=error, components=len(models))
    if component_merge is not None:
        quality['component_merge']={key:component_merge.get(key) for key in ('schema','accepted','reason','chosen','seconds','source_modified')}
        quality['component_merge']['attempts']=len(component_merge.get('attempts',[]))
        if component_merge.get('accepted'):
            quality['source_components']=len(models)
            quality['components']=1
    if temporal_repair is not None:
        quality['temporal_repair']=temporal_repair
    if endpoint_resection is not None:
        quality['endpoint_resection']={key:endpoint_resection.get(key) for key in
            ('schema','accepted','reason','namespace','further_original_db_matching','poses_interpolated','execution_qualified')}
        quality['endpoint_resection']['added_views']=sum(bool(frame.get('accepted')) for frame in endpoint_resection.get('frames',[])) if endpoint_resection.get('accepted') else 0
    if recovery is not None:
        # Full rejected-candidate audits remain in learned-recovery/result.json;
        # the sealed quality receipt has a fixed 64 KiB budget.
        quality['learned_recovery']={key:recovery.get(key) for key in
            ('schema','accepted','reason','error_code','seconds','device','max_features','chosen_model')}
        quality['learned_recovery']['candidate_count']=len(recovery.get('models',[]))
        if recovery.get('accepted'):
            quality['components']=len(recovery['models'])
    quality['selection']=cached_assessment[1]
    quality['conditioning'] = quality['selection']['conditioning']
    quality['intrinsics_condition'] = quality['selection']['intrinsics_condition']
    write_json(job / 'quality.json', quality)
    if rec.num_reg_images() < 10 or coverage < .7 or rec.num_points3D() < 300 or not math.isfinite(error) or error > 3:
        raise RuntimeError('camera_quality_gate_failed')
    if not quality['conditioning']['passed']:
        raise RuntimeError('camera_geometry_degenerate')
    if not quality['intrinsics_condition']['passed']:
        raise RuntimeError('camera_intrinsics_degenerate')
    if route_only and not quality['selection']['route_admissible']:
        raise RuntimeError('camera_quality_gate_failed')
    # A largest component is not a claim that discarded views are connected.
    target = prepared / 'sparse' / '0'
    target.mkdir(parents=True)
    rec.write(target)
    rec.export_PLY(prepared / 'sparse' / 'points.ply')
    finish_sparse(job, prepared, geometry, quality, mask, masks, steps, route_only=route_only)


def finish_sparse(job, prepared, geometry, quality, mask, masks, steps, *, route_only):
    """Seal camera evidence, optionally stop before expensive visual training."""
    from scripts.pilot.sparse_scene_receipt import create_sparse_receipt
    create_sparse_receipt(job)
    if route_only:
        state(job, 'sparse_complete')
        return
    # Brush uses masks/image.png; keep COLMAP's independent mask naming intact.
    if masks:
        for path in list(masks.glob('*.png.png')):
            (masks / path.name[:-4]).write_bytes(path.read_bytes())
    train_dense(job, prepared, geometry, quality, mask, steps)


def validate_splats(path):
    """Validate the complete binary Brush PLY, including every float, in chunks."""
    import numpy as np

    size = path.stat().st_size
    if not 1024 < size <= 256 * 1024**2:
        raise RuntimeError('dense_export_missing_or_exceeds_256mib')
    with path.open('rb') as file:
        lines, header_bytes = [], 0
        while True:
            line = file.readline(256)
            header_bytes += len(line)
            if not line or len(line) >= 256 or header_bytes > 8192:
                raise RuntimeError('dense_export_invalid_header')
            text = line.decode('ascii').strip()
            lines.append(text)
            if text == 'end_header':
                break
        vertices = [line for line in lines if line.startswith('element vertex ')]
        if lines[:2] != ['ply', 'format binary_little_endian 1.0'] or len(vertices) != 1:
            raise RuntimeError('dense_export_invalid_header')
        count = int(vertices[0].split()[-1])
        properties = [line.split() for line in lines if line.startswith('property ')]
        names = [row[-1] for row in properties]
        required = {'x', 'y', 'z', 'opacity', 'scale_0', 'scale_1', 'scale_2',
                    'rot_0', 'rot_1', 'rot_2', 'rot_3', 'f_dc_0', 'f_dc_1', 'f_dc_2'}
        if (not 1 <= count <= 750000 or not required.issubset(names) or len(set(names)) != len(names)
                or any(len(row) != 3 or row[1] != 'float' for row in properties)
                or len(properties) > 64 or header_bytes + count * len(properties) * 4 != size):
            raise RuntimeError('dense_export_invalid_layout')
        remaining = count
        while remaining:
            take = min(65536, remaining)
            raw = file.read(take * len(properties) * 4)
            if len(raw) != take * len(properties) * 4 or not np.isfinite(np.frombuffer(raw, dtype='<f4')).all():
                raise RuntimeError('dense_export_nonfinite_or_truncated')
            remaining -= take
    return dict(vertices=count, bytes=size, sha256=digest(path))


def preserve_checkpoint(job, steps, export=None):
    quality = json.loads((job / 'quality.json').read_text('utf-8')) if (job / 'quality.json').exists() else {}
    minimum = max(300, int(quality.get('points', 0) * .25))
    candidates = []
    for path in (export or job / 'dense').glob('scene_*.ply'):
        match = re.fullmatch(r'scene_(\d+)\.ply', path.name)
        if match and 0 < int(match[1]) < steps:
            candidates.append((int(match[1]), path))
    for iteration, path in sorted(candidates, reverse=True):
        try:
            metadata = validate_splats(path)
            if metadata['vertices'] < minimum:
                continue
        except (ValueError, RuntimeError, OSError):
            continue
        write_json(job / 'checkpoint.json', dict(file=path.relative_to(job).as_posix(), steps=iteration,
                   target_steps=steps, partial=True, **metadata))
        return


def brush_dataset(job, prepared, names, name='brush-dataset'):
    """A single isolated COLMAP model: no alternative cameras or init points."""
    folder = job / name
    folder.mkdir()
    (folder / 'images').mkdir()
    (folder / 'sparse/0').mkdir(parents=True)
    (folder / 'masks').mkdir()
    sources = [(path, folder / 'sparse/0' / path.name) for path in (prepared / 'sparse/0').iterdir() if path.is_file()]
    for name in names:
        if not re.fullmatch(r'[0-9]{8}\.png', name):
            raise RuntimeError('brush_dataset_image_name')
        sources.append((prepared / 'images' / name, folder / 'images' / name))
        mask = prepared / 'masks' / name
        if mask.is_file():
            sources.append((mask, folder / 'masks' / name))
    binding = []
    for source, destination in sources:
        if source.is_symlink() or not source.is_file():
            raise RuntimeError('brush_dataset_regular_source_required')
        try:
            os.link(source, destination)
        except OSError:
            shutil.copyfile(source, destination)
        binding.append(dict(file=destination.relative_to(folder).as_posix(), sha256=digest(destination)))
    write_json(folder / 'binding.json', dict(schema='sphere-single-colmap-dataset-v1', files=binding))
    return folder


def train_dense(job, prepared, geometry, quality, mask, steps, attempt=0):
    interval = export_interval(steps)
    checkpoint(job)
    archive = TOOLS / 'brush-app-v0.3.0-windows.zip'
    if digest(archive) != BRUSH_SHA:
        raise RuntimeError('brush_archive_mismatch')
    binary = TOOLS / 'brush-v0.3.0/brush_app.exe'
    with zipfile.ZipFile(archive) as package:
        executables = [name for name in package.namelist() if name.endswith('/brush_app.exe') or name == 'brush_app.exe']
        if len(executables) != 1 or hashlib.sha256(package.read(executables[0])).hexdigest() != digest(binary):
            raise RuntimeError('brush_binary_mismatch')
    engine = 'brush-0.3.0-official'
    patched = TOOLS / 'brush-system-timing/receipt.json'
    if patched.exists():
        receipt = json.loads(patched.read_text('utf-8'))
        candidate = patched.parent / 'brush_headless.exe'
        if (receipt.get('engine') != 'brush-0.3.0-system-timing-1'
                or receipt.get('cubecl_revision') != '43580a8c294f3a8140921c26f6378a12aef82881'
                or receipt.get('brush_git_tree') != '3edecbb2fe79d3e2c87eeab85b15e0b1dd10d486'
                or receipt.get('headless_entry_sha256') != digest(ROOT / 'scripts/pilot/brush_headless.rs')
                or receipt.get('binary_sha256') != digest(candidate)):
            raise RuntimeError('patched_brush_receipt_mismatch')
        binary, engine = candidate, receipt['engine']
    elif os.name == 'nt':
        raise RuntimeError('brush_system_timing_build_required')
    dataset = brush_dataset(job, prepared, [camera['image'] for camera in geometry['cameras']],
                            name=f'brush-dataset-attempt-{attempt}' if attempt else 'brush-dataset')
    export = job / (f'dense-attempt-{attempt}' if attempt else 'dense')
    export.mkdir()
    state(job, 'training', quality=quality, total_steps=steps)
    command = [str(binary), str(dataset), '--total-steps', str(steps), '--max-splats', '750000',
               '--max-resolution', '1920', '--sh-degree', '2', '--seed', '17',
               '--export-every', str(interval), '--export-path', str(export), '--export-name', 'scene_{iter}.ply']
    log_name = f'brush-retry-{attempt}.log' if attempt else 'brush.log'
    environment = dict(os.environ, CUBECL_AUTOTUNE_LEVEL='balanced', RUST_BACKTRACE='1')
    binding_checked = False
    with (job / log_name).open('xb') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env=environment,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 1200
        try:
            while process.poll() is None:
                checkpoint(job)
                if not binding_checked:
                    text = (job / log_name).read_text('utf-8', errors='replace')
                    loaded = re.findall(r'Loading colmap dataset with (\d+) images', text)
                    initial = re.findall(r'Starting from colmap points (\d+)', text)
                    if loaded and initial:
                        if list(map(int, loaded)) != [quality['registered']] or list(map(int, initial)) != [quality['points']]:
                            raise RuntimeError('brush_dataset_binding_mismatch')
                        binding_checked = True
                if (time.monotonic() > deadline or log.tell() > 20 * 1024**2
                        or sum(path.stat().st_size for path in export.glob('*.ply')) > 2**31):
                    raise RuntimeError('brush_time_or_log_budget')
                time.sleep(2)
            if process.returncode:
                preserve_checkpoint(job, steps, export)
                text = (job / log_name).read_text('utf-8', errors='replace')
                reason = ('brush_timing_overflow' if 'cannot convert float seconds to Duration' in text
                          else 'brush_failed_see_local_log')
                raise RuntimeError(reason)
        except Exception:
            # A resource/cancellation refusal is also a failed training run.
            # Stop the writer before inspecting its last complete export.
            if process.poll() is None:
                process.kill()
                process.wait(10)
            preserve_checkpoint(job, steps, export)
            raise
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(10)
    checkpoint(job)
    ply = export / f'scene_{steps}.ply'
    splats = validate_splats(ply)
    if not binding_checked or splats['vertices'] < max(300, int(quality['points'] * .25)):
        raise RuntimeError('dense_geometry_collapsed_or_unbound')
    final = export / 'scene.ply'
    with final.open('xb') as output, ply.open('rb') as source:
        while chunk := source.read(1024**2):
            output.write(chunk)
    state(job, 'evaluating', quality=quality)
    appearance = evaluate_dense(job, dataset, final, attempt=attempt)
    result = dict(schema='sphere-dense-reconstruction-v1', quality=quality,
                  source_manifest_sha256=geometry['source_manifest_sha256'],
                  ply_sha256=splats['sha256'], ply_bytes=splats['bytes'], vertices=splats['vertices'],
                  scene_file=final.relative_to(job).as_posix(),
                  geometry_sha256=digest(job / 'geometry.json'),
                  metric_scale=None, masks=mask, dynamic_objects_removed=False,
                  collision_map=False, execution_qualified=False,
                  tools=dict(pycolmap='4.2.1', brush='0.3.0'), training_steps=steps,
                  autotune='balanced', engine=engine, periodic_export_steps=interval,
                  appearance=appearance['summary'])
    features_path = prepared / 'features.json'
    if features_path.is_file():
        result['feature_matching'] = json.loads(features_path.read_text('utf-8'))
    write_json(job / 'result.json', result)
    (job / 'COMPLETE').write_text(digest(job / 'result.json') + '\n', encoding='ascii')
    accepted_phase = 'partial_scene' if quality['registered'] < quality['selected'] else 'complete'
    state(job, accepted_phase if appearance['summary']['state'] == 'passed' else 'quality_rejected',
          result=result, **({} if appearance['summary']['state'] == 'passed'
                           else dict(error='dense_visual_quality_gate_failed')))


def appearance_receipt(job, ply, folder):
    """Bind reference comparisons to the exact geometry and exported candidate."""
    metrics = json.loads((folder / 'metrics.json').read_text('utf-8'))
    summary = reference_quality(metrics)
    views = []
    for row in metrics['views']:
        name = row['image'].replace('\\', '/').split('/')[-1]
        if not re.fullmatch(r'[0-9]{8}\.png', name):
            raise RuntimeError('reference_image_name_invalid')
        files = {}
        for kind in ('source', 'render'):
            path = folder / f'{name[:-4]}-{kind}.png'
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4 * 1024**2:
                raise RuntimeError('reference_image_invalid')
            files[kind] = dict(file=path.relative_to(job).as_posix(), sha256=digest(path), bytes=path.stat().st_size)
        views.append(dict(image=name, psnr=row['psnr'], ssim=row['ssim'], **files))
    if len({view['image'] for view in views}) != len(views):
        raise RuntimeError('reference_image_duplicate')
    receipt = dict(schema='sphere-scene-appearance-v1', summary=summary, views=views,
                   ply_sha256=digest(ply), geometry_sha256=digest(job / 'geometry.json'))
    write_json(job / 'appearance.json', receipt)
    return receipt


def evaluate_dense(job, dataset, ply, attempt=0):
    package = TOOLS / 'brush-reference-evaluator'
    receipt = json.loads((package / 'receipt.json').read_text('utf-8'))
    binary = package / 'brush_evaluate.exe'
    if (receipt.get('entry_sha256') != digest(ROOT / 'scripts/pilot/brush_evaluate.rs')
            or receipt.get('binary_sha256') != digest(binary)
            or receipt.get('brush_tree') != '3edecbb2fe79d3e2c87eeab85b15e0b1dd10d486'):
        raise RuntimeError('reference_evaluator_receipt_mismatch')
    folder = job / (f'reference-evaluation-attempt-{attempt}' if attempt else 'reference-evaluation')
    with (job / (folder.name + '.log')).open('xb') as log:
        process = subprocess.Popen([str(binary), str(dataset), str(ply), str(folder)],
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 180
        try:
            while process.poll() is None:
                checkpoint(job)
                if time.monotonic() > deadline or log.tell() > 20 * 1024**2:
                    raise RuntimeError('reference_evaluation_budget')
                time.sleep(2)
            if process.returncode:
                raise RuntimeError('reference_evaluation_failed')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(10)
    return appearance_receipt(job, ply, folder)


def retry_dense(job, attempt):
    """One explicit maintainer retry; never repeats capture, upload, SfM or input."""
    checkpoint(job)
    previous = json.loads((job / 'state.json').read_text('utf-8'))
    if previous.get('phase') != 'failed' or previous.get('error') not in {'brush_failed_see_local_log', 'brush_timing_overflow', 'brush_system_timing_build_required'}:
        raise RuntimeError('dense_retry_requires_confirmed_brush_failure')
    capture = validate_browser(job / 'input')
    for _ in browser_units(capture):
        pass
    prepared = job / 'prepared'
    source = json.loads((prepared / 'reconstruction-input.json').read_text('utf-8'))
    geometry = json.loads((job / 'geometry.json').read_text('utf-8'))
    quality = json.loads((job / 'quality.json').read_text('utf-8'))
    if source['source_manifest_sha256'] != digest(job / 'input/manifest.json') or geometry['source_manifest_sha256'] != source['source_manifest_sha256']:
        raise RuntimeError('dense_retry_source_changed')
    for image in source['images']:
        path = prepared / image['image']
        if not path.resolve().is_relative_to(prepared.resolve()) or digest(path) != image['png_sha256']:
            raise RuntimeError('dense_retry_image_changed')
    sys.path.insert(0, str(TOOLS / 'pycolmap-4.2.1'))
    import numpy as np
    import pycolmap as p

    rec = p.Reconstruction(prepared / 'sparse/0')
    recovered = model_geometry(rec, prepared)
    if (rec.num_points3D() != quality['points'] or rec.num_reg_images() != quality['registered']
            or [c['image'] for c in recovered['cameras']] != [c['image'] for c in geometry['cameras']]
            or not np.allclose([c['camera_to_world'] for c in recovered['cameras']],
                               [c['camera_to_world'] for c in geometry['cameras']], rtol=1e-7, atol=1e-7)):
        raise RuntimeError('dense_retry_camera_map_changed')
    condition = sparse_condition([camera['center'] for camera in recovered['cameras']],
                                 [point.xyz for point in rec.points3D.values()])
    if not condition['passed']:
        raise RuntimeError('camera_geometry_degenerate')
    intrinsic = recovered['cameras'][0]['intrinsics']
    if not pinhole_condition(intrinsic['width'], intrinsic['height'], intrinsic['fx'], intrinsic['fy'])['passed']:
        raise RuntimeError('camera_intrinsics_degenerate')
    control = json.loads((job / 'control.json').read_text('utf-8'))
    with (job / f'DENSE-RETRY-{attempt}.json').open('x', encoding='utf-8') as file:
        json.dump(dict(previous_state=previous, source_manifest_sha256=source['source_manifest_sha256'],
                       retry='dense_only_single_dataset_system_timing', at=time.time()), file)
    train_dense(job, prepared, geometry, quality, control['mask'], control['steps'], attempt=attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--mask', choices=['none', 'avatar', 'game'], default='game')
    parser.add_argument('--steps', type=int, choices=TRAINING_STEPS, default=5000)
    parser.add_argument('--retry-dense', action='store_true')
    parser.add_argument('--route-only', action='store_true')
    parser.add_argument('--retry-attempt', type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    job = args.job.resolve(strict=True)
    os.environ.update(OMP_NUM_THREADS='4', HF_HUB_OFFLINE='1', RUST_LOG='info')
    try:
        if args.retry_dense:
            retry_dense(job, args.retry_attempt)
        else:
            reconstruct(job, args.mask, args.steps, route_only=args.route_only)
    except Exception as error:
        # Keep raw records and partial outputs. Never mark partial training complete.
        state(job, 'cancelled' if str(error) == 'cancelled' else 'failed',
              error=str(error)[:300], error_type=type(error).__name__)
        raise


if __name__ == '__main__':
    main()
