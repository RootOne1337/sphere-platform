"""Budgeted candidate retrieval for the controlled RGB vehicle pilot."""

import numpy as np

from motor_worker.route_xfeat import ReferenceLKXFeatLocalizer, XFEAT_POLICY, _XFeatMeasuredSolve


FAST_XFEAT_POLICY = XFEAT_POLICY + "_coarse_stride2"


class _CoarseSearch:
    def __init__(self, matcher):
        self.matcher = matcher

    def knnMatch(self, descriptors, *, k):
        # Descriptor rows are ordered by feature score. Interleave the sample
        # through the list and retain every descriptor for exact verification.
        return self.matcher.knnMatch(np.ascontiguousarray(descriptors[::2]), k=k)


class _FastMeasuredSolve(_XFeatMeasuredSolve):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search = _CoarseSearch(self.search)

    def _solve(self, *args):
        # Keep using measured 2D-to-3D correspondences while a strong anchor
        # is fresh. Weak or stalled flow still goes through full re-detection.
        if (self.confirmations >= 3 and self.anchor is not None and self.anchor_direct is not None
                and .65 < self.last_received - self.anchor_direct <= 1.05
                and 0 < self.last_received - self.anchor[-1] <= .22 and len(self.anchor[2]) >= 48):
            self.last_diagnostic["method"] = "xfeat_anchored_flow"
            solved = self._flow()
            if solved is not None and solved[2] >= 48:
                return solved
        return super()._solve(*args)


class FastReferenceLKXFeatLocalizer(ReferenceLKXFeatLocalizer, _FastMeasuredSolve):
    verification_policy = ReferenceLKXFeatLocalizer.verification_policy + ":coarse_stride2_fresh_anchor"
