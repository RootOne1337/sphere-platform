"""Budgeted candidate retrieval for the controlled RGB vehicle pilot."""

import numpy as np

from motor_worker.route_xfeat import ReferenceLKXFeatLocalizer, XFEAT_POLICY


FAST_XFEAT_POLICY = XFEAT_POLICY + "_coarse_stride2"


class _CoarseSearch:
    def __init__(self, matcher):
        self.matcher = matcher

    def knnMatch(self, descriptors, *, k):
        # Descriptor rows are ordered by feature score. Interleave the sample
        # through the list and retain every descriptor for exact verification.
        return self.matcher.knnMatch(np.ascontiguousarray(descriptors[::2]), k=k)


class FastReferenceLKXFeatLocalizer(ReferenceLKXFeatLocalizer):
    verification_policy = ReferenceLKXFeatLocalizer.verification_policy + ":coarse_stride2"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search = _CoarseSearch(self.search)
