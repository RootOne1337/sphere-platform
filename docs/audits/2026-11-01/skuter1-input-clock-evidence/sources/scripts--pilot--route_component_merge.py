"""Optional bounded native merge of components from one prepared COLMAP database.

Only owned copies are written. A successful CLI exit is not proof of a merge:
COLMAP 4.2.1 also returns zero when alignment fails. Every result must contain
the actual input camera union and pass reciprocal-track, cheirality and existing
route assessment before it can improve the caller's baseline. Arbitrary SfM
units remain arbitrary; no pose interpolation or navigation authority is added.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_geometry_selection import candidate_rank

ROOT = Path(__file__).resolve().parents[2]
COLMAP = ROOT / '.local-pilot/reconstruction-tools/colmap-v4.2.1-cpu/bin/colmap.exe'
COLMAP_SHA256 = 'cca7acf7618703b5766e456f1b27940bd4a63ee904960bba78c8ea92a35121dd'
TOTAL_SECONDS = 120
MERGE_SECONDS = 90
MAX_MODELS = 4
MAX_MERGES = 3
MAX_FILE_BYTES = 512 * 1024**2
MAX_POINTS = 500_000
MAX_OBSERVATIONS = 2_000_000
MAX_LOG_BYTES = 4 * 1024**2
MAX_REPROJECTION_PX = 4.
MIN_INLIER_OBSERVATIONS = .3  # Fixed inside official MergeReconstructions.


def _hash(path, check):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024**2):
            check()
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path, root, maximum=MAX_FILE_BYTES):
    path, root = Path(path), Path(root)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('component_merge_source_scope')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('component_merge_source_symlink')
        if part == root:
            break
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('component_merge_source_file')


def _source(job, prepared, selected, check):
    manifest, index, database = job / 'input/manifest.json', prepared / 'reconstruction-input.json', prepared / 'database.db'
    _regular(manifest, job, 65536)
    _regular(index, job, 1024**2)
    _regular(database, job)
    paths = [manifest, index, database]
    provenance = json.loads(index.read_bytes())
    rows = provenance.get('images')
    if (provenance.get('source_manifest_sha256') != _hash(manifest, check)
            or not isinstance(rows, list) or len(rows) != selected):
        raise ValueError('component_merge_source_binding')
    names = set()
    for row in rows:
        check()
        name = row['image']
        if (not isinstance(name, str) or not re.fullmatch(r'images/[0-9]{8}\.png', name)
                or name in names):
            raise ValueError('component_merge_image_binding')
        names.add(name)
        image = prepared / name
        _regular(image, job, 8 * 1024**2)
        if _hash(image, check) != row.get('png_sha256'):
            raise ValueError('component_merge_image_changed')
        paths.append(image)
    # Snapshot original model files as well as the database and source inputs.
    models = prepared / 'models'
    if models.is_symlink():
        raise ValueError('component_merge_source_symlink')
    if models.is_dir():
        directories = list(models.iterdir())
        if len(directories) > MAX_MODELS:
            raise ValueError('component_merge_model_quota')
        for directory in directories:
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError('component_merge_model_scope')
            files = list(directory.iterdir())
            if len(files) > 8:
                raise ValueError('component_merge_model_file_quota')
            for path in files:
                _regular(path, job)
                paths.append(path)
    for path in (job / 'input').iterdir():
        _regular(path, job)
        if path not in paths:
            paths.append(path)
    if sum(path.stat().st_size for path in paths) > 3 * MAX_FILE_BYTES:
        raise ValueError('component_merge_source_quota')
    hashes = {path.relative_to(job).as_posix(): _hash(path, check) for path in paths}
    return names, paths, hashes


def _namespace(model, database, names, check):
    """Verify full ordered pixel arrays, not merely matching image names/IDs."""
    import numpy as np

    ids = list(model.reg_image_ids())
    if not 3 <= len(ids) <= 240 or len(set(ids)) != len(ids) or len(model.images) > 240:
        raise ValueError('component_merge_image_quota')
    if model.num_points3D() > MAX_POINTS:
        raise ValueError('component_merge_point_quota')
    total = 0
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        for image in model.images.values():
            check()
            row = db.execute('SELECT name,camera_id FROM images WHERE image_id=?', (image.image_id,)).fetchone()
            if (row is None or row[0] != image.name or row[1] != image.camera_id
                    or 'images/' + image.name not in names):
                raise ValueError('component_merge_database_image_namespace')
            camera = model.cameras[image.camera_id]
            dimensions = db.execute('SELECT model,width,height FROM cameras WHERE camera_id=?', (image.camera_id,)).fetchone()
            if dimensions != (int(camera.model), camera.width, camera.height):
                raise ValueError('component_merge_database_camera_namespace')
            feature = db.execute('SELECT rows,cols,data FROM keypoints WHERE image_id=?', (image.image_id,)).fetchone()
            if feature is None or feature[1] not in (2, 4, 6) or not 0 <= feature[0] <= 32768:
                raise ValueError('component_merge_database_keypoints')
            count, cols, blob = feature
            if blob is None or len(blob) != count * cols * 4 or image.num_points2D() != count:
                raise ValueError('component_merge_database_keypoint_namespace')
            total += count
            if total > MAX_OBSERVATIONS:
                raise ValueError('component_merge_keypoint_quota')
            expected = np.frombuffer(blob, dtype='<f4').reshape(count, cols)[:, :2]
            actual = np.asarray([point.xy for point in image.points2D], dtype=float).reshape(count, 2)
            if not np.isfinite(expected).all() or not np.array_equal(actual, expected):
                raise ValueError('component_merge_database_keypoint_namespace')


def compatible(first, second, *, check=lambda: None):
    """Measure orientation-aware positive Sim3 consistency in scale-free units.

    This conservative preflight is not a replacement for COLMAP's subsequent
    bidirectional reprojection alignment at 4 px / min-inlier-observations .3.
    Camera rotations resolve the ambiguity of nearly collinear camera centers.
    """
    import numpy as np

    common = sorted(set(first.reg_image_ids()) & set(second.reg_image_ids()))
    if len(common) < 3:
        raise ValueError('component_merge_common_cameras_insufficient')
    rotations, source, target = [], [], []
    shared_counts = []
    for identity in common:
        check()
        a, b = first.images[identity], second.images[identity]
        if a.name != b.name or a.camera_id != b.camera_id or a.num_points2D() != b.num_points2D():
            raise ValueError('component_merge_common_namespace')
        shared = sum(x.has_point3D() and y.has_point3D() for x, y in zip(a.points2D, b.points2D, strict=True))
        shared_counts.append(shared)
        pa, pb = a.cam_from_world().inverse(), b.cam_from_world().inverse()
        ra, rb = np.asarray(pa.rotation.matrix()), np.asarray(pb.rotation.matrix())
        if any(not np.isfinite(v).all() for v in (ra, rb, pa.translation, pb.translation)):
            raise ValueError('component_merge_nonfinite_pose')
        for rotation in (ra, rb):
            if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) or abs(np.linalg.det(rotation) - 1) > 1e-6:
                raise ValueError('component_merge_invalid_rotation')
        rotations.append(rb @ ra.T)
        source.append(pa.translation)
        target.append(pb.translation)
    if sum(n >= 3 for n in shared_counts) < 3 or sum(shared_counts) < 15:
        raise ValueError('component_merge_common_2d_support_insufficient')
    u, _, vt = np.linalg.svd(np.sum(rotations, axis=0))
    rotation = u @ np.diag([1., 1., np.linalg.det(u @ vt)]) @ vt
    x, y = np.asarray(source) @ rotation.T, np.asarray(target)
    xc, yc = x - x.mean(axis=0), y - y.mean(axis=0)
    denominator = float(np.sum(xc * xc))
    span = float(np.sqrt(np.mean(np.sum(yc * yc, axis=1))))
    if denominator <= 1e-16 or span <= 1e-8:
        raise ValueError('component_merge_common_centers_degenerate')
    scale = float(np.sum(xc * yc) / denominator)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('component_merge_scale_not_positive')
    residual = np.linalg.norm(scale * xc - yc, axis=1) / span
    angles = [math.degrees(math.acos(float(np.clip((np.trace(rotation.T @ r) - 1) / 2, -1, 1)))) for r in rotations]
    if np.median(angles) > 1 or max(angles) > 3 or np.median(residual) > .02 or max(residual) > .05:
        raise ValueError('component_merge_sim3_inconsistent')
    return dict(common_cameras=len(common), shared_triangulated_2d=sum(shared_counts),
                scale=scale, rotation_median_deg=float(np.median(angles)), rotation_max_deg=max(angles),
                center_residual_relative_median=float(np.median(residual)),
                center_residual_relative_max=float(max(residual)),
                center_normalizer='rms_common_camera_centers_target_arbitrary_units')


def structural_audit(model, *, check=lambda: None):
    """Require both directions of tracks, one feature per image/point and depth>0."""
    import numpy as np

    ids = set(model.reg_image_ids())
    if not 3 <= len(ids) <= 240 or len(model.points3D) > MAX_POINTS:
        raise ValueError('component_merge_structural_quota')
    counts: dict[int, int] = {}
    total = 0
    for pid, point in model.points3D.items():
        if len(counts) % 512 == 0:
            check()
        xyz = np.asarray(point.xyz)
        if xyz.shape != (3,) or not np.isfinite(xyz).all() or not math.isfinite(point.error) or point.error < 0:
            raise ValueError('component_merge_nonfinite_point')
        elements = point.track.elements
        if len(elements) < 2 or point.track.length() != len(elements):
            raise ValueError('component_merge_invalid_track')
        total += len(elements)
        if total > MAX_OBSERVATIONS:
            raise ValueError('component_merge_observation_quota')
        seen = set()
        for element in elements:
            image_id, index = element.image_id, element.point2D_idx
            if image_id in seen:
                raise ValueError('component_merge_duplicate_image_observation')
            seen.add(image_id)
            if image_id not in ids or not 0 <= index < model.images[image_id].num_points2D():
                raise ValueError('component_merge_track_binding')
            image = model.images[image_id]
            feature = image.points2D[index]
            if not feature.has_point3D() or feature.point3D_id != pid or not np.isfinite(feature.xy).all():
                raise ValueError('component_merge_track_reciprocity')
            pose = image.cam_from_world()
            camera_point = pose.rotation.matrix() @ xyz + pose.translation
            if not np.isfinite(camera_point).all() or camera_point[2] <= 0:
                raise ValueError('component_merge_nonpositive_depth')
        counts[pid] = len(elements)
    reverse: dict[int, int] = {}
    examined = 0
    for identity in ids:
        check()
        image = model.images[identity]
        examined += image.num_points2D()
        if examined > MAX_OBSERVATIONS:
            raise ValueError('component_merge_observation_quota')
        for feature in image.points2D:
            if feature.has_point3D():
                pid = feature.point3D_id
                if pid not in counts:
                    raise ValueError('component_merge_image_reciprocity')
                reverse[pid] = reverse.get(pid, 0) + 1
    if counts != reverse:
        raise ValueError('component_merge_image_reciprocity')
    return dict(status='complete', observations=total, duplicate_image_observations=0,
                invalid_reciprocal_observations=0, nonpositive_depth=0)


def _child_affinity(pid):
    if os.name != 'nt':
        getattr(os, 'sched_setaffinity')(pid, set(sorted(getattr(os, 'sched_getaffinity')(0))[:2]))
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x0200 | 0x1000, False, pid)
    try:
        current, system = ctypes.c_size_t(), ctypes.c_size_t()
        if not handle or not kernel.GetProcessAffinityMask(handle, ctypes.byref(current), ctypes.byref(system)):
            raise RuntimeError('component_merge_affinity_unavailable')
        bits = [1 << bit for bit in range(ctypes.sizeof(current) * 8) if current.value & (1 << bit)][:2]
        if not bits or not kernel.SetProcessAffinityMask(handle, sum(bits)):
            raise RuntimeError('component_merge_affinity_unavailable')
    finally:
        if handle:
            kernel.CloseHandle(handle)


def _native(first, second, output, executable, check):
    """Own exactly one child; never kill names/process trees or touch CANCEL."""
    began = time.monotonic()
    log_path = output.parent / (output.name + '.log')
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='2')
    command = [str(executable), 'model_merger', '--input_path1', str(first),
               '--input_path2', str(second), '--output_path', str(output),
               '--max_reproj_error', str(MAX_REPROJECTION_PX), '--log_target', 'stderr']
    with log_path.open('xb') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            _child_affinity(process.pid)
            while process.poll() is None:
                check()
                if time.monotonic() - began >= MERGE_SECONDS:
                    raise RuntimeError('component_merge_native_timeout')
                if log_path.stat().st_size > MAX_LOG_BYTES:
                    raise RuntimeError('component_merge_log_quota')
                time.sleep(.1)
            check()
            if process.returncode != 0:
                raise RuntimeError('component_merge_native_failed')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
    return dict(exit_code=process.returncode, seconds=time.monotonic() - began, cpu_affinity_limit=2,
                max_reprojection_px=MAX_REPROJECTION_PX, min_inlier_observations=MIN_INLIER_OBSERVATIONS)


def _evaluate(model, prepared, selected, source_start, source_end, check):
    from scripts.pilot.reconstruct_route import model_assessment
    return model_assessment(model, prepared, selected, source_start, source_end, check=check)[1]


def merge_components(job, prepared, models, baseline, selected, source_start, source_end,
                     check, progress, *, assessment_check=None):
    """Return ``(chosen_model, report)`` without altering baselines or geometry.

    ``models`` are the <=4 reconstructions from this prepared database. Caller
    supplies cancellation/resource ``check``; those refusals propagate after an
    explicit result is sealed. An unavailable/mismatched optional executable,
    incompatibility or timeout keeps the original baseline. Invocation owns an
    exclusive UUID workspace and never resumes or deletes earlier evidence.
    """
    job, prepared = Path(job).absolute(), Path(prepared).absolute()
    if (job.is_symlink() or prepared.is_symlink() or not prepared.is_dir()
            or not prepared.resolve().is_relative_to(job.resolve())
            or type(selected) is not int or not 10 <= selected <= 240):
        raise ValueError('component_merge_scope')
    check()
    folder = prepared / ('component-merge-' + uuid.uuid4().hex)
    folder.mkdir()
    began = time.monotonic()
    report: dict[str, Any] = dict(schema='sphere-route-component-merge-v1', accepted=False, reason=None,
                  workspace=str(folder.relative_to(job)), attempts=[], baseline=None, chosen=None,
                  source_modified=False, poses_interpolated=False, execution_qualified=False,
                  navigation_qualified=False, physical_actions=0, network_downloads=False)
    write_json(folder / 'intent.json', dict(schema='sphere-route-component-merge-intent-v1',
        total_seconds=TOTAL_SECONDS, native_seconds=MERGE_SECONDS, max_models=MAX_MODELS,
        max_merges=MAX_MERGES, max_reprojection_px=MAX_REPROJECTION_PX,
        min_inlier_observations=MIN_INLIER_OBSERVATIONS, cpu_affinity_limit=2,
        rotation_median_limit_deg=1., rotation_max_limit_deg=3.,
        center_relative_median_limit=.02, center_relative_max_limit=.05,
        max_points_combined=MAX_POINTS, max_observations=MAX_OBSERVATIONS,
        max_log_bytes=MAX_LOG_BYTES,
        executable_sha256=COLMAP_SHA256, execution_qualified=False))
    chosen, propagate, paths, before = baseline, None, [], {}

    def bounded():
        # Never translate a caller's cancellation/resource exception into a
        # successful optional-stage return (including arbitrary exception types).
        try:
            check()
            if (job / 'CANCEL').exists():
                raise RuntimeError('cancelled')
        except Exception as error:
            raise _CallerRefusal(error) from error
        if time.monotonic() - began >= TOTAL_SECONDS:
            raise RuntimeError('component_merge_timeout')

    def observation_check():
        bounded()
        if assessment_check is not None:
            try:
                assessment_check()
            except Exception as error:
                raise _CallerRefusal(error) from error

    try:
        bounded()
        if not COLMAP.is_file():
            report['reason'] = 'component_merge_unavailable'
        elif COLMAP.is_symlink() or _hash(COLMAP, bounded) != COLMAP_SHA256:
            report['reason'] = 'component_merge_binary_pin_mismatch'
        elif not 2 <= len(models) <= MAX_MODELS:
            report['reason'] = 'component_merge_component_count'
        else:
            import pycolmap as p

            if p.__version__ != '4.2.1':
                raise ValueError('component_merge_binding_version')
            names, paths, before = _source(job, prepared, selected, bounded)
            report['source_before'] = before
            report['source_manifest_sha256'] = before['input/manifest.json']
            report['database_sha256'] = before[(prepared / 'database.db').relative_to(job).as_posix()]
            entries = list(models.items())
            if sum(model.num_points3D() for _, model in entries) > MAX_POINTS:
                raise ValueError('component_merge_combined_point_quota')
            if baseline is not None and not any(model is baseline for _, model in entries):
                raise ValueError('component_merge_baseline_not_input')
            for _, model in entries:
                bounded()
                _namespace(model, prepared / 'database.db', names, bounded)
            active = baseline if baseline is not None else max(entries, key=lambda row: row[1].num_reg_images())[1]
            donors = [(identity, model) for identity, model in entries if model is not active]
            if baseline is not None:
                report['baseline'] = _evaluate(baseline, prepared, selected, source_start, source_end, observation_check)
            best = report['baseline']
            active_path = folder / 'initial'
            active_path.mkdir()
            active.write(active_path)
            # Grow one compatible union. Failed/incompatible pairs never restore
            # an old edge or introduce inferred poses; each donor is tried once.
            while donors and len(report['attempts']) < MAX_MERGES:
                bounded()
                donors.sort(key=lambda row: len(set(active.reg_image_ids()) & set(row[1].reg_image_ids())), reverse=True)
                identity, donor = donors.pop(0)
                attempt = dict(donor=str(identity), accepted=False)
                report['attempts'].append(attempt)
                try:
                    attempt['compatibility'] = compatible(donor, active, check=bounded)
                    expected = set(active.reg_image_ids()) | set(donor.reg_image_ids())
                    if len(expected) <= active.num_reg_images():
                        raise ValueError('component_merge_no_new_cameras')
                    index = len(report['attempts'])
                    donor_path, output = folder / f'input-{index}', folder / f'merged-{index}'
                    donor_path.mkdir()
                    donor.write(donor_path)
                    output.mkdir()
                    bounded()
                    progress('component_merge', index, min(len(models) - 1, MAX_MERGES))
                    attempt['native'] = _native(donor_path, active_path, output, COLMAP, bounded)
                    bounded()
                    candidate = p.Reconstruction(output)
                    if set(candidate.reg_image_ids()) != expected:
                        raise ValueError('component_merge_camera_union_incomplete')
                    _namespace(candidate, prepared / 'database.db', names, bounded)
                    attempt['structural'] = structural_audit(candidate, check=bounded)
                    assessment = _evaluate(candidate, prepared, selected, source_start, source_end, observation_check)
                    attempt['assessment'] = assessment
                    # A structurally valid intermediate union can support the
                    # next merge, but never bypass final scene/route assessment.
                    active, active_path = candidate, output
                    if (assessment['scene_admissible'] and (best is None or candidate_rank(assessment) > candidate_rank(best))):
                        chosen, best = candidate, assessment
                        report.update(accepted=True, chosen=f'merged-{index}', reason='assessed_component_union_improved')
                        attempt['accepted'] = True
                    else:
                        attempt['reason'] = 'component_merge_no_assessed_improvement'
                except (ValueError, RuntimeError, OSError) as error:
                    attempt['reason'] = _error_code(error)
                    if str(error) == 'component_merge_timeout':
                        raise
                write_json(folder / 'progress.json', report)
            if not report['accepted']:
                report['reason'] = 'component_merge_no_assessed_improvement'
        bounded()  # Cancellation wins even at an optional-unavailable return.
    except _CallerRefusal as error:
        propagate = error.error
        chosen = baseline
        report.update(accepted=False, chosen=None, reason='component_merge_caller_refused', error_code=_error_code(error.error))
    except (ValueError, RuntimeError, OSError, ImportError, KeyError, TypeError, OverflowError) as error:
        chosen = baseline
        report.update(accepted=False, chosen=None, reason=_error_code(error))
    finally:
        # Never extend the stage to finish a hash audit after its deadline.
        # An incomplete audit cannot yield an adopted candidate.
        try:
            after = {path.relative_to(job).as_posix(): _hash(path, bounded) for path in paths}
            report['source_after'] = after
            report['source_modified'] = bool(before and before != after)
            if report['source_modified']:
                chosen = baseline
                report.update(accepted=False, chosen=None, reason='component_merge_source_changed')
            bounded()
        except _CallerRefusal as error:
            chosen = baseline
            report.update(accepted=False, chosen=None, source_verification='incomplete', reason='component_merge_final_check_refused')
            propagate = error.error
        except Exception as error:
            chosen = baseline
            report.update(accepted=False, chosen=None, source_verification='incomplete', reason=_error_code(error))
        report['seconds'] = time.monotonic() - began
        write_json(folder / 'result.json', report)
    if propagate is not None:
        raise propagate
    return chosen, report


class _CallerRefusal(Exception):
    def __init__(self, error):
        self.error = error


def _error_code(error):
    message = str(error)
    return message if re.fullmatch(r'[a-z][a-z0-9_]{0,95}', message) else 'component_merge_inconclusive_' + type(error).__name__
