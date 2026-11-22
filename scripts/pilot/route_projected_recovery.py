"""Offline candidate that measures the current image around a prior pose."""

from __future__ import annotations

from motor_worker.route_confirmation import SOFT_VISUAL_MISSES, _BoundedConfirmationMixin
from motor_worker.route_localization import SIZE, trace_step_scale
from motor_worker.route_reference_lk import ReferenceLKLocalizer
from scripts.pilot.check_route_coarse_retrieval import evaluate_reference


class _ProjectedRecoverySolve(ReferenceLKLocalizer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_direct = None
        self._step = trace_step_scale(self.lengths)

    def _agrees(self, first, second):
        np = self.np
        angle = np.arccos(np.clip((np.trace(first[1] @ second[1].T) - 1) / 2, -1, 1))
        return np.linalg.norm(first[0] - second[0]) <= 0.25 * self._step and angle <= 0.12

    def _solve(self, *args):
        direct = super()._solve(*args)
        # A disagreement in direct map measurements remains a disagreement.
        if direct is not None or self.last_diagnostic["verifiedCandidateCount"]:
            return direct
        if self._last_direct is None or not 0 < self.last_received - self._last_direct[3] <= 0.8:
            return None

        np = self.np
        center, rotation, progress, direct_at = self._last_direct
        arrays = self._cache.arrays
        # Camera spacing changes with recorded speed. Select neighboring
        # measured views even when the last pose sits on a fast segment.
        at = int(np.searchsorted(self.cumulative, progress, side="right")) - 1
        eligible = np.arange(max(0, at - 2), min(len(self.cumulative), at + 5))
        scores = np.mean((self._tiny[eligible] - self._thumbnail(self._gray)) ** 2, axis=1)
        first, *rest = eligible[np.argsort(scores, kind="stable")]
        second = next((ref for ref in rest if abs(ref - first) >= 2), None)
        if second is None:
            return None

        self.last_diagnostic.update(
            projectedReferences=[int(first), int(second)],
            projectedRetained=[],
            projectedResult="insufficient",
        )
        verified = []
        for parity, ref in enumerate((first, second)):
            if self.clock() - self.last_received > 0.25 or self.clock() - direct_at > 0.8:
                return None
            start, end = map(int, arrays["offsets"][ref : ref + 2])
            xyz = arrays["xyz"][start:end]
            camera = (xyz - center) @ rotation.T
            keep = (camera[:, 2] > 1e-5) & (arrays["native_ids"][start:end] % 2 == parity)
            indices = np.flatnonzero(keep)
            projected = camera[indices] @ self.K.T
            uv = projected[:, :2] / projected[:, 2:3]
            inside = np.isfinite(uv).all(axis=1) & ((uv >= 0) & (uv < SIZE)).all(axis=1)
            if inside.sum() < 24:
                return None
            count, pose = evaluate_reference(
                self, self._gray, int(ref), initial_pixels=uv[inside], point_indices=indices[inside]
            )
            self.last_diagnostic["projectedRetained"].append(count)
            if pose is None or pose[2] < 24:
                return None
            verified.append(pose)
        if self.clock() - direct_at > 0.8:
            return None
        if not self._agrees(*verified):
            self.last_diagnostic["projectedResult"] = "disagreement"
            return None
        winner = max(verified, key=lambda pose: pose[2])
        nearest = self._nearest(winner[0])
        motion_limit = self._motion_limit(progress, self.last_received - direct_at)
        if (
            nearest is None
            or abs(nearest[1] - progress) > motion_limit
            or np.linalg.norm(winner[0] - center) > motion_limit
        ):
            self.last_diagnostic["projectedResult"] = "outside_motion_envelope"
            return None
        self.last_diagnostic.update(method="projected_reference_lk", projectedResult="agreed")
        return winner[:4]


class ProjectedRecoveryLocalizer(_BoundedConfirmationMixin, _ProjectedRecoverySolve):
    """Candidate behind the existing current-image and temporal gates."""

    def observe(self, frame, **kwargs):
        pose = super().observe(frame, **kwargs)
        if (
            pose.state == "localized"
            and self.last_diagnostic.get("method") == "measured_reference_lk"
        ):
            self._last_direct = self.previous
        elif (
            pose.state == "unknown"
            and pose.reason not in SOFT_VISUAL_MISSES
            and pose.reason != "route_pose_discontinuity"
        ):
            self._last_direct = None
        return pose
