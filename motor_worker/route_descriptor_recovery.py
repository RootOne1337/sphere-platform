"""Native descriptor recovery for an already bound measured Reference-LK route."""

import time

from motor_worker.protocol import ProtocolError
from motor_worker.route_confirmation import _BoundedConfirmationMixin
from motor_worker.route_localization import (
    NATIVE_REFERENCE_FAMILY,
    RouteLocalizer,
    SparseRoute,
    extract_gray_features,
    feature_mask,
    map_support,
    native_reference_pipeline_id,
)
from motor_worker.route_reference_lk import ReferenceLKLocalizer, ReferenceLKRoute


DESCRIPTOR_RECOVERY_POLICY = "lk_zero_geometry_rootsift_recovery_150ms_v1"
_MAX_FRAME_AGE_SECONDS = 0.250
_DESCRIPTOR_START_RESERVE_SECONDS = 0.150


def _validate_sidecar(route, sidecar):
    # The caller admits source and descriptor provenance from the receipts.
    # These checks bind the loaded arrays to the owner's actual coordinate
    # system and normalized view, including legacy full-resolution profiles.
    if (
        type(route) is not ReferenceLKRoute
        or type(sidecar) is not SparseRoute
        or sidecar.pipeline_sha256 != native_reference_pipeline_id()
        or sidecar.source_capture_sha256 != route.source_capture_sha256
        or sidecar.intrinsics != route.intrinsics
        or sidecar.camera_trace != route.camera_trace
        or sidecar.source_seconds != route.source_seconds
        or sidecar.source_frame_indices != route.source_frame_indices
        or sidecar.profile.roi != route.profile.roi
        or sidecar.profile.excluded != route.profile.excluded
    ):
        raise ProtocolError("route_descriptor_recovery_binding")
    support = map_support(sidecar)
    if not (
        support["all_reference_neighborhoods_supported"]
        and support["all_reference_intervals_observed"]
    ):
        raise ProtocolError("route_map_has_unobserved_sections")


class _DescriptorRecoverySolve(ReferenceLKLocalizer):
    def __init__(self, route, *, sidecar, **kwargs):
        _validate_sidecar(route, sidecar)
        super().__init__(route, **kwargs)
        try:
            if not self.np.array_equal(self.mask, feature_mask(sidecar.profile)):
                raise ProtocolError("route_descriptor_recovery_mask")
            # RouteLocalizer's descriptor solve uses these read-only arrays.
            # It calls this owner for pose verification, rank and recent hints.
            self.xyz = self.np.asarray(sidecar.points, self.np.float64)
            self.descriptors = self.np.frombuffer(sidecar.descriptors, dtype="<f4").reshape(-1, 128)
            self.visibility = self.np.zeros((len(route.camera_trace), len(sidecar.points)), self.np.uint8)
            for point, views in enumerate(sidecar.landmark_views):
                self.visibility[list(views), point] = 1
            self.xyz.setflags(write=False)
            self.visibility.setflags(write=False)
        except BaseException:
            self.close()
            raise

    def _has_receiver_budget(self, reserve):
        if self.last_received is None:
            return False
        age = self.clock() - self.last_received
        return 0 <= age <= _MAX_FRAME_AGE_SECONDS - reserve

    def _solve_descriptors(self):
        if not self._has_receiver_budget(_DESCRIPTOR_START_RESERVE_SECONDS):
            self.last_diagnostic["descriptorRecoverySkipped"] = "receiver_budget"
            return None

        diagnostic = self.last_diagnostic
        # LK indices and counts refer to different candidates from this solve.
        for key in ("flowRetainedByCandidate", "coarseSearchMs", "candidateMatchPnPMs"):
            diagnostic.pop(key, None)
        diagnostic.update(method="descriptor_pnp", queryFamily=NATIVE_REFERENCE_FAMILY,
                          candidateReferenceIndices=[], verifiedCandidateCount=0)
        began = time.perf_counter()
        pixels, descriptors = extract_gray_features(self._gray, self.mask)
        diagnostic["featureExtractionMs"] = (time.perf_counter() - began) * 1000
        if not self._has_receiver_budget(0):
            return None
        return RouteLocalizer._solve(self, pixels, descriptors)

    def _solve(self, *args):
        solved = super()._solve(*args)
        if solved is not None or self.last_diagnostic.get("verifiedCandidateCount") != 0:
            # A refusal among competing measured LK poses remains a refusal.
            return solved
        return self._solve_descriptors()

    def close(self):
        self.xyz = self.descriptors = self.visibility = self._proposal_index = None
        super().close()


class ReferenceLKRecoveryLocalizer(_BoundedConfirmationMixin, _DescriptorRecoverySolve):
    """Keep one route, one observation and one confirmation window per frame."""

    verification_policy = _BoundedConfirmationMixin.verification_policy + ":" + DESCRIPTOR_RECOVERY_POLICY
