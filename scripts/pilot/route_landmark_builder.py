"""Triangulate runtime-resolution features using explicitly supplied camera poses.

This does not repair/qualify the camera model. At least three different images,
positive depth, parallax and reprojection consistency are required per landmark.
No input journal, game coordinates or keyboard replay is consumed.
"""

from __future__ import annotations

from collections import defaultdict


def triangulate(observations, pixels, matrices, K):
    import numpy as np

    rows, centers = [], []
    inverse = np.linalg.inv(K)
    for image, index in observations:
        ext = matrices[image]
        ray = inverse @ np.r_[pixels[image][index], 1.]
        rows.extend([ray[0]*ext[2]-ext[0], ray[1]*ext[2]-ext[1]])
        centers.append(-ext[:, :3].T @ ext[:, 3])
    _, _, vh = np.linalg.svd(rows, full_matrices=False)
    if abs(vh[-1, 3]) < 1e-8:
        return None
    xyz = vh[-1, :3]/vh[-1, 3]
    if not np.isfinite(xyz).all():
        return None
    for image, index in observations:
        camera = matrices[image][:, :3]@xyz+matrices[image][:, 3]
        projected = K@camera
        if camera[2] <= 1e-5 or np.linalg.norm(projected[:2]/projected[2]-pixels[image][index]) > 3:
            return None
    rays = xyz-np.asarray(centers)
    rays /= np.maximum(np.linalg.norm(rays, axis=1, keepdims=True), 1e-8)
    if np.min(rays@rays.T) > np.cos(np.deg2rad(1.)):
        return None
    return xyz


def build(observations, matrices, K, *, checkpoint):
    """Adjacent feature tracks; bounded to the caller's <=256-view submap."""
    import cv2 as cv
    import numpy as np

    parents = {}

    def find(key):
        root = key
        while parents.setdefault(root, root) != root:
            root = parents[root]
        while key != root:
            parent = parents[key]
            parents[key] = root
            key = parent
        return root

    for first in range(len(observations)):
        if first % 8 == 0:
            checkpoint()
        a = observations[first][1]
        for second in range(first+1, min(first+4, len(observations))):
            b = observations[second][1]
            if min(len(a), len(b)) < 2:
                continue
            matcher = cv.BFMatcher(cv.NORM_L2)
            pairs = matcher.knnMatch(a, b, k=2)
            reverse = matcher.match(b, a)
            for pair in pairs:
                if len(pair) != 2:
                    continue
                m, n = pair
                if m.distance < .75*n.distance and m.distance < .7 and reverse[m.trainIdx].trainIdx == m.queryIdx:
                    first_key, second_key = (first, m.queryIdx), (second, m.trainIdx)
                    parents[find(second_key)] = find(first_key)
    tracks = defaultdict(list)
    for key in parents:
        tracks[find(key)].append(key)
    pixels = [v[0] for v in observations]
    valid, rejected = [], 0
    for track in tracks.values():
        if len(track) < 3 or len({image for image, _ in track}) != len(track):
            rejected += 1
            continue
        xyz = triangulate(track, pixels, matrices, K)
        if xyz is None:
            rejected += 1
            continue
        samples = np.stack([observations[image][1][index] for image, index in track])
        medoid = int(np.argmin(np.linalg.norm(samples[:, None]-samples[None, :], axis=2).sum(axis=1)))
        valid.append((len(track), tuple(float(v) for v in xyz), samples[medoid], tuple(sorted(image for image, _ in track))))
    valid.sort(key=lambda row: -row[0])
    return valid, dict(tracks=len(tracks), accepted=len(valid), rejected=rejected,
                      min_views=3, max_error_px=3, min_parallax_degrees=1, runtime_features_rebuilt=True)
