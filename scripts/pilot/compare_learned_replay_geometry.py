"""Offline learned-match evaluation against the bound measured-reference cache.

This reports geometric evidence only: it does not perform temporal admission,
freshness checks, localization confirmation, or control.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from motor_worker.route_localization import SIZE


def compare_candidates(localizer, candidates, *, merge_covisible=False):
    """Verify and rank candidate matches using the localizer's existing gates.

    Each candidate is a mapping with ``reference_index``, ``query_xy`` (Nx2
    pixels in the 960x540 query), and ``reference_indices`` (N integer indices
    relative to that reference's complete measured cache slice). Duplicate
    indices, landmark IDs or query positions are rejected, as are malformed or
    masked coordinates. The bound cache supplies all 3D points; callers cannot
    supply or remap world coordinates. The result is JSON serializable.

    Ranking uses the localizer's current state, including its existing motion
    disambiguation if applicable. Neither the cache nor tracker state is changed.
    """
    arrays = localizer._cache.arrays
    mask, offsets = arrays["mask"], arrays["offsets"]
    reports, proposals, measured = [], [], {}
    seen_refs = set()
    for candidate in candidates:
        report = {
            "reference_index": None,
            "status": "invalid_input",
            "matches": 0,
            "inliers": 0,
            "median_error_px": None,
        }
        reports.append(report)
        if not isinstance(candidate, dict):
            continue
        ref = candidate.get("reference_index")
        if isinstance(ref, (bool, np.bool_)) or not isinstance(ref, (int, np.integer)):
            continue
        ref = int(ref)
        report["reference_index"] = ref
        if ref < 0 or ref >= len(offsets) - 1 or ref in seen_refs:
            continue
        seen_refs.add(ref)
        try:
            xy = np.asarray(candidate["query_xy"], dtype=np.float64)
            indices = np.asarray(candidate["reference_indices"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (
            xy.ndim != 2
            or xy.shape[1] != 2
            or indices.ndim != 1
            or len(xy) != len(indices)
            or indices.dtype.kind not in "iu"
            or not np.isfinite(xy).all()
        ):
            continue
        start, end = map(int, offsets[ref : ref + 2])
        if (
            np.any(indices >= end - start)
            or np.any(indices < 0)
            or len(np.unique(indices)) != len(indices)
            or len(np.unique(xy, axis=0)) != len(xy)
        ):
            continue
        absolute = start + indices.astype(np.int64)
        if len(np.unique(arrays["native_ids"][absolute])) != len(absolute):
            continue
        ref_xy = arrays["pixels"][absolute]
        world = arrays["xyz"][absolute]
        if (
            not np.isfinite(ref_xy).all()
            or not np.isfinite(world).all()
            or np.any(xy < 0)
            or np.any(xy >= SIZE)
            or np.any(ref_xy < 0)
            or np.any(ref_xy >= SIZE)
        ):
            continue
        # Match the runtime's rounded-pixel mask rule, including edge clipping.
        query_pixel = np.minimum(np.rint(xy).astype(np.int64), np.array(SIZE) - 1)
        ref_pixel = np.minimum(np.rint(ref_xy).astype(np.int64), np.array(SIZE) - 1)
        if np.any(mask[query_pixel[:, 1], query_pixel[:, 0]] == 0) or np.any(
            mask[ref_pixel[:, 1], ref_pixel[:, 0]] == 0
        ):
            report["status"] = "masked_coordinate"
            continue
        report["matches"] = len(xy)
        if merge_covisible:
            measured[ref] = (absolute, xy)
        if len(xy) < 24:
            report["status"] = "insufficient_correspondences"
            continue
        verified = localizer._verify_correspondences(world, xy)
        if verified is None:
            report["status"] = "geometry_rejected"
            continue
        report.update(
            status="verified", inliers=int(verified[2]), median_error_px=float(verified[3])
        )
        proposals.append((verified[:4], report))

    if merge_covisible and len(measured) > 1:
        merged = merge_candidate_observations(arrays, measured)
        for refs, world, xy in merged:
            report = {
                "reference_index": refs[0],
                "merged_reference_indices": refs,
                "status": "insufficient_correspondences",
                "matches": len(xy),
                "inliers": 0,
                "median_error_px": None,
            }
            reports.append(report)
            if len(xy) < 24:
                continue
            verified = localizer._verify_correspondences(world, xy)
            if verified is None:
                report["status"] = "geometry_rejected"
                continue
            report.update(
                status="verified", inliers=int(verified[2]), median_error_px=float(verified[3])
            )
            proposals.append((verified[:4], report))
    if not proposals:
        rank_status, winner = "no_verified_candidates", None
    else:
        diagnostic = localizer.last_diagnostic.copy()
        try:
            ranked = localizer._rank_proposals([proposal for proposal, _ in proposals])
        finally:
            localizer.last_diagnostic.clear()
            localizer.last_diagnostic.update(diagnostic)
        if ranked is None:
            rank_status, winner = "ambiguous", None
        else:
            rank_status = "winner"
            winner = next(
                report["reference_index"] for proposal, report in proposals if proposal is ranked
            )
    return {"candidates": reports, "rank_status": rank_status, "winner_reference_index": winner}


def merge_candidate_observations(arrays, measured):
    """Fuse covisible views while discarding conflicting 2D or 3D associations."""
    offsets, native_ids = arrays["offsets"], arrays["native_ids"]
    visibility = {ref: set(native_ids[offsets[ref] : offsets[ref + 1]]) for ref in measured}
    groups = []
    for ref in measured:
        # Require shared measured 3D landmarks, even for adjacent video times.
        connected = [
            i
            for i, group in enumerate(groups)
            if any(len(visibility[ref] & visibility[peer]) >= 24 for peer in group)
        ]
        if not connected:
            groups.append([ref])
            continue
        first, *others = connected
        for i in reversed(others):
            groups[first].extend(groups.pop(i))
        groups[first].append(ref)
    for group in groups:
        if len(group) < 2:
            continue
        by_landmark, by_pixel = defaultdict(dict), defaultdict(set)
        for ref in group:
            indices, pixels = measured[ref]
            for index, pixel in zip(indices, pixels):
                landmark = int(native_ids[index])
                pixel = tuple(pixel)
                by_landmark[landmark][pixel] = int(index)
                by_pixel[pixel].add(landmark)
        unique = [
            (index, pixel)
            for observations in by_landmark.values()
            if len(observations) == 1
            for pixel, index in observations.items()
            if len(by_pixel[pixel]) == 1
        ]
        indices = np.fromiter((index for index, _ in unique), dtype=np.int64)
        xy = np.asarray([pixel for _, pixel in unique], dtype=np.float64).reshape(-1, 2)
        yield [ref for ref in measured if ref in group], arrays["xyz"][indices], xy
