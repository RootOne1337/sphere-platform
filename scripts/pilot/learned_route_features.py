"""Offline pinned LightGlue matching for recorded-route reconstruction.

No downloads, Android authority or global package changes. Classical features
and learned correspondence prediction remain distinct from scene training.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import time

SOURCE = 'eb42fee2d71449efb0aa5c10549752b5d75384d8'
WEIGHTS = '5b52b8d9982d43532dc042606b346bb9594c9f5a4bd6f64362c63866287b4ac0'


def paths(root):
    tools = root / '.local-pilot/reconstruction-tools'
    return (tools / 'lightglue', tools / 'lightglue-models/hub/checkpoints/sift_lightglue_v0-1_arxiv.pth')


def available(root):
    source, weights = paths(root)
    return (source / 'lightglue/lightglue.py').is_file() and weights.is_file()


def validate_assets(root):
    source, weights = paths(root)
    if weights.is_symlink() or not weights.is_file() or weights.stat().st_size != 47632573:
        raise RuntimeError('lightglue_weights_mismatch')
    with weights.open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != WEIGHTS:
            raise RuntimeError('lightglue_weights_mismatch')
    command = ['git', '-C', str(source)]
    if (subprocess.check_output([*command, 'rev-parse', 'HEAD'], text=True, timeout=10).strip() != SOURCE
            or subprocess.check_output([*command, 'diff', '--name-only'], text=True, timeout=10).strip()):
        raise RuntimeError('lightglue_source_mismatch')
    return source, weights


def verify_pairs(database, pair_file, token):
    import pycolmap as p

    options = p.TwoViewGeometryOptions()
    # COLMAP already parallelizes pairs; nested RANSAC parallelism is refused.
    options.ransac.num_threads = 1
    p.verify_matches(database, pair_file, options=options, cancellation_token=token)


def load_matcher(root, memory_fraction=.65):
    """Load the locally verified weights, never the upstream download path."""
    source, weights = validate_assets(root)
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError('lightglue_gpu_unavailable')
    torch.set_num_threads(4)
    torch.manual_seed(17)
    torch.cuda.set_per_process_memory_fraction(memory_fraction)
    spec = importlib.util.spec_from_file_location('_sphere_pinned_lightglue', source / 'lightglue/lightglue.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Construct without the upstream automatic weight download path.
    matcher = module.LightGlue(features=None, input_dim=128, add_scale_ori=True, filter_threshold=.2).eval()
    state = torch.load(weights, map_location='cpu', weights_only=True)
    for i in range(9):
        state = {key.replace(f'self_attn.{i}', f'transformers.{i}.self_attn')
                 .replace(f'cross_attn.{i}', f'transformers.{i}.cross_attn'): value for key, value in state.items()}
    state.setdefault('confidence_thresholds', matcher.confidence_thresholds)
    matcher.load_state_dict(state, strict=True)
    matcher.to('cuda')
    return matcher


def extract_and_match(root, prepared, database, reader, token, check, *, progress=None):
    import cv2
    import numpy as np
    import pycolmap as p
    import torch

    matcher = load_matcher(root)
    cv2.setNumThreads(4)
    p.Database.open(database).close()
    p.import_images(database, prepared / 'images', camera_mode=p.CameraMode.SINGLE, options=reader)
    sift = cv2.SIFT_create(nfeatures=4096, contrastThreshold=.0066667, edgeThreshold=10)
    features, ids, names = {}, [], {}
    started, observed = time.monotonic(), 0.
    stage, processed, total = 'features', 0, 0

    def bounded():
        nonlocal observed
        if time.monotonic() - started > 800:
            raise RuntimeError('learned_matching_timeout')
        if time.monotonic() - observed >= 3:
            check()
            if progress is not None:
                progress(stage,processed,total)
            observed = time.monotonic()

    with p.Database.open(database) as db:
        images = sorted(db.read_all_images(), key=lambda image: image.name)
        if not 10 <= len(images) <= 240:
            raise RuntimeError('learned_matching_view_budget')
        total=len(images)
        for image in images:
            bounded()
            gray = cv2.imread(str(prepared / 'images' / image.name), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                raise RuntimeError('learned_matching_image_invalid')
            height, width = gray.shape
            mask_path = prepared / 'masks' / (image.name + '.png')
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE) if mask_path.is_file() else np.full_like(gray, 255)
            if mask is None or mask.shape != gray.shape:
                raise RuntimeError('learned_matching_mask_invalid')
            # Conservative burn-in footer exclusion, not semantic NPC removal.
            mask[int(height * .975):] = 0
            keypoints, descriptors = sift.detectAndCompute(gray, mask)
            if descriptors is None or len(keypoints) < 15:
                raise RuntimeError('learned_matching_insufficient_features')
            if len(keypoints) > 4096:
                strongest = sorted(range(len(keypoints)), key=lambda i: (-keypoints[i].response, i))[:4096]
                keypoints, descriptors = [keypoints[i] for i in strongest], descriptors[strongest]
            xy = np.asarray([point.pt for point in keypoints], dtype='float32') + .5
            scales = np.asarray([point.size for point in keypoints], dtype='float32')
            angles = np.deg2rad(np.asarray([point.angle for point in keypoints], dtype='float32'))
            descriptors /= np.maximum(descriptors.sum(-1, keepdims=True), 1e-6)
            descriptors = np.sqrt(np.maximum(descriptors, 1e-6))
            descriptors /= np.maximum(np.linalg.norm(descriptors, axis=-1, keepdims=True), 1e-6)
            db.write_keypoints(image.image_id, np.column_stack([xy, scales, angles]))
            db.write_descriptors(image.image_id, p.FeatureDescriptors(p.FeatureExtractorType.SIFT,
                np.clip(np.round(descriptors * 512), 0, 255).astype('uint8')))
            data = dict(keypoints=xy, scales=scales, oris=angles, descriptors=descriptors,
                        image_size=np.array([width, height], dtype='float32'))
            features[image.image_id] = {key: torch.from_numpy(value)[None].to('cuda') for key, value in data.items()}
            ids.append(image.image_id)
            names[image.image_id] = image.name
            processed+=1
        pairs, counts = [], []
        stage,processed,total='matching',0,sum(i+lag<len(ids) for i in range(len(ids)) for lag in (1,2,3,5,8))
        if progress is not None:
            progress(stage,processed,total)
        with torch.inference_mode():
            for i, first in enumerate(ids):
                for lag in (1, 2, 3, 5, 8):
                    if i + lag >= len(ids):
                        continue
                    bounded()
                    second = ids[i + lag]
                    output = matcher(dict(image0=features[first], image1=features[second]))
                    matches = output['matches'][0].cpu().numpy().astype('uint32')
                    if (matches.ndim != 2 or matches.shape[1] != 2 or len(matches) > 4096
                            or len(matches) and (matches[:, 0].max() >= features[first]['keypoints'].shape[1]
                                                or matches[:, 1].max() >= features[second]['keypoints'].shape[1])):
                        raise RuntimeError('learned_matching_output_invalid')
                    db.write_matches(first, second, matches)
                    pairs.append(f'{names[first]} {names[second]}')
                    counts.append(len(matches))
                    processed+=1
        del features, matcher
        torch.cuda.empty_cache()
    pair_file = prepared / 'learned-pairs.txt'
    pair_file.write_text('\n'.join(pairs) + '\n', encoding='ascii')
    report = dict(method='opencv-rootsift-lightglue', lightglue_source=SOURCE, weights_sha256=WEIGHTS,
                  opencv=cv2.__version__, torch=torch.__version__, views=len(images), pairs=len(pairs),
                  median_raw_matches=float(np.median(counts)), max_features=4096, gpu_memory_fraction=.65,
                  footer_exclusion_fraction=.025, semantic_dynamic_mask=False, network_downloads=False)
    report['geometric_verification_complete'] = False
    (prepared / 'features.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    bounded()
    verify_pairs(database, pair_file, token)
    report['geometric_verification_complete'] = True
    (prepared / 'features.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
