"""One bounded, local learned-matching alternative for a recorded camera route.

No source images, frame indices, existing feature reports or models are replaced.
The alternative owns an exclusive directory and can replace the caller's model
only when measured observations support the complete route. No Android input or
network download is performed here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.learned_route_features import available, extract_and_match
from scripts.pilot.route_geometry_selection import candidate_rank, evaluate_candidate

ROOT = Path(__file__).resolve().parents[2]
TOTAL_SECONDS = 420


def recovery_device():
    """Prefer the installed accelerator; CPU remains a bounded fallback."""
    import torch
    return 'cuda' if torch.cuda.is_available() else 'cpu'


def _regular(path, root, maximum):
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise ValueError('learned_recovery_source_symlink')
    if (not path.is_file() or not path.resolve().is_relative_to(root.resolve())
            or not 0 < path.stat().st_size <= maximum):
        raise ValueError('learned_recovery_source_invalid')


def _link_workspace(job, prepared, folder, selected):
    index = prepared / 'reconstruction-input.json'
    manifest = job / 'input/manifest.json'
    _regular(index, prepared, 1024**2)
    _regular(manifest, job, 65536)
    source_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    provenance = json.loads(index.read_bytes())
    rows = provenance.get('images')
    if (provenance.get('source_manifest_sha256') != source_hash
            or not isinstance(rows, list) or len(rows) != selected):
        raise ValueError('learned_recovery_source_binding')
    names = [row['image'] for row in rows]
    if (len(set(names)) != selected
            or any(not isinstance(name, str) or not re.fullmatch(r'images/[0-9]{8}\.png', name)
                   for name in names)):
        raise ValueError('learned_recovery_image_binding')
    (folder / 'images').mkdir()
    masks = prepared / 'masks'
    if masks.is_symlink():
        raise ValueError('learned_recovery_source_symlink')
    if masks.exists():
        (folder / 'masks').mkdir()
    os.link(index, folder / index.name)
    for row,name in zip(rows,names,strict=True):
        source = prepared / name
        _regular(source, prepared, 8 * 1024**2)
        if (not isinstance(row.get('png_sha256'),str)
                or hashlib.sha256(source.read_bytes()).hexdigest()!=row['png_sha256']):
            raise ValueError('learned_recovery_image_changed')
        os.link(source, folder / name)
        mask = masks / (Path(name).name + '.png')
        if mask.is_symlink():
            raise ValueError('learned_recovery_source_symlink')
        if mask.exists():
            _regular(mask, prepared, 8 * 1024**2)
            os.link(mask, folder / 'masks' / mask.name)
    return source_hash


def _evaluate(model, prepared, selected, source_start, source_end, *, check=None):
    from scripts.pilot.reconstruct_route import model_geometry
    from scripts.pilot.reconstruction_quality import pinhole_condition, sparse_condition
    from scripts.pilot.route_observation_support import compact_observation_support, observation_support

    geometry = None
    try:
        geometry = model_geometry(model, prepared)
        conditioning = sparse_condition([camera['center'] for camera in geometry['cameras']],
                                        [point.xyz for point in model.points3D.values()])
        intrinsic = geometry['cameras'][0]['intrinsics']
        intrinsics = pinhole_condition(intrinsic['width'], intrinsic['height'],
                                      intrinsic['fx'], intrinsic['fy'])
        report = evaluate_candidate(geometry, selected=selected, points=model.num_points3D(),
                                    reprojection_px=model.compute_mean_reprojection_error(),
                                    conditioning=conditioning, intrinsics_condition=intrinsics,
                                    source_start=source_start, source_end=source_end)
    except (ValueError, RuntimeError, TypeError, KeyError, IndexError, OverflowError) as error:
        report = evaluate_candidate(dict(cameras=[]), selected=selected, points=0,
                                    reprojection_px=None, conditioning={}, intrinsics_condition={},
                                    source_start=source_start, source_end=source_end)
        report['evaluation_error_type'] = type(error).__name__
    report['observation_support'] = compact_observation_support(observation_support(model, geometry['cameras'] if geometry else [], check=check))
    return geometry, report


def recover_with_learned(job, prepared, baseline, selected, source_start, source_end,
                         reader, check, progress, *, assessment_check=None):
    """Return ``(chosen_model, report)``; cancellation/resource refusals propagate.

    The installed pinned matcher runs with 1024 features. Its own
    validation prevents downloads. A 420 s watchdog covers preparation/matching
    and mapping; native mapping additionally has a 180 s/2-thread bound.
    Reusing an existing recovery intent is refused instead of repeating work.
    ``baseline`` may be None when the first mapping produced no component.
    """
    job, prepared = Path(job).absolute(), Path(prepared).absolute()
    folder = prepared / 'learned-recovery'
    if folder.exists() or folder.is_symlink():
        raise RuntimeError('learned_recovery_existing_intent')
    if (job.is_symlink() or prepared.is_symlink() or not prepared.is_dir()
            or not prepared.resolve().is_relative_to(job.resolve())
            or type(selected) is not int or not 10 <= selected <= 240):
        raise ValueError('learned_recovery_scope')
    check()
    folder.mkdir()
    report = dict(schema='sphere-learned-route-recovery-v1', accepted=False,
                  selected=selected, models=[], baseline=None, chosen_model=None,
                  source_modified=False, poses_interpolated=False, physical_actions=0,
                  execution_qualified=False, network_downloads=False,
                  device='cpu', max_features=1024)
    write_json(folder / 'intent.json', dict(schema='sphere-learned-route-recovery-intent-v1',
               scope='OFFLINE_GEOMETRY_ONLY', selected=selected, physical_actions=0,
               total_seconds=TOTAL_SECONDS, mapping_seconds=180, device='cpu', max_features=1024))
    began = time.monotonic()
    token = None
    finished = threading.Event()
    reasons = []
    thread = None

    def bounded():
        check()
        if time.monotonic() - began > TOTAL_SECONDS:
            raise RuntimeError('learned_recovery_timeout')
        if reasons:
            raise RuntimeError(reasons[0])

    def bounded_assessment():
        if assessment_check is None:
            return bounded()
        assessment_check()
        if time.monotonic() - began > TOTAL_SECONDS:
            raise RuntimeError('learned_recovery_timeout')
        if reasons:
            raise RuntimeError(reasons[0])

    def watch():
        while not finished.wait(2):
            try:
                bounded()
            except Exception as error:
                reasons.append(str(error) if isinstance(error, RuntimeError) else 'learned_recovery_watch_failed')
                token.cancel()
                return

    chosen = baseline
    propagate = None
    try:
        if not available(ROOT):
            report['reason'] = 'learned_matching_unavailable'
        else:
            report['source_manifest_sha256'] = _link_workspace(job, prepared, folder, selected)
            bounded()
            import pycolmap as p

            report['device']=recovery_device()

            token = p.CancellationToken()
            thread = threading.Thread(target=watch, daemon=True)
            thread.start()
            if baseline is not None:
                _, report['baseline'] = _evaluate(baseline, prepared, selected, source_start, source_end, check=bounded_assessment)
            bounded()
            progress('features', 0, selected)
            extract_and_match(ROOT, folder, folder / 'database.db', reader, token, bounded,
                              progress=progress, max_features=1024, device=report['device'],filter_stationary=True)
            bounded()
            progress('cameras', 0, selected)
            (folder / 'models').mkdir()
            options = p.IncrementalPipelineOptions(num_threads=2, random_seed=17,
                max_runtime_seconds=180, max_num_models=4, ignore_watermarks=True,
                structure_less_registration_fallback=False, ba_refine_sensor_from_rig=False)
            models = p.incremental_mapping(folder / 'database.db', folder / 'images', folder / 'models',
                                           options=options, cancellation_token=token)
            bounded()
            if len(models) > 4:
                raise RuntimeError('learned_recovery_model_quota')
            eligible = []
            for index, (identity, model) in enumerate(models.items()):
                bounded()
                geometry, candidate = _evaluate(model, folder, selected, source_start, source_end, check=bounded_assessment)
                report['models'].append(dict(model=str(identity), **candidate))
                if geometry is not None:
                    write_json(folder / f'geometry-{index}.json', geometry)
                if (candidate['route_admissible']
                        and (report['baseline'] is None or candidate_rank(candidate) > candidate_rank(report['baseline']))):
                    eligible.append((model, identity, candidate))
            if eligible:
                chosen, identity, _ = max(eligible, key=lambda item: candidate_rank(item[2]))
                report.update(accepted=True, chosen_model=str(identity), reason='complete_observed_route_improved')
            else:
                report['reason'] = 'no_admissible_route_improvement'
    except Exception as error:
        reason = reasons[0] if reasons else str(error)
        report.update(accepted=False, chosen_model=None, reason='learned_recovery_inconclusive',
                      error_type=type(error).__name__)
        if re.fullmatch(r'[a-z][a-z0-9_]{0,79}', reason):
            report['error_code'] = reason
        chosen = baseline
        if reason == 'cancelled' or reason.startswith('resource_guard'):
            report['reason'] = reason
            propagate = RuntimeError(reason)
        elif reason == 'learned_recovery_timeout':
            report['reason'] = reason
    finally:
        finished.set()
        if thread is not None:
            thread.join(5)
        # A resource/cancellation result racing with the last candidate must
        # still defeat adoption after the watchdog has actually stopped.
        if reasons:
            chosen = baseline
            report.update(accepted=False, chosen_model=None, reason='learned_recovery_inconclusive')
            if reasons[0] == 'cancelled' or reasons[0].startswith('resource_guard'):
                report['reason'] = reasons[0]
                propagate = RuntimeError(reasons[0])
            elif reasons[0] == 'learned_recovery_timeout':
                report['reason'] = reasons[0]
        report['seconds'] = time.monotonic() - began
        write_json(folder / 'result.json', report)
    if propagate is not None:
        raise propagate
    return chosen, report
