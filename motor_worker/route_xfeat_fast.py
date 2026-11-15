"""Budgeted candidate retrieval for the controlled RGB vehicle pilot."""

from concurrent.futures import ThreadPoolExecutor, wait
import time

import numpy as np

from motor_worker.route_localization import inlier_spatial_support
from motor_worker.route_xfeat import ReferenceLKXFeatLocalizer, XFEAT_POLICY, _XFeatMeasuredSolve


FAST_XFEAT_POLICY = XFEAT_POLICY + "_coarse_stride2_parallel2_ap3p_budget"


class _CoarseSearch:
    def __init__(self, matcher):
        self.matcher = matcher

    def knnMatch(self, descriptors, *, k):
        # Descriptor rows are ordered by feature score. Interleave the sample
        # through the list and retain every descriptor for exact verification.
        return self.matcher.knnMatch(np.ascontiguousarray(descriptors[::2]), k=k)


class _FastMeasuredSolve(_XFeatMeasuredSolve):
    def __init__(self, *args, **kwargs):
        self._verification_pool = None
        self._ransac_trials = 120
        super().__init__(*args, **kwargs)
        self.search = _CoarseSearch(self.search)
        self._verification_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="route-pnp")

    def close(self):
        if self._verification_pool is not None:
            self._verification_pool.shutdown(wait=True, cancel_futures=True)
            self._verification_pool = None
        super().close()

    def _candidates_ranked(self):
        """Optional recovery can use the shortlist while verification runs."""

    def _verify_correspondences(self, world, image):
        # This live solver keeps the Reference-LK consensus and geometry checks.
        # With the required 50% inlier fraction, 120 four-point trials are
        # enough for >99.9% probability of drawing an all-inlier sample.
        if (len(world) < 24 or len(world) != len(image)
                or not np.isfinite(world).all() or not np.isfinite(image).all()):
            return None
        singular = np.linalg.svd(world - world.mean(axis=0), compute_uv=False)
        if singular[0] <= 0 or singular[2] / singular[0] < 1e-4:
            return None
        cv = self.cv
        ok, rvec, tvec, inliers = cv.solvePnPRansac(world, image, self.K, None,
            iterationsCount=self._ransac_trials, reprojectionError=3, confidence=.999, flags=cv.SOLVEPNP_AP3P)
        if not ok or inliers is None or len(inliers) < 20:
            return None
        keep = inliers[:, 0]
        rvec, tvec = cv.solvePnPRefineLM(world[keep], image[keep], self.K, None, rvec, tvec)
        rotation = cv.Rodrigues(rvec)[0]
        center = (-rotation.T @ tvec).reshape(3)
        projected = cv.projectPoints(world, rvec, tvec, self.K, None)[0].reshape(-1, 2)
        error = np.linalg.norm(projected - image, axis=1)
        depth = (world @ rotation.T + tvec.reshape(3))[:, 2]
        mask = (error <= 3) & (depth > 1e-5)
        count = int(mask.sum())
        if (not np.isfinite(center).all() or not np.isfinite(rotation).all() or count < 20
                or mask.mean() < .5 or not inlier_spatial_support(image[mask])):
            return None
        median = float(np.median(error[mask]))
        return (center, rotation, count, median, mask) if median <= 2. else None

    def _verify_ranked(self, ranked, pixels, descriptors):
        # Each lane uses the same frame and immutable map. Collect all its
        # witnesses before ranking; if any group misses the frame deadline,
        # never promote an incomplete set of competing poses.
        candidates = []
        for first in range(0, len(ranked), 2):
            if self.clock() - self.last_received > .25:
                break
            group = [self._verification_pool.submit(self._exact, *self.bank[index][1:], pixels, descriptors)
                     for index in ranked[first:first + 2]]
            wait(group)
            candidates.extend(row for task in group if (row := task.result()) is not None)
        return candidates

    def _solve(self, *_unused):
        self.current = None
        # Keep using measured 2D-to-3D correspondences while a strong anchor
        # is fresh. Weak or stalled flow still goes through full re-detection.
        if (self.confirmations >= 3 and self.anchor is not None and self.anchor_direct is not None
                and 0 < self.last_received - self.anchor[-1] <= .3):
            direct_age = self.last_received - self.anchor_direct
            strong = self.last_received - self.anchor[-1] <= .22 and len(self.anchor[2]) >= 48
            if direct_age <= .65 or direct_age <= 1.05 and strong:
                self.last_diagnostic["method"] = "xfeat_anchored_flow"
                flow = self._flow()
                if flow is not None and (direct_age <= .65 or flow[2] >= 48):
                    return flow

        began = time.perf_counter()
        pixels, descriptors = self.engine.query(self._gray, self.mask)
        diagnostic = self.last_diagnostic
        diagnostic.update(method="xfeat_measured", queryFeatures=len(pixels),
                          featureExtractionMs=(time.perf_counter() - began) * 1000)
        if len(descriptors) < 24:
            return None
        began = time.perf_counter()
        matches = np.fromiter((m.trainIdx for group in self.search.knnMatch(descriptors, k=8)
                               for m in group if m.distance < .72), np.int32)
        if not len(matches):
            return None
        votes = np.bincount(self.owners[matches], minlength=len(self.bank))
        ranked = [int(j) for j in np.argsort(-votes, kind="stable")[:8] if votes[j] >= 8]
        diagnostic["candidateReferenceIndices"] = [self.bank[j][0] for j in ranked]
        diagnostic["coarseSearchMs"] = (time.perf_counter() - began) * 1000
        if ranked:
            self._candidates_ranked()
        began = time.perf_counter()
        candidates = self._verify_ranked(ranked, pixels, descriptors)
        if not candidates and ranked and self.clock() - self.last_received < .165:
            # A clean but difficult view can still miss the small random
            # budget. Recheck the three strongest retrieval candidates if this
            # frame has time left; all candidates already had a first pass.
            self._ransac_trials = 300
            try:
                candidates = self._verify_ranked(ranked[:3], pixels, descriptors)
            finally:
                self._ransac_trials = 120
        diagnostic["verifiedCandidateCount"] = len(candidates)
        diagnostic["candidateMatchPnPMs"] = (time.perf_counter() - began) * 1000
        if self.clock() - self.last_received > .25 or not candidates:
            return None
        best = self._rank_proposals([row[0] for row in candidates])
        if best is not None:
            _, points, image = next(row for row in candidates if row[0] is best)
            self.current = points, image, True
        return best


class FastReferenceLKXFeatLocalizer(ReferenceLKXFeatLocalizer, _FastMeasuredSolve):
    verification_policy = ReferenceLKXFeatLocalizer.verification_policy + ":coarse_stride2_parallel2_ap3p_budget_fresh_anchor"
