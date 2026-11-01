"""Offline measured RootSIFT tracks gated by already frozen camera geometry.

No camera, intrinsic, source pixel or threshold is fitted here. The caller owns
the CPU/process resource guard and must supply the same source-bound runtime
features as the canonical exporter. This module has no IO or device authority.
"""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict

MAX_VIEWS = 256
MAX_FEATURES_PER_VIEW = 4096
MAX_OBSERVATIONS = 1_048_576
MAX_VIEW_LAG = 8
DESCRIPTOR_CANDIDATES = 8
MAX_PAIR_QUERIES = 8_388_608
MAX_DESCRIPTOR_PROPOSALS = MAX_PAIR_QUERIES * DESCRIPTOR_CANDIDATES
MAX_MATCH_EDGES = 1_000_000
MAX_PROVENANCE_OBSERVATIONS = 100_000
MAX_BUILD_SECONDS = 90.0
SIZE = (960, 540)
MAX_SAMPSON_PX = 2.0
DESCRIPTOR_RATIO = 0.75
MAX_DESCRIPTOR_DISTANCE = 0.7


def _fundamental(first, second, inverse_k, minimum_baseline):
    """Known cam_from_world -> F; a zero baseline never invents an epipolar line."""
    import numpy as np

    r1, r2 = first[:, :3], second[:, :3]
    c1, c2 = -r1.T @ first[:, 3], -r2.T @ second[:, 3]
    translation = r2 @ (c1 - c2)
    length = float(np.linalg.norm(translation))
    if not math.isfinite(length) or length <= minimum_baseline:
        return None
    x, y, z = translation / length
    skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    fundamental = inverse_k.T @ skew @ (r2 @ r1.T) @ inverse_k
    magnitude = float(np.max(np.abs(fundamental)))
    if not math.isfinite(magnitude) or magnitude <= 0:
        return None
    fundamental /= magnitude
    return fundamental / np.linalg.norm(fundamental)


def _sampson(first, second, fundamental):
    """Pixel Sampson distance, scale invariant; degenerate denominators refuse."""
    import numpy as np

    first, second = np.asarray(first, np.float64), np.asarray(second, np.float64)
    f = np.asarray(fundamental, np.float64)
    if (
        first.shape != second.shape
        or first.ndim != 2
        or first.shape[1] != 2
        or f.shape != (3, 3)
        or not np.isfinite(f).all()
    ):
        raise ValueError("guided_landmark_epipolar_input")
    result = np.full(len(first), np.inf)
    magnitude = float(np.max(np.abs(f)))
    if magnitude <= 0:
        return result
    f = f / magnitude
    f /= np.linalg.norm(f)
    a = np.column_stack((first, np.ones(len(first))))
    b = np.column_stack((second, np.ones(len(second))))
    line_b, line_a = a @ f.T, b @ f
    numerator = np.sum(b * line_b, axis=1)
    denominator = np.sum(line_b[:, :2] ** 2 + line_a[:, :2] ** 2, axis=1)
    valid = (
        np.isfinite(numerator)
        & np.isfinite(denominator)
        & (denominator > 1e-18)
        & np.isfinite(first).all(axis=1)
        & np.isfinite(second).all(axis=1)
    )
    result[valid] = np.abs(numerator[valid]) / np.sqrt(denominator[valid])
    return result


def _directed(pixels_a, descriptors_a, pixels_b, descriptors_b, fundamental, *, checkpoint, counts):
    import cv2 as cv
    import numpy as np

    if len(pixels_b) < 2 or not len(pixels_a):
        return {}
    counts["descriptor_queries"] += len(pixels_a)
    if counts["descriptor_queries"] > MAX_PAIR_QUERIES:
        raise ValueError("guided_landmark_pair_query_quota")
    checkpoint()
    rows = cv.BFMatcher(cv.NORM_L2).knnMatch(
        descriptors_a, descriptors_b, k=min(DESCRIPTOR_CANDIDATES, len(pixels_b))
    )
    selected = {}
    for start in range(0, len(rows), 256):
        checkpoint()
        chunk = rows[start : start + 256]
        size = sum(len(row) for row in chunk)
        counts["descriptor_proposals"] += size
        if counts["descriptor_proposals"] > MAX_DESCRIPTOR_PROPOSALS:
            raise ValueError("guided_landmark_descriptor_proposal_quota")
        if not size:
            continue
        query_ids = np.repeat(np.arange(start, start + len(chunk)), [len(row) for row in chunk])
        train_ids = np.fromiter((m.trainIdx for row in chunk for m in row), np.int64, count=size)
        errors = _sampson(pixels_a[query_ids], pixels_b[train_ids], fundamental)
        offset = 0
        for index, row in enumerate(chunk, start):
            row_errors = errors[offset : offset + len(row)]
            offset += len(row)
            candidates = sorted(
                (
                    (m.distance, m.trainIdx, float(error))
                    for m, error in zip(row, row_errors)
                    if math.isfinite(m.distance) and error <= MAX_SAMPSON_PX
                ),
                key=lambda item: (item[0], item[1]),
            )
            counts["epipolar_rejected_proposals"] += len(row) - len(candidates)
            if len(candidates) < 2:
                counts["fewer_than_two_epipolar_candidates"] += 1
                continue
            first, second = candidates[:2]
            if first[0] < DESCRIPTOR_RATIO * second[0] and first[0] < MAX_DESCRIPTOR_DISTANCE:
                selected[index] = (first[1], first[0], first[2])
            else:
                counts["descriptor_rejected_queries"] += 1
    return selected


def _tracks(edges, *, checkpoint):
    """Deterministic forest: two different detections of one image never merge."""
    parents, views = {}, {}

    def find(node):
        if node not in parents:
            parents[node], views[node] = node, {node[0]}
        root = node
        while parents[root] != root:
            root = parents[root]
        while parents[node] != root:
            previous = parents[node]
            parents[node] = root
            node = previous
        return root

    conflicts, cycles, merged = 0, 0, 0
    for index, (_, _, a, i, b, j) in enumerate(sorted(edges)):
        if index % 1024 == 0:
            checkpoint()
        left, right = find((a, i)), find((b, j))
        if left == right:
            cycles += 1
            continue
        if views[left] & views[right]:
            conflicts += 1
            continue
        if (len(views[left]), left) < (len(views[right]), right):
            left, right = right, left
        parents[right] = left
        views[left].update(views.pop(right))
        merged += 1
    components = defaultdict(list)
    for index, node in enumerate(parents):
        if index % 4096 == 0:
            checkpoint()
        components[find(node)].append(node)
    return sorted(
        (sorted(track) for track in components.values()),
        key=lambda track: (-len(track), tuple(track)),
    ), dict(conflict_edges_rejected=conflicts, redundant_cycle_edges=cycles, forest_edges=merged)


def build(observations, matrices, K, *, checkpoint, provenance=None):
    """Compatible candidate rows; optional provenance is a separate caller list.

    Lag 1..8 and all gates are fixed. Timestamps/labels do not rank matches.
    The report stays compact; an optional empty provenance list is populated
    only on successful completion. No partial candidates are returned on error.
    """
    import numpy as np

    from scripts.pilot.route_landmark_builder import triangulate

    began = time.monotonic()

    def bounded():
        if time.monotonic() - began > MAX_BUILD_SECONDS:
            raise ValueError("guided_landmark_time_quota")
        checkpoint()

    bounded()
    if (
        not 3 <= len(observations) <= MAX_VIEWS
        or len(matrices) != len(observations)
        or provenance is not None
        and (type(provenance) is not list or provenance)
    ):
        raise ValueError("guided_landmark_input_quota")
    k = np.asarray(K, dtype=np.float64)
    if (
        k.shape != (3, 3)
        or not np.isfinite(k).all()
        or (np.abs(k) > 1e8).any()
        or k[0, 0] <= 0
        or k[1, 1] <= 0
        or not np.allclose(k[2], [0, 0, 1], rtol=0, atol=1e-12)
        or abs(float(np.linalg.det(k))) < 1e-12
    ):
        raise ValueError("guided_landmark_intrinsics")
    inverse_k = np.linalg.inv(k)
    poses, pixels, descriptors, centers = [], [], [], []
    observation_count = 0
    for view, (observed, matrix) in enumerate(zip(observations, matrices)):
        bounded()
        pose = np.asarray(matrix, np.float64)
        if (
            pose.shape != (3, 4)
            or not np.isfinite(pose).all()
            or (np.abs(pose) > 1e8).any()
            or not np.allclose(pose[:, :3] @ pose[:, :3].T, np.eye(3), rtol=0, atol=1e-6)
            or abs(float(np.linalg.det(pose[:, :3])) - 1) > 1e-6
        ):
            raise ValueError("guided_landmark_pose")
        xy, desc = (np.asarray(v) for v in observed)
        observation_count += len(xy) if xy.ndim else MAX_OBSERVATIONS + 1
        if observation_count > MAX_OBSERVATIONS:
            raise ValueError("guided_landmark_observation_quota")
        if (
            xy.ndim != 2
            or xy.shape[1] != 2
            or desc.shape != (len(xy), 128)
            or len(xy) > MAX_FEATURES_PER_VIEW
            or xy.dtype.kind != "f"
            or desc.dtype.kind != "f"
            or not np.isfinite(xy).all()
            or not np.isfinite(desc).all()
            or (xy < 0).any()
            or (xy[:, 0] >= SIZE[0]).any()
            or (xy[:, 1] >= SIZE[1]).any()
            or (desc < 0).any()
            or (desc > 1.0001).any()
            or (np.abs(np.linalg.norm(desc, axis=1) - 1) > 0.001).any()
        ):
            raise ValueError("guided_landmark_features")
        poses.append(pose)
        centers.append(-pose[:, :3].T @ pose[:, 3])
        pixels.append(xy.astype(np.float64, copy=False))
        descriptors.append(desc.astype(np.float32, copy=False))
    extent = max(float(np.linalg.norm(c - centers[0])) for c in centers)
    magnitude = max(float(np.linalg.norm(c)) for c in centers)
    baseline_floor = max(1e-12, extent * 1e-10, magnitude * np.finfo(np.float64).eps * 64)
    counts = Counter()
    edges = []
    for a in range(len(observations)):
        for b in range(a + 1, min(a + MAX_VIEW_LAG + 1, len(observations))):
            bounded()
            counts["reference_pairs"] += 1
            f = _fundamental(poses[a], poses[b], inverse_k, baseline_floor)
            if f is None:
                counts["zero_or_tiny_baseline_pairs_skipped"] += 1
                continue
            forward = _directed(
                pixels[a],
                descriptors[a],
                pixels[b],
                descriptors[b],
                f,
                checkpoint=bounded,
                counts=counts,
            )
            reverse = _directed(
                pixels[b],
                descriptors[b],
                pixels[a],
                descriptors[a],
                f.T,
                checkpoint=bounded,
                counts=counts,
            )
            for i, (j, distance, error) in forward.items():
                if j not in reverse or reverse[j][0] != i:
                    counts["nonreciprocal_matches_rejected"] += 1
                    continue
                if len(edges) >= MAX_MATCH_EDGES:
                    raise ValueError("guided_landmark_edge_quota")
                edges.append((max(distance, reverse[j][1]), max(error, reverse[j][2]), a, i, b, j))
    tracks, forest = _tracks(edges, checkpoint=bounded)
    candidates, proofs, rejected = [], [], Counter()
    proof_observations = 0
    for index, track in enumerate(tracks):
        if index % 64 == 0:
            bounded()
        if len(track) < 3:
            rejected["fewer_than_3_observations"] += 1
            continue
        if len({view for view, _ in track}) != len(track):
            raise ValueError("guided_landmark_internal_track_conflict")
        xyz = triangulate(track, pixels, poses, k, rejected=rejected)
        if xyz is None:
            continue
        samples = np.asarray([descriptors[view][feature] for view, feature in track], np.float64)
        norms = np.sum(samples * samples, axis=1)
        distances = np.sqrt(
            np.maximum(0, norms[:, None] + norms[None, :] - 2 * samples @ samples.T)
        )
        medoid = int(np.argmin(distances.sum(axis=1)))
        candidates.append(
            (
                len(track),
                tuple(float(v) for v in xyz),
                descriptors[track[medoid][0]][track[medoid][1]].copy(),
                tuple(view for view, _ in track),
            )
        )
        if provenance is not None:
            proof_observations += len(track)
            if proof_observations > MAX_PROVENANCE_OBSERVATIONS:
                raise ValueError("guided_landmark_provenance_quota")
            proofs.append(
                dict(
                    candidate_index=len(candidates) - 1,
                    observations=[list(node) for node in track],
                    medoid_observation=list(track[medoid]),
                )
            )
    support = Counter(view for row in candidates for view in row[3])
    bounded()
    report = dict(
        schema="sphere-guided-runtime-landmark-build-v1",
        method="known-pose-sampson-rootsift-conflict-free-v1",
        tracks=len(tracks),
        accepted=len(candidates),
        rejected=len(tracks) - len(candidates),
        rejection_reasons=dict(rejected),
        matching=dict(counts),
        forest=forest,
        reference_views=len(observations),
        runtime_observations=observation_count,
        candidate_support_per_view=[support[i] for i in range(len(observations))],
        max_view_lag=MAX_VIEW_LAG,
        descriptor_candidates=DESCRIPTOR_CANDIDATES,
        descriptor_ratio=DESCRIPTOR_RATIO,
        max_descriptor_distance=MAX_DESCRIPTOR_DISTANCE,
        max_sampson_px=MAX_SAMPSON_PX,
        min_views=3,
        max_error_px=3,
        min_parallax_degrees=1,
        zero_baseline_floor_units=baseline_floor,
        camera_poses_modified=False,
        intrinsics_modified=False,
        runtime_features_rebuilt=False,
        triangulation_performed=True,
        source_times_used_for_matching=False,
        pixel_coordinates="opencv_integer_centers_v1",
        provenance_returned_separately=provenance is not None,
        execution_qualified=False,
    )
    if provenance is not None:
        provenance.extend(proofs)
    return candidates, report
