"""Opt-in CPU surface reconstruction from an existing, hash-bound camera model.

The Gaussian result and original capture are never modified. Pinned external
OpenMVS (AGPL-3.0) stays in the local tool directory, outside the Android APK.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import TOOLS, checkpoint, digest
from scripts.pilot.surface_bake import bake

BINARIES = {
    'InterfaceCOLMAP.exe': '785311ce935b49a5c993570e5daf77b5616fe7fce871b7ddee3b5e5c10c30cc4',
    'DensifyPointCloud.exe': 'baa34151aa66ca5b909645330fdb79c271087f08759872dd2d474717dc901d77',
    'ReconstructMesh.exe': 'bb84317e4881effed587a560a80c574c1e22fc3dd9b1d9655127944f66b8abcc',
}
SURFACE_TERMINAL = {'ready', 'failed', 'cancelled'}


def source_model(job):
    result = json.loads((job / 'result.json').read_text('utf-8'))
    name = result.get('camera_model_path', 'prepared/sparse/0')
    if not re.fullmatch(r'(?:prepared|revision-[12])/sparse/0', name):
        raise ValueError('surface_camera_model_path_invalid')
    for target in ('geometry.json', 'input/manifest.json'):
        if digest(job / target) != result['geometry_sha256' if target == 'geometry.json' else 'source_manifest_sha256']:
            raise ValueError('surface_source_binding_changed')
    if not (job / 'COMPLETE').is_file():
        raise ValueError('surface_completed_source_required')
    folder = job / name
    if not folder.resolve().is_relative_to(job.resolve()) or any(p.is_symlink() for p in [folder, *folder.parents][:4]):
        raise ValueError('surface_camera_model_path_invalid')
    return folder, result


def tools_available():
    folder = TOOLS / 'openmvs-v2.4.0-cpu/vc17/x64/Release'
    return os.name == 'nt' and all((folder / name).is_file() for name in BINARIES)


def reconstruct(job):
    output = job / 'surface'
    if not (output / 'START').is_file() or (output / 'result.json').exists():
        raise ValueError('surface_exclusive_intent_required')
    started, next_resource = time.monotonic(), 0.

    def check():
        nonlocal next_resource
        if (output / 'CANCEL').exists() or (job / 'CANCEL').exists():
            raise RuntimeError('cancelled')
        if time.monotonic() - started > 1800:
            raise RuntimeError('surface_time_budget')
        if time.monotonic() >= next_resource:
            checkpoint(output)
            if sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) > 4 * 1024**3:
                raise RuntimeError('surface_working_disk_quota')
            next_resource = time.monotonic() + 3

    def state(phase, **details):
        check()
        write_json(output / 'state.json', dict(phase=phase, updated_at=time.time(), **details))

    try:
        state('preparing')
        model, result = source_model(job)
        if not tools_available():
            raise RuntimeError('surface_openmvs_cpu_not_installed')
        binaries = TOOLS / 'openmvs-v2.4.0-cpu/vc17/x64/Release'
        for name, sha in BINARIES.items():
            if digest(binaries / name) != sha:
                raise ValueError('surface_native_digest_changed')
        sys.path.insert(0, str(TOOLS / 'pycolmap-4.2.1'))
        import pycolmap as p

        if p.__version__ != '4.2.1':
            raise ValueError('surface_colmap_version_changed')
        rec = p.Reconstruction(model)
        geometry = json.loads((job / 'geometry.json').read_text('utf-8'))
        cameras = geometry['cameras']
        if not 3 <= len(cameras) <= 96 or {c['image'] for c in cameras} != {im.name for im in rec.images.values()}:
            raise ValueError('surface_view_limit_or_camera_binding')
        import numpy as np

        recovered = {im.name: im for im in rec.images.values()}
        for camera in cameras:
            image = recovered[camera['image']]
            k = camera['intrinsics']
            calibration = rec.cameras[image.camera_id].calibration_matrix()
            if (not np.allclose(image.cam_from_world().inverse().matrix(), camera['camera_to_world'], atol=1e-7, rtol=1e-7)
                    or not np.allclose(calibration, [[k['fx'], 0, k['cx']], [0, k['fy'], k['cy']], [0, 0, 1]], atol=1e-7, rtol=1e-7)):
                raise ValueError('surface_calibration_binding_changed')
        provenance = json.loads((job / 'prepared/reconstruction-input.json').read_text('utf-8'))
        if provenance['source_manifest_sha256'] != result['source_manifest_sha256']:
            raise ValueError('surface_source_binding_changed')
        expected = {Path(row['image']).name: row['png_sha256'] for row in provenance['images']}
        dataset = output / 'dataset'
        images = dataset / 'images'
        images.mkdir(parents=True)
        (dataset / 'sparse').mkdir()
        rec.write(dataset / 'sparse')
        masks = job / model.relative_to(job).parts[0] / 'masks'
        hashes, mask_hashes = {}, {}
        for camera in cameras:
            check()
            name = camera['image']
            if not re.fullmatch(r'[0-9]{8}\.png', name):
                raise ValueError('surface_image_name_invalid')
            source = job / 'prepared/images' / name
            if source.is_symlink() or digest(source) != expected[name]:
                raise ValueError('surface_source_image_changed')
            shutil.copyfile(source, images / name)
            hashes[name] = expected[name]
            mask = masks / name
            if mask.is_file():
                if mask.is_symlink():
                    raise ValueError('surface_mask_invalid')
                shutil.copyfile(mask, images / (name[:-4] + '.mask.png'))
                mask_hashes[name] = digest(mask)
        binding = dict(source_manifest_sha256=result['source_manifest_sha256'],
            geometry_sha256=result['geometry_sha256'], source_images_sha256=hashes,
            source_masks_sha256=mask_hashes,
            camera_model_sha256={f.name: digest(f) for f in model.glob('*.bin')},
            tool_tag='v2.4.0', native_binaries=BINARIES, cpu_threads=4,
            max_geometry_resolution=960, max_texture_pixels=64 * 1024**2)
        write_json(output / 'provenance.json', binding)

        def run(binary, args, phase):
            state(phase)
            process = subprocess.Popen([str(binaries / binary), *map(str, args), '--max-threads', '4'],
                cwd=output, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                while process.poll() is None:
                    check()
                    time.sleep(1)
                if process.returncode:
                    raise RuntimeError('surface_native_failed_see_local_log')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(10)

        run('InterfaceCOLMAP.exe', ['-i', dataset, '-o', output / 'scene.mvs',
            '--image-folder', images], 'preparing')
        run('DensifyPointCloud.exe', [output / 'scene.mvs', '-o', output / 'scene_dense.mvs',
            '--resolution-level', '1', '--max-resolution', '960', '--min-resolution', '640',
            '--number-views', '5', '--number-views-fuse', '3', '--ignore-mask-label', '0',
            '--geometric-iters', '2', '--estimate-roi', '0'], 'densifying')
        run('ReconstructMesh.exe', [output / 'scene_dense.mvs', '-o', output / 'scene_mesh.mvs',
            '--close-holes', '0', '--smooth', '0', '--target-face-num', '330000'], 'meshing')
        state('baking', views=0, total_views=len(cameras))
        counts = bake(output / 'scene_mesh.ply', cameras, images, output / 'scene.glb', check,
                      lambda done, total: state('baking', views=done, total_views=total))
        check()
        # Reconcile the source again before publication; a failed/unknown attempt cannot publish READY.
        source_model(job)
        if any(digest(job / 'prepared/images' / name) != sha for name, sha in hashes.items()):
            raise ValueError('surface_source_image_changed')
        if any(digest(masks / name) != sha for name, sha in mask_hashes.items()):
            raise ValueError('surface_mask_changed')
        if any(digest(model / name) != sha for name, sha in binding['camera_model_sha256'].items()):
            raise ValueError('surface_camera_model_changed')
        receipt = dict(schema='sphere-observed-surface-v1', **binding, **counts,
            file='scene.glb', sha256=digest(output / 'scene.glb'), bytes=(output / 'scene.glb').stat().st_size,
            metric_scale=None, navigation_qualified=False, collision_map=False,
            geometric_accuracy_accepted=False, unseen_surfaces_filled=False,
            seconds=round(time.monotonic() - started, 2))
        write_json(output / 'result.json', receipt)
        state('ready')
        return receipt
    except Exception as error:
        write_json(output / 'state.json', dict(phase='cancelled' if str(error) == 'cancelled' else 'failed',
            error=str(error)[:200], updated_at=time.time()))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, type=Path)
    args = parser.parse_args()
    reconstruct(args.job.resolve(strict=True))


if __name__ == '__main__':
    main()
