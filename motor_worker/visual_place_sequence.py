"""Diagnostic temporal consistency for image places, never a driving permit.

All limits are in recorded-media seconds, not metres. Each instance is bound to
one stream epoch; callers must replace it when the source epoch changes and
provide a monotonically increasing source-frame ID, not a receive counter.
This module does not estimate a vehicle position, confirm a road, or authorize
Android input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from motor_worker.visual_place import PlaceResult


@dataclass(frozen=True)
class SequenceResult:
    state: str
    reference: int | None
    reason: str


class VisualPlaceSequence:
    """Require three compatible observations; forget lock on any uncertainty."""

    def __init__(self, reference_seconds, *, epoch, max_gap_seconds=0.5, max_reference_step=2.0):
        if (
            type(reference_seconds) is not tuple
            or not 2 <= len(reference_seconds) <= 240
            or any(
                isinstance(t, bool)
                or not isinstance(t, (int, float))
                or not math.isfinite(t)
                or t < 0
                for t in reference_seconds
            )
            or any(b <= a for a, b in zip(reference_seconds, reference_seconds[1:]))
            or type(epoch) is not str
            or not 1 <= len(epoch) <= 128
            or isinstance(max_gap_seconds, bool)
            or not isinstance(max_gap_seconds, (int, float))
            or not math.isfinite(max_gap_seconds)
            or not 0 < max_gap_seconds <= 1
            or isinstance(max_reference_step, bool)
            or not isinstance(max_reference_step, (int, float))
            or not math.isfinite(max_reference_step)
            or not 0 < max_reference_step <= 5
        ):
            raise ValueError("invalid_visual_place_sequence")
        self.times = reference_seconds
        self.epoch = epoch
        self.max_gap_seconds = max_gap_seconds
        self.max_reference_step = max_reference_step
        self.last_observed = None
        self.last_frame_id = None
        self.previous_reference = None
        self.confirmations = 0

    def _reset(self, reason):
        self.previous_reference = None
        self.confirmations = 0
        return SequenceResult("unknown", None, reason)

    def forget_confirmation(self):
        """Forget candidate evidence without resetting source identity or clock."""
        self._reset("confirmation_cleared")

    def observe(self, result, observed_at, *, frame_id=None, epoch=None):
        if (
            type(result) is not PlaceResult
            or result.state not in {"matched", "unknown", "ambiguous"}
            or isinstance(observed_at, bool)
            or not isinstance(observed_at, (int, float))
            or not math.isfinite(observed_at)
            or observed_at < 0
            or type(frame_id) is not int
            or frame_id < 0
            or result.state == "matched"
            and (
                type(result.reference) is not int
                or not 0 <= result.reference < len(self.times)
                or type(result.inliers) is not int
                or result.inliers < 15
            )
        ):
            self._reset("invalid_observation")
            raise ValueError("invalid_visual_place_sequence_observation")
        if type(epoch) is not str or epoch != self.epoch:
            return self._reset("capture_epoch_changed_or_missing")
        if self.last_frame_id is not None and frame_id <= self.last_frame_id:
            return self._reset("source_frame_not_increasing")
        # Even a frame with a broken timestamp must not later be replayed with
        # a new receive time to count as fresh evidence.
        self.last_frame_id = frame_id
        if self.last_observed is not None and observed_at <= self.last_observed:
            return self._reset("observation_clock_not_increasing")
        gap = (
            self.last_observed is not None
            and observed_at - self.last_observed > self.max_gap_seconds
        )
        self.last_observed = float(observed_at)
        if gap:
            return self._reset("observation_gap")
        if result.state != "matched":
            return self._reset("visual_match_" + result.state)
        if (
            self.previous_reference is not None
            and abs(self.times[result.reference] - self.times[self.previous_reference])
            > self.max_reference_step
        ):
            return self._reset("reference_jump")
        self.previous_reference = result.reference
        self.confirmations += 1
        if self.confirmations < 3:
            return SequenceResult("confirming", None, "awaiting_consistent_views")
        return SequenceResult("matched", result.reference, "image_sequence_not_pose_or_clearance")
