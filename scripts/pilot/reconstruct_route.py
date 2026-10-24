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
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from motor_worker.browser_teach import prepare_browser, validate_browser
from scripts.pilot.atomic_json import write_json
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / '.local-pilot/reconstruction-tools'
BRUSH_SHA = 'b68e3e9cf052d51bf3ee30776fa5a364de7f2ba13b58443128ff797bb7bcfcd6'


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def checkpoint(job):
    if (job / 'CANCEL').exists():
        raise RuntimeError('cancelled')
    if evaluate(collect(ROOT)):
        raise RuntimeError('resource_guard')


def state(job, phase, **details):
    write_json(job / 'state.json', dict(phase=phase, updated_at=time.time(), **details))


def masked_inputs(prepared, mode):
    """Keep original RGB; a separate documented exclusion mask precedes SfM.

    This fixed game preset excludes HUD and the usual third-person avatar. It
    does not detect arbitrary moving players/cars and is never a collision mask.
    """
    from PIL import Image, ImageDraw

    if mode == 'none':
        return None
    folder = prepared / 'masks'
    folder.mkdir()
    for path in (prepared / 'images').glob('*.png'):
        with Image.open(path) as rgb:
            width, height = rgb.size
        mask = Image.new('L', (width, height), 255)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((0, 0, width, int(height * .25)), fill=0)
        draw.rectangle((0, int(height * .56), int(width * .25), height), fill=0)
        draw.rectangle((int(width * .83), int(height * .52), width, height), fill=0)
        draw.rectangle((int(width * .39), int(height * .47), int(width * .64), height), fill=0)
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
        cameras.append(dict(image=image.name, center=pose[:, 3].tolist(),
                            camera_to_world=pose.tolist(),
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


def reconstruct(job, mask, steps):
    checkpoint(job)
    sys.path.insert(0, str(TOOLS / 'pycolmap-4.2.1'))
    state(job, 'verifying')
    capture = validate_browser(job / 'input')
    duration = capture.frames[-1]['relative_ticks_90k'] / 90000
    if duration < 5:
        raise RuntimeError('clip_too_short_minimum_5_seconds')
    state(job, 'extracting', source_frames=len(capture.frames))
    prepared = job / 'prepared'
    prepare_browser(job / 'input', prepared, interval=max(.5, duration / 230),
                    max_images=240, max_bytes=2**31)
    images = list((prepared / 'images').glob('*.png'))
    if len(images) < 10:
        raise RuntimeError('insufficient_selected_views')
    masks = masked_inputs(prepared, mask)
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
        reader = p.ImageReaderOptions(camera_model='PINHOLE')
        if masks:
            reader.mask_path = str(masks)
        features = p.FeatureExtractionOptions(num_threads=4, use_gpu=False, max_image_size=1920)
        features.sift.max_num_features = 8192
        state(job, 'features', selected_views=len(images), masks=mask)
        database = prepared / 'database.db'
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
                                               max_runtime_seconds=600, max_num_models=4)
        models = p.incremental_mapping(database, prepared / 'images', sparse,
                                       options=options, cancellation_token=token)
    finally:
        finished.set()
        guard.join(5)
    if aborted:
        raise RuntimeError(aborted[0])
    checkpoint(job)
    if not models:
        raise RuntimeError('no_connected_cameras_need_translation_and_overlap')
    rec = max(models.values(), key=lambda model: model.num_reg_images())
    geometry = model_geometry(rec, prepared)
    write_json(job / 'geometry.json', geometry)
    coverage = rec.num_reg_images() / len(images)
    error = rec.compute_mean_reprojection_error()
    quality = dict(registered=rec.num_reg_images(), selected=len(images), coverage=coverage,
                   points=rec.num_points3D(), mean_reprojection_px=error, components=len(models))
    write_json(job / 'quality.json', quality)
    if rec.num_reg_images() < 10 or coverage < .7 or rec.num_points3D() < 300 or not math.isfinite(error) or error > 3:
        raise RuntimeError('camera_quality_gate_failed')
    # A largest component is not a claim that discarded views are connected.
    target = prepared / 'sparse' / '0'
    target.mkdir(parents=True)
    rec.write(target)
    rec.export_PLY(prepared / 'sparse' / 'points.ply')
    # Brush uses masks/image.png; keep COLMAP's independent mask naming intact.
    if masks:
        for path in list(masks.glob('*.png.png')):
            (masks / path.name[:-4]).write_bytes(path.read_bytes())
    archive = TOOLS / 'brush-app-v0.3.0-windows.zip'
    if digest(archive) != BRUSH_SHA:
        raise RuntimeError('brush_archive_mismatch')
    binary = TOOLS / 'brush-v0.3.0/brush_app.exe'
    with zipfile.ZipFile(archive) as package:
        executables = [name for name in package.namelist() if name.endswith('/brush_app.exe') or name == 'brush_app.exe']
        if len(executables) != 1 or hashlib.sha256(package.read(executables[0])).hexdigest() != digest(binary):
            raise RuntimeError('brush_binary_mismatch')
    export = job / 'dense'
    export.mkdir()
    state(job, 'training', quality=quality, total_steps=steps)
    command = [str(binary), str(prepared), '--total-steps', str(steps), '--max-splats', '750000',
               '--max-resolution', '1920', '--sh-degree', '2', '--seed', '17',
               '--export-every', str(steps), '--export-path', str(export), '--export-name', 'scene.ply']
    with (job / 'brush.log').open('xb') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 1200
        try:
            while process.poll() is None:
                checkpoint(job)
                if time.monotonic() > deadline or log.tell() > 20 * 1024**2:
                    raise RuntimeError('brush_time_or_log_budget')
                time.sleep(2)
            if process.returncode:
                raise RuntimeError('brush_failed_see_local_log')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(10)
    checkpoint(job)
    ply = export / 'scene.ply'
    if not ply.is_file() or not 1024 < ply.stat().st_size <= 256 * 1024**2:
        raise RuntimeError('dense_export_missing_or_exceeds_256mib')
    header = ply.open('rb')
    try:
        prefix = header.read(4096)
    finally:
        header.close()
    if not prefix.startswith(b'ply\n') or b'property float scale_0' not in prefix:
        raise RuntimeError('dense_export_not_gaussian_ply')
    result = dict(schema='sphere-dense-reconstruction-v1', quality=quality,
                  source_manifest_sha256=geometry['source_manifest_sha256'],
                  ply_sha256=digest(ply), ply_bytes=ply.stat().st_size,
                  geometry_sha256=digest(job / 'geometry.json'),
                  metric_scale=None, masks=mask, dynamic_objects_removed=False,
                  collision_map=False, execution_qualified=False,
                  tools=dict(pycolmap='4.2.1', brush='0.3.0'), training_steps=steps)
    write_json(job / 'result.json', result)
    (job / 'COMPLETE').write_text(digest(job / 'result.json') + '\n', encoding='ascii')
    state(job, 'complete', result=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--mask', choices=['none', 'game'], default='game')
    parser.add_argument('--steps', type=int, choices=[3000, 5000, 10000], default=5000)
    args = parser.parse_args()
    job = args.job.resolve(strict=True)
    os.environ.update(OMP_NUM_THREADS='4', HF_HUB_OFFLINE='1', RUST_LOG='info')
    try:
        reconstruct(job, args.mask, args.steps)
    except Exception as error:
        # Keep raw records and partial outputs. Never mark partial training complete.
        state(job, 'cancelled' if str(error) == 'cancelled' else 'failed',
              error=str(error)[:300], error_type=type(error).__name__)
        raise


if __name__ == '__main__':
    main()
