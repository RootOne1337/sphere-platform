"""Experimental visual-place retrieval. Results are not poses or control permits.

The index is explicitly bounded and holds descriptors, not frames. Callers own
freshness, resource admission and sequence/episode validation. This module does
not assume that image similarity implies a traversable or metric route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaceResult:
    state: str
    reference: int | None
    inliers: int
    reason: str


@dataclass(frozen=True)
class PlaceCandidates:
    state: str
    candidates: tuple[PlaceResult, ...]
    reason: str


class VisualPlaceIndex:
    """Coarse grayscale retrieval followed by bounded ORB geometry verification."""

    def __init__(self, *, max_candidates: int = 8):
        import cv2 as cv
        import numpy as np

        if type(max_candidates) is not int or not 2 <= max_candidates <= 16:
            raise ValueError("invalid_place_candidate_limit")
        self.cv, self.np, self.max_candidates = cv, np, max_candidates
        self.detector = cv.ORB_create(nfeatures=2000, fastThreshold=9)
        self.mask = np.zeros((540, 960), np.uint8)
        self.mask[45:420, 15:945] = 255
        self.refs = []
        self.aspect = None

    def _features(self, rgb):
        cv, np = self.cv, self.np
        if (
            not isinstance(rgb, np.ndarray)
            or rgb.dtype != np.uint8
            or rgb.ndim != 3
            or rgb.shape[2] != 3
        ):
            raise ValueError("invalid_place_rgb")
        if not 16 <= rgb.shape[0] <= 2160 or not 16 <= rgb.shape[1] <= 3840:
            raise ValueError("invalid_place_rgb_size")
        if (
            self.aspect is not None
            and rgb.shape[1] * self.aspect[1] != rgb.shape[0] * self.aspect[0]
        ):
            raise ValueError("place_aspect_ratio_changed")
        gray = cv.cvtColor(
            cv.resize(rgb, (960, 540), interpolation=cv.INTER_AREA), cv.COLOR_RGB2GRAY
        )
        fingerprint = (
            cv.resize(gray[45:420, 15:945], (40, 20), interpolation=cv.INTER_AREA)
            .reshape(-1)
            .astype(np.float32)
        )
        fingerprint -= fingerprint.mean()
        fingerprint /= max(float(np.linalg.norm(fingerprint)), 1e-6)
        keypoints, descriptors = self.detector.detectAndCompute(gray, self.mask)
        return fingerprint, keypoints, descriptors

    def add(self, rgb, seconds: float):
        if (
            len(self.refs) >= 240
            or isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
            or self.refs
            and seconds <= self.refs[-1][0]
        ):
            raise ValueError("invalid_place_reference")
        fp, keypoints, descriptors = self._features(rgb)
        self.refs.append((float(seconds), fp, keypoints, descriptors))
        if self.aspect is None:
            self.aspect = (rgb.shape[1], rgb.shape[0])

    def compare_candidates(self, rgb, *, strategy="ranked") -> PlaceCandidates:
        """Return every supported top-K candidate, never a driving decision.

        Only the preselected candidates are assessed; absence from this tuple
        does not rule out similar views elsewhere in the route. No truncation of
        geometric proposals occurs here. Use <=8 preselected candidates when
        passing this output to GlobalRecovery.
        """
        if type(strategy) is not str or strategy not in {"ranked", "diverse"}:
            raise ValueError("invalid_place_selection_strategy")
        if not 2 <= len(self.refs) <= 240:
            raise ValueError("insufficient_place_references")
        cv, np = self.cv, self.np
        fp, keypoints, descriptors = self._features(rgb)
        if descriptors is None or len(descriptors) < 20:
            return PlaceCandidates("unknown", (), "insufficient_features")
        fingerprints = np.stack([ref[1] for ref in self.refs])
        ranked = np.argsort(fingerprints @ fp)[::-1]
        rank = select_place_candidates(
            tuple(int(i) for i in ranked),
            tuple(ref[0] for ref in self.refs),
            self.max_candidates,
            strategy=strategy,
        )
        matcher = cv.BFMatcher(cv.NORM_HAMMING)
        proposals = []
        for index in rank:
            seconds, _, ref_keypoints, ref_descriptors = self.refs[int(index)]
            if ref_descriptors is None or len(ref_descriptors) < 2:
                continue
            pairs = matcher.knnMatch(descriptors, ref_descriptors, k=2)
            good = [
                a
                for pair in pairs
                if len(pair) == 2
                for a, b in [pair]
                if a.distance < 0.75 * b.distance
            ]
            good = list(
                {
                    m.trainIdx: m for m in sorted(good, key=lambda m: m.distance, reverse=True)
                }.values()
            )
            if len(good) < 20:
                continue
            query = np.float32([keypoints[m.queryIdx].pt for m in good])
            reference = np.float32([ref_keypoints[m.trainIdx].pt for m in good])
            matrix, mask = cv.findHomography(query, reference, cv.RANSAC, 3.0)
            if matrix is None or mask is None or not np.isfinite(matrix).all():
                continue
            accepted = mask.ravel().astype(bool)
            count = int(accepted.sum())
            cells = [
                len({(int(x // 240), int(y // 180)) for x, y in points[accepted]})
                for points in (query, reference)
            ]
            corners = np.float32([[[0, 0], [960, 0], [960, 540], [0, 540]]])
            transformed = cv.perspectiveTransform(corners, matrix)[0]
            sane = (
                np.isfinite(transformed).all()
                and cv.isContourConvex(transformed)
                and 0.4 <= cv.contourArea(transformed, oriented=True) / (960 * 540) <= 2.5
            )
            if count >= 15 and count / len(good) >= 0.4 and min(cells) >= 4 and sane:
                proposals.append((count, int(index), seconds))
        if not proposals:
            return PlaceCandidates("unknown", (), "no_geometric_match")
        proposals.sort(reverse=True)
        results = tuple(
            PlaceResult("matched", index, count, "image_resemblance_not_pose")
            for count, index, _ in proposals
        )
        return PlaceCandidates("candidates", results, "top_k_geometric_hypotheses_not_exhaustive")

    def compare(self, rgb) -> PlaceResult:
        evaluated = self.compare_candidates(rgb)
        if not evaluated.candidates:
            return PlaceResult("unknown", None, 0, evaluated.reason)
        first = evaluated.candidates[0]
        seconds = self.refs[first.reference][0]
        if any(
            other.inliers >= 0.75 * first.inliers
            and abs(self.refs[other.reference][0] - seconds) > 2
            for other in evaluated.candidates[1:]
        ):
            return PlaceResult("ambiguous", None, first.inliers, "similar_distant_views")
        return first


def select_place_candidates(ranked, seconds, limit, *, strategy="ranked"):
    """Bounded candidate-selection experiment; does not validate match quality.

    'diverse' keeps half of slots for the best scores and seeks temporally
    separated reference views for the rest, then fills unused slots by score.
    Recorded-media seconds are not physical distance or map connectivity.
    """
    if (
        type(ranked) is not tuple
        or type(seconds) is not tuple
        or len(ranked) != len(seconds)
        or not 2 <= len(ranked) <= 240
        or type(limit) is not int
        or not 2 <= limit <= 16
        or type(strategy) is not str
        or strategy not in {"ranked", "diverse"}
        or any(type(i) is not int or not 0 <= i < len(seconds) for i in ranked)
        or len(set(ranked)) != len(ranked)
        or any(
            isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0
            for t in seconds
        )
        or any(a >= b for a, b in zip(seconds, seconds[1:]))
    ):
        raise ValueError("invalid_place_candidate_selection")
    target = min(limit, len(ranked))
    if strategy == "ranked":
        return ranked[:target]
    selected = list(ranked[: max(1, target // 2)])
    for index in ranked:
        if len(selected) >= target:
            break
        if index not in selected and all(
            abs(seconds[index] - seconds[other]) > 2.0 for other in selected
        ):
            selected.append(index)
    for index in ranked:
        if len(selected) >= target:
            break
        if index not in selected:
            selected.append(index)
    return tuple(selected)
