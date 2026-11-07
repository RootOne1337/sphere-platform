"""Offline multi-hypothesis route relocalization, without control authority.

Inputs must be independently produced image-match candidates. This component
does not validate geometry, determine metres, prove a pose, or issue controls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from motor_worker.visual_place import PlaceResult


@dataclass(frozen=True)
class RecoveryHypotheses:
    state: str
    reference: int | None
    surviving: tuple[int, ...]
    reason: str
    held_previous: tuple[int, ...] = ()
    reference_streak: int = 0
    reference_streak_seconds: float = 0.0
    near_reference_tail: bool = False


class GlobalRecovery:
    """Compare <=8 candidates for four fresh views; keep competing paths.

    Route seconds only describe ordering in the original media, not distance,
    speed, elapsed time in the new run, or a physical pose. Instantiate anew
    for a capture epoch. No output is a navigation or actuator permit.
    """

    def __init__(self, reference_seconds, *, epoch):
        if (
            type(reference_seconds) is not tuple
            or not 2 <= len(reference_seconds) <= 240
            or any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                or v < 0
                for v in reference_seconds
            )
            or any(a >= b for a, b in zip(reference_seconds, reference_seconds[1:]))
            or type(epoch) is not str
            or not 1 <= len(epoch) <= 128
        ):
            raise ValueError("invalid_global_recovery_binding")
        self.times, self.epoch = reference_seconds, epoch
        self.frame_id = self.time = None
        self.paths = {}
        self.last_winner = None
        self.winner_since = None
        self.winner_count = 0

    def _clear_winner(self):
        self.last_winner, self.winner_since, self.winner_count = None, None, 0

    def observe(self, candidates, observed_at, *, frame_id, epoch):
        valid = (
            type(candidates) is tuple
            and len(candidates) <= 8
            and all(
                type(c) is PlaceResult
                and c.state == "matched"
                and type(c.reference) is int
                and 0 <= c.reference < len(self.times)
                and type(c.inliers) is int
                and c.inliers >= 15
                for c in candidates
            )
            and len({c.reference for c in candidates}) == len(candidates)
            and type(frame_id) is int
            and frame_id >= 0
            and not isinstance(observed_at, bool)
            and isinstance(observed_at, (int, float))
            and math.isfinite(observed_at)
            and observed_at >= 0
        )
        if not valid:
            self.paths.clear()
            self._clear_winner()
            raise ValueError("invalid_global_recovery_observation")
        if epoch != self.epoch:
            self.paths.clear()
            self._clear_winner()
            return RecoveryHypotheses("unknown", None, (), "capture_epoch_changed_or_missing")
        if self.frame_id is not None and frame_id <= self.frame_id:
            self.paths.clear()
            self._clear_winner()
            return RecoveryHypotheses("unknown", None, (), "source_frame_not_increasing")
        self.frame_id = frame_id
        if self.time is not None and observed_at <= self.time:
            self.paths.clear()
            self._clear_winner()
            return RecoveryHypotheses("unknown", None, (), "observation_clock_not_increasing")
        if self.time is not None and observed_at - self.time > 0.5:
            self.paths.clear()
            self._clear_winner()
        self.time = float(observed_at)
        # A top-K retriever can temporarily omit an otherwise supported place.
        # Keep a missing, distinct branch as a competitor for one observation,
        # but never count it as a fresh match or carry it over an empty frame.
        missing = {
            previous
            for previous in self.paths
            if candidates
            and all(abs(self.times[c.reference] - self.times[previous]) > 1.5 for c in candidates)
        }
        updated = {}
        for candidate in candidates:
            index = candidate.reference
            options = [
                history
                for previous, history in self.paths.items()
                if abs(self.times[index] - self.times[previous]) <= 1.5
            ]
            # Prefer the longest viable history; deterministic tie-break.
            prior = max(options, key=lambda h: (len(h), h), default=())
            updated[index] = (*prior, index)[-4:]
        self.paths = updated
        eligible = sorted(
            index
            for index, history in updated.items()
            if len(history) == 4 and len(set(history)) >= 2
        )
        if not eligible:
            self._clear_winner()
            return RecoveryHypotheses(
                "confirming" if updated else "unknown", None, (), "no_independent_sequence"
            )
        # A geometrically supported competing candidate must not disappear
        # merely because its branch has only one distinct nearby reference.
        # Otherwise a densely sampled false branch can win against a sparse
        # but genuine competing location. Top-K remains non-exhaustive.
        competing = sorted(
            index
            for index in set(updated) | missing
            if any(abs(self.times[index] - self.times[winner]) > 2.0 for winner in eligible)
        )
        if competing:
            self._clear_winner()
            return RecoveryHypotheses(
                "ambiguous",
                None,
                tuple(sorted(set(eligible + competing))),
                "multiple_distant_hypotheses",
                tuple(sorted(missing.intersection(competing))),
            )
        # Similar adjacent views can be a single local hypothesis; no position
        # averaging, confidence or correctness claim is implied.
        winner = eligible[len(eligible) // 2]
        if winner != self.last_winner:
            self.last_winner, self.winner_since, self.winner_count = winner, float(observed_at), 1
        else:
            self.winner_count += 1
        return RecoveryHypotheses(
            "hypothesis",
            winner,
            tuple(eligible),
            "image_sequence_not_pose_or_control",
            reference_streak=self.winner_count,
            reference_streak_seconds=float(observed_at - self.winner_since),
            near_reference_tail=winner >= len(self.times) - 2,
        )
