"""Bounded loop proposals and anchored registration for a valid partial map.

Retrieval proposes correspondences; learned matching, epipolar verification and
pose/geometry checks decide whether the candidate can replace the partial map.
No raw RGB is changed, and a rejected candidate leaves the anchor intact.
"""
from __future__ import annotations

import json
import math
import threading
import time

from scripts.pilot.atomic_json import write_json
from scripts.pilot.learned_route_features import load_matcher, verify_pairs
from scripts.pilot.reconstruction_quality import sparse_condition


def known_pairs(database, ids):
    """Native bulk reads omit empty rows; existence still forbids re-insertion."""
    return {tuple(sorted((first, second))) for i, first in enumerate(ids)
            for second in ids[i+1:] if database.exists_matches(first, second)}


def bounded_pairs(similarity, ids, registered, existing, limit=1200):
    """Keep all small-map missing-view tests; balance larger maps by view."""
    missing = [i for i, identity in enumerate(ids) if identity not in registered]
    rows = {}
    for i in missing:
        rows[i] = sorted((j for j, identity in enumerate(ids) if identity in registered
                          and tuple(sorted((ids[i], identity))) not in existing),
                         key=lambda j: (-float(similarity[i, j]), abs(i-j), j))
    chosen = set()
    # Round-robin prevents the first missing view consuming the pair budget.
    for rank in range(len(ids)):
        for i in missing:
            if rank < len(rows[i]):
                chosen.add(tuple(sorted((i, rows[i][rank]))))
                if len(chosen) == limit:
                    return sorted(chosen)
    for i in range(len(ids)):
        for j in sorted((j for j in range(len(ids)) if abs(i-j) >= 10),
                        key=lambda j: (-float(similarity[i, j]), j))[:8]:
            if tuple(sorted((ids[i], ids[j]))) not in existing:
                chosen.add(tuple(sorted((i, j))))
                if len(chosen) == limit:
                    return sorted(chosen)
    return sorted(chosen)


def complete_partial(root, prepared, database, anchor, check):
    import cv2
    import numpy as np
    import pycolmap as p
    import torch

    folder = prepared / 'loop-completion'
    folder.mkdir()
    started, checked = time.monotonic(), 0.

    def bounded():
        nonlocal checked
        if time.monotonic() - started > 800:
            raise RuntimeError('loop_completion_timeout')
        if time.monotonic() - checked >= 3:
            check()
            checked = time.monotonic()

    cv2.setNumThreads(4)
    cv2.setRNGSeed(17)
    with p.Database.open(database) as db:
        images = sorted(db.read_all_images(), key=lambda image: image.name)
        if not anchor.num_reg_images() < len(images) <= 240:
            raise RuntimeError('loop_completion_view_budget')
        descriptors = [db.read_descriptors(image.image_id).data.astype('float32') / 512 for image in images]
        rng = np.random.default_rng(17)
        sample = np.concatenate([d[rng.choice(len(d), min(300, len(d)), replace=False)] for d in descriptors])
        _, _, centers = cv2.kmeans(sample, 128, None,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 15, .001), 1, cv2.KMEANS_PP_CENTERS)
        bags = []
        for data in descriptors:
            bounded()
            _, index = cv2.batchDistance(data, centers, cv2.CV_32F, normType=cv2.NORM_L2, K=1)
            bags.append(np.bincount(index[:, 0], minlength=128))
        hist = np.asarray(bags, dtype='float32')
        hist = np.sqrt(hist / np.maximum(hist.sum(1, keepdims=True), 1)) * (
            np.log((1 + len(hist)) / (1 + (hist > 0).sum(0))) + 1)
        hist /= np.maximum(np.linalg.norm(hist, axis=1, keepdims=True), 1e-6)
        ids = [image.image_id for image in images]
        existing = known_pairs(db, ids)
        pairs = bounded_pairs(hist @ hist.T, ids, set(anchor.reg_image_ids()), existing)
        matcher = load_matcher(root, memory_fraction=.35)
        features = {}
        for image, data in zip(images, descriptors, strict=True):
            bounded()
            keypoints = db.read_keypoints(image.image_id)
            camera = db.read_camera(image.camera_id)
            data /= np.maximum(np.linalg.norm(data, axis=-1, keepdims=True), 1e-6)
            tensors = dict(keypoints=keypoints[:, :2], scales=keypoints[:, 2], oris=keypoints[:, 3],
                           descriptors=data, image_size=np.array([camera.width, camera.height], dtype='float32'))
            features[image.image_id] = {key: torch.from_numpy(np.ascontiguousarray(value))[None].to('cuda')
                                        for key, value in tensors.items()}
        with torch.inference_mode():
            for i, j in pairs:
                bounded()
                first, second = ids[i], ids[j]
                matches = matcher(dict(image0=features[first], image1=features[second]))['matches'][0]
                matches = matches.cpu().numpy().astype('uint32')
                if (matches.ndim != 2 or matches.shape[1] != 2 or len(matches) > 4096
                        or len(matches) and (matches[:, 0].max() >= len(descriptors[i])
                                            or matches[:, 1].max() >= len(descriptors[j]))):
                    raise RuntimeError('loop_matching_output_invalid')
                db.write_matches(first, second, matches)
        del features, matcher, descriptors
        torch.cuda.empty_cache()
        # Bind resection to the already validated camera calibration.
        for camera_id, calibration in anchor.cameras.items():
            camera = db.read_camera(camera_id)
            camera.params = calibration.params.copy()
            db.update_camera(camera)
    pair_file = folder / 'pairs.txt'
    pair_file.write_text(''.join(f'{images[i].name} {images[j].name}\n' for i, j in pairs), encoding='ascii')
    token, done = p.CancellationToken(), threading.Event()
    aborted = []

    def watch():
        deadline = time.monotonic() + 180
        while not done.wait(3):
            try:
                check()
                if time.monotonic() > deadline:
                    raise RuntimeError('loop_geometry_timeout')
            except RuntimeError as error:
                aborted.append(str(error))
                token.cancel()
                return

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        verify_pairs(database, pair_file, token)
        initial = folder / 'anchor'
        initial.mkdir()
        anchor.write(initial)
        options = p.IncrementalPipelineOptions(num_threads=4, random_seed=17, max_runtime_seconds=170,
            max_num_models=1, multiple_models=False, fix_existing_frames=True,
            constant_cameras=set(anchor.cameras), ba_refine_focal_length=False,
            ba_refine_extra_params=False, ba_refine_sensor_from_rig=False,
            structure_less_registration_fallback=False)
        options.mapper.abs_pose_refine_focal_length = False
        options.mapper.abs_pose_refine_extra_params = False
        models = p.incremental_mapping(database, prepared / 'images', folder / 'models',
                    options=options, input_path=initial, cancellation_token=token)
    finally:
        done.set()
        thread.join(5)
    if aborted:
        raise RuntimeError(aborted[0])
    candidate = max(models.values(), key=lambda model: model.num_reg_images()) if models else anchor
    preserved = all(i in candidate.images and np.allclose(candidate.images[i].cam_from_world().matrix(),
        anchor.images[i].cam_from_world().matrix(), rtol=1e-7, atol=1e-7) for i in anchor.reg_image_ids())
    condition = sparse_condition([image.cam_from_world().inverse().translation
        for image in candidate.images.values() if image.has_pose], [point.xyz for point in candidate.points3D.values()])
    error = candidate.compute_mean_reprojection_error()
    accepted = (candidate.num_reg_images() > anchor.num_reg_images() and preserved
                and condition['passed'] and math.isfinite(error) and error <= 3)
    report = dict(method='bounded-rootsift-bow128-and-missing-view-lightglue', pairs=len(pairs),
        quantized_descriptors=True, registered_before=anchor.num_reg_images(),
        registered_after=candidate.num_reg_images(), anchor_poses_preserved=preserved,
        conditioning=condition, accepted=accepted, mean_reprojection_px=error,
        network_downloads=False, source_rgb_modified=False)
    write_json(folder / 'report.json', report)
    feature_path = prepared / 'features.json'
    features = json.loads(feature_path.read_text('utf-8'))
    features['loop_completion'] = report
    write_json(feature_path, features)
    return candidate if accepted else anchor
