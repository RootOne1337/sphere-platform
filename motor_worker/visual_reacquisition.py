"""Experimental local image-place reacquisition; never commands movement.

Recorded timestamps express route order, not distance. A visual match or a
confirmed local anchor does not establish pose, traversability or goal progress.
Create a new instance for a new capture epoch/route; never bridge epochs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from motor_worker.visual_place_sequence import VisualPlaceSequence


@dataclass(frozen=True)
class ReacquisitionResult:
    state: str
    reference: int | None
    anchor: int | None
    reason: str


class LocalReacquisition:
    """Require a locally consistent sequence; remember the last confirmed anchor.

    An unknown result clears confirmation but retains historical anchor solely
    to bound the next candidate. A distant match is never adopted on its own.
    """

    def __init__(
        self, reference_seconds, *, epoch, start_window_seconds=1.0, anchor_window_seconds=2.0
    ):
        if any(
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(x)
            or not 0 < x <= 5
            for x in (start_window_seconds, anchor_window_seconds)
        ):
            raise ValueError("invalid_reacquisition_window")
        self.sequence = VisualPlaceSequence(reference_seconds, epoch=epoch)
        self.times = reference_seconds
        self.start_window_seconds = start_window_seconds
        self.anchor_window_seconds = anchor_window_seconds
        self.anchor = None

    def observe(self, candidate, observed_at, *, frame_id, epoch):
        # Sequence owns timestamp/epoch/source-frame validation. Filtering after
        # observe retains replay protection even when the candidate is rejected.
        result = self.sequence.observe(candidate, observed_at, frame_id=frame_id, epoch=epoch)
        if candidate.state == "matched" and result.reason not in {
            "capture_epoch_changed_or_missing",
            "source_frame_not_increasing",
            "observation_clock_not_increasing",
            "observation_gap",
            "reference_jump",
        }:
            limit = (
                self.times[0] + self.start_window_seconds
                if self.anchor is None
                else self.times[self.anchor] + self.anchor_window_seconds
            )
            lower = (
                self.times[0]
                if self.anchor is None
                else self.times[self.anchor] - self.anchor_window_seconds
            )
            at = self.times[candidate.reference]
            if not lower <= at <= limit:
                self.sequence.forget_confirmation()
                return ReacquisitionResult(
                    "unknown", None, self.anchor, "candidate_outside_local_window"
                )
        if result.state == "matched":
            self.anchor = result.reference
        return ReacquisitionResult(
            result.state,
            result.reference if result.state == "matched" else None,
            self.anchor,
            result.reason,
        )
