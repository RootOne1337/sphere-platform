"""Bounded evidence across soft visual misses; no stale pose/input permission.

Three distinct current-image poses within five observations and one second may
confirm a position. Original PnP, corridor, source and 250 ms gates remain. A
separately versioned subpixel centre check admits only bounded translational
indistinguishability after measured rotation. A missing image returns neutral.
"""
from __future__ import annotations

import hashlib
import math
from collections import deque
from pathlib import Path

from motor_worker.protocol import ProtocolError
from motor_worker.route_localization import (
    MAX_REFERENCE_INTERVAL_SECONDS,
    inlier_spatial_support,
    trace_step_scale,
)
from motor_worker.route_reference_lk import REFERENCE_LK_VERIFICATION_POLICY, ReferenceLKLocalizer

CONFIRMATION_POLICY = 'distinct_current_pose_3of5_source_bound_1second_v1'
MOTION_TOLERANCE_POLICY = 'current_inlier_center_subpixel_0p5px_1pct_moving_step_v2'
SOURCE_MOTION_POLICY = 'bounded_source_arc_preimage_local_speed_v1'
CONFIRMATION_RUNTIME_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SOFT_VISUAL_MISSES = frozenset({'route_pose_not_verified', 'route_repeated_rgb_not_independent'})


def source_arc_motion_envelope(cumulative, reference_times, progress, epsilon, dt):
    """Local source-speed envelope for a bounded arc preimage, never all-route.

    A recorded pause has multiple plausible source times for the same arc.
    Intersect every monotone arc segment, including complete zero-length
    plateaus. Actual receiver dt and the original 0.2 s horizon stay unchanged.
    An unobserved source interval makes this extension unavailable.
    """
    import numpy as np

    arc, times = np.asarray(cumulative, np.float64), np.asarray(reference_times, np.float64)
    if (arc.ndim != 1 or not 2 <= len(arc) <= 256 or times.shape != arc.shape
            or not np.isfinite(arc).all() or not np.isfinite(times).all()
            or arc[0] != 0 or arc[-1] <= 0 or (np.diff(arc) < 0).any()
            or (np.diff(times) <= 0).any()
            or any(isinstance(value, (bool, str)) or not np.isscalar(value)
                   or not math.isfinite(value) for value in (progress, epsilon, dt))
            or not 0 <= progress <= arc[-1] or epsilon <= 0 or dt <= 0):
        return None
    low, high = max(0., progress-epsilon), min(float(arc[-1]), progress+epsilon)
    steps, intervals = np.diff(arc), np.diff(times)
    overlap = (arc[:-1] <= high) & (arc[1:] >= low)
    if not overlap.any() or (intervals[overlap] > MAX_REFERENCE_INTERVAL_SECONDS).any():
        return None
    lower, upper = np.zeros(len(steps)), np.ones(len(steps))
    np.divide(low-arc[:-1], steps, out=lower, where=steps > 0)
    np.divide(high-arc[:-1], steps, out=upper, where=steps > 0)
    first = times[:-1] + np.clip(lower, 0, 1)*intervals
    last = times[:-1] + np.clip(upper, 0, 1)*intervals
    first_time, last_time = float(first[overlap].min()), float(last[overlap].max())
    window_start, window_end = max(float(times[0]), first_time-.5), min(float(times[-1]), last_time+.5)
    neighborhood = (times[:-1] <= window_end) & (times[1:] >= window_start)
    if (intervals[neighborhood] > MAX_REFERENCE_INTERVAL_SECONDS).any():
        return None
    speed = float(np.max(steps[neighborhood]/intervals[neighborhood], initial=0.))
    limit = speed*max(float(dt), .2)*1.25
    if not math.isfinite(limit):
        return None
    return dict(limit=limit, speed=speed, arc_low=low, arc_high=high,
                source_first=first_time, source_last=last_time,
                window_start=window_start, window_end=window_end)


def subpixel_projection_consistency(world, image, center, rotation, old_center, old_rotation, calibration):
    """Two centres indistinguishable after the CURRENT verified rotation.

    The 0.5 pixel bound is per coordinate (L-infinity), not a Euclidean radius.
    This is a deterministic image-space check, not a covariance estimate. It
    cannot validate a correspondence or publish the previous pose. The caller
    separately enforces the small source-unit cap and ordinary route gates.
    Camera yaw/pitch is already measured by current PnP. It is compensated in
    this translational sensitivity check; its original 1.05 rad turn gate stays.
    """
    import numpy as np

    world, image, center, rotation, old_center, old_rotation, calibration = (
        np.asarray(value, np.float64) for value in
        (world, image, center, rotation, old_center, old_rotation, calibration))
    if (world.ndim != 2 or world.shape[1:] != (3,) or not 20 <= len(world) <= 8192
            or image.shape != (len(world), 2) or center.shape != (3,) or old_center.shape != (3,)
            or rotation.shape != (3, 3) or old_rotation.shape != (3, 3) or calibration.shape != (3, 3)
            or not all(np.isfinite(value).all() for value in
                       (world, image, center, rotation, old_center, old_rotation, calibration))
            or not inlier_spatial_support(image)):
        return False, None
    turn = float(np.arccos(np.clip((np.trace(rotation @ old_rotation.T)-1)/2, -1, 1)))
    if turn > 1.05:
        return False, None
    singular = np.linalg.svd(world - world.mean(axis=0), compute_uv=False)
    if singular[0] <= 0 or singular[2] / singular[0] < 1e-4:
        return False, None
    projections = []
    for at in (center, old_center):
        camera = (world - at) @ rotation.T
        if not np.isfinite(camera).all() or (camera[:, 2] <= 1e-5).any():
            return False, None
        projected = camera @ calibration.T
        projected = projected[:, :2] / projected[:, 2:]
        if not np.isfinite(projected).all():
            return False, None
        error = np.linalg.norm(projected - image, axis=1)
        keep = error <= 3.
        if (int(keep.sum()) < 20 or keep.mean() < .5
                or not inlier_spatial_support(image[keep]) or np.median(error[keep]) > 2.):
            return False, None
        projections.append(projected)
    maximum = float(np.max(np.abs(projections[0] - projections[1])))
    return maximum <= .5, maximum


class ConfirmationEvidence:
    """A tiny bounded vote window. Invalid slots never provide a current vote."""
    def __init__(self):
        self.slots = deque(maxlen=5)
        self.binding = self.last_sequence = self.last_received = self.current = None

    def clear(self):
        self.slots.clear()
        self.binding = self.last_sequence = self.last_received = self.current = None

    def prepare(self, binding, sequence, received_at):
        if (type(sequence) is not int or not 1 <= sequence <= 1_000_000
                or type(received_at) not in (int, float) or not math.isfinite(received_at)):
            self.clear()
            raise ProtocolError('route_confirmation_observation_invalid')
        if self.binding is not None and binding != self.binding:
            self.clear()
        if (self.last_sequence is not None and sequence <= self.last_sequence
                or self.last_received is not None and received_at <= self.last_received):
            self.clear()
            raise ProtocolError('route_confirmation_observation_order')
        # Include the upcoming observation in the five-slot budget. A miss does
        # not refresh the timestamp of any previously verified image.
        previous = [slot for slot in self.slots if 0 <= received_at - slot[0] <= 1.0][-4:]
        self.slots = deque(previous, maxlen=5)
        self.binding, self.last_sequence, self.last_received = binding, sequence, received_at
        self.current = (received_at, sequence)

    @property
    def votes(self):
        return [slot for slot in self.slots if slot[2] is not None]

    def append(self, source_sha, *, valid, payload=None):
        if self.current is None or type(valid) is not bool:
            raise ProtocolError('route_confirmation_not_prepared')
        if (type(source_sha) is not str or len(source_sha) != 64
                or any(c not in '0123456789abcdef' for c in source_sha)):
            self.clear()
            raise ProtocolError('route_confirmation_source_invalid')
        distinct = source_sha not in [slot[2] for slot in self.votes]
        accepted = valid and distinct
        at, sequence = self.current
        self.slots.append((at, sequence, source_sha if accepted else None, payload if accepted else None))
        self.current = None
        return accepted


class _BoundedConfirmationMixin:
    verification_policy = (REFERENCE_LK_VERIFICATION_POLICY + ':' + CONFIRMATION_POLICY
                           + ':' + MOTION_TOLERANCE_POLICY + ':' + SOURCE_MOTION_POLICY)
    confirmation_policy = CONFIRMATION_POLICY
    confirmation_runtime_sha256 = CONFIRMATION_RUNTIME_SHA256

    def __init__(self, *args, **kwargs):
        self._confirmation = ConfirmationEvidence()
        self._verified_current = []
        self._solving_current = self._subpixel_allowance = False
        self._winner_current_verified = False
        super().__init__(*args, **kwargs)

    def _restore_evidence(self):
        votes = self._confirmation.votes
        self.confirmations = len(votes)
        self.previous = votes[-1][3] if votes else None
        self.recent_confirmed_sources = [slot[2] for slot in votes]

    def _solve(self, *args):
        # No allowance exists while hypotheses are being ranked. Only the
        # actual winning object's own measured inliers can authorize this check.
        self._verified_current.clear()
        self._subpixel_allowance = False
        self._winner_current_verified = False
        self._solving_current = True
        try:
            solved = super()._solve(*args)
        finally:
            self._solving_current = False
        winner = None if solved is None else next((row for row in self._verified_current
                    if row[0][0] is solved[0] and row[0][1] is solved[1]), None)
        self._winner_current_verified = winner is not None
        if solved is not None and self.previous is not None:
            center, rotation = solved[:2]
            old_center, old_rotation, old_progress, _ = self.previous
            nearest = self._nearest(center)
            self.last_diagnostic.update(
                motionCenterDeltaUnits=float(self.np.linalg.norm(center - old_center)),
                motionLimitUnits=float(self._motion_limit(old_progress, self.last_received - self.previous[3])),
                motionTurnRadians=float(self.np.arccos(self.np.clip(
                    (self.np.trace(rotation @ old_rotation.T) - 1) / 2, -1, 1))),
            )
            if nearest is not None:
                self.last_diagnostic['motionProgressDeltaUnits'] = abs(float(nearest[1] - old_progress))
            cap = trace_step_scale(self.lengths) * .01
            self.last_diagnostic.update(motionConsistencyPolicy=MOTION_TOLERANCE_POLICY,
                                        motionSubpixelCapUnits=cap, motionSubpixelEligible=False)
            if (nearest is not None and self.last_diagnostic['motionCenterDeltaUnits'] <= cap
                    and self.last_diagnostic['motionProgressDeltaUnits'] <= cap
                    and self.last_diagnostic['motionTurnRadians'] <= 1.05):
                if winner is not None:
                    eligible, maximum = subpixel_projection_consistency(
                        winner[1], winner[2], center, rotation, old_center, old_rotation, self.K)
                    self._subpixel_allowance = eligible
                    self.last_diagnostic['motionSubpixelEligible'] = eligible
                    if maximum is not None:
                        self.last_diagnostic['motionSubpixelDeltaPx'] = maximum
        if solved is not None:
            self.last_diagnostic.update(verifiedInliersBeforeTemporalGate=int(solved[2]),
                                        verifiedMedianErrorPx=float(solved[3]))
        return solved

    def _verify_correspondences(self, world, image):
        verified = super()._verify_correspondences(world, image)
        if verified is not None and self._solving_current and len(self._verified_current) < 8:
            keep = verified[4]
            self._verified_current.append((verified, self.np.asarray(world)[keep].copy(),
                                           self.np.asarray(image)[keep].copy()))
        return verified

    def _motion_limit(self, progress, dt):
        original = super()._motion_limit(progress, dt)
        self.last_diagnostic['motionBaseLimitUnits'] = original
        effective = original
        if self._winner_current_verified and not self._solving_current:
            envelope = source_arc_motion_envelope(self.cumulative, self.reference_times, progress,
                                                   trace_step_scale(self.lengths)*.01, dt)
            self.last_diagnostic.update(motionSourcePolicy=SOURCE_MOTION_POLICY,
                                        motionSourceEnvelopeEligible=envelope is not None)
            if envelope is not None:
                effective = max(effective, envelope['limit'])
                self.last_diagnostic.update(motionSourceLimitUnits=envelope['limit'],
                    motionSourceArcEpsilonUnits=trace_step_scale(self.lengths)*.01,
                    motionSourceMaxSpeedUnitsPerSecond=envelope['speed'],
                    motionSourceArcLowUnits=envelope['arc_low'], motionSourceArcHighUnits=envelope['arc_high'],
                    motionSourceFirstSeconds=envelope['source_first'], motionSourceLastSeconds=envelope['source_last'],
                    motionSourceWindowStartSeconds=envelope['window_start'],
                    motionSourceWindowEndSeconds=envelope['window_end'])
        if self._subpixel_allowance and not self._solving_current:
            allowance = trace_step_scale(self.lengths) * .01
            self.last_diagnostic['motionAllowanceUnits'] = allowance
            effective = max(effective, allowance)
        self.last_diagnostic['motionLimitUnits'] = effective
        return effective

    def observe(self, frame, *, episode_id, goal_revision, scene):
        # Core validation remains authoritative; only valid PolicyFrame fields
        # can prepare evidence. Any binding/scene/freshness failure hard-resets.
        from motor_worker.policy import PolicyFrame
        try:
            self._subpixel_allowance = False
            self._winner_current_verified = False
            if type(frame) is not PolicyFrame:
                raise ProtocolError('invalid_route_localization_observation')
            binding = (self.route.id, self.route.world_revision, self.route.source_sha256,
                       frame.capture_epoch, episode_id, goal_revision)
            self._confirmation.prepare(binding, frame.receiver_sequence, frame.received_at)
            self._restore_evidence()
            pose = super().observe(frame, episode_id=episode_id, goal_revision=goal_revision, scene=scene)
            if pose.state in {'confirming', 'localized'}:
                if not self._confirmation.append(pose.source_rgb_sha256, valid=True, payload=self.previous):
                    raise ProtocolError('route_confirmation_duplicate_pose')
                self._restore_evidence()
                expected = 'localized' if self.confirmations >= 3 else 'confirming'
                if pose.state != expected:
                    raise ProtocolError('route_confirmation_state_inconsistent')
            elif pose.reason in SOFT_VISUAL_MISSES and not self.retired and scene == 'active':
                self._confirmation.append(pose.source_rgb_sha256, valid=False)
                self._restore_evidence()
            else:
                self._confirmation.clear()
            self.last_diagnostic.update(confirmationPolicy=CONFIRMATION_POLICY,
                                        confirmationValidCount=len(self._confirmation.votes),
                                        confirmationObservationCount=len(self._confirmation.slots))
            return pose
        except BaseException as exc:
            if isinstance(exc, ProtocolError) and str(exc) == 'route_confirmation_observation_order':
                self.retired = True
            self._confirmation.clear()
            self.confirmations, self.previous = 0, None
            self.recent_confirmed_sources.clear()
            raise
        finally:
            self._subpixel_allowance = False
            self._winner_current_verified = False
            self._verified_current.clear()

    def close(self):
        self._confirmation.clear()
        self._verified_current.clear()
        self._subpixel_allowance = False
        self._winner_current_verified = False
        super().close()


class ReferenceLKConfirmationLocalizer(_BoundedConfirmationMixin, ReferenceLKLocalizer):
    """Same measured-image family and geometry with bounded soft-miss evidence."""
