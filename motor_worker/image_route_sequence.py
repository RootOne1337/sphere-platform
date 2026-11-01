"""Temporal selection of reference images, without a pose or execution permit.

Inputs are already geometrically checked image-match scores, not probabilities.
Reference times describe the recorded media: their differences are neither
distance nor a live query clock. Instances belong to one ordered source stream;
replace the instance when that stream changes. No recorded control inputs enter
this filter.
"""

from __future__ import annotations

import math
from array import array
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

SequenceStatus = Literal["reference_selected", "ambiguous", "unknown", "stale"]


def _number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _at_least(value: float, threshold: float) -> bool:
    # Do not turn equality at the relative boundary into uniqueness because
    # e.g. .8 * .75 is represented as .6000000000000001 in binary floating point.
    return value >= threshold or math.isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-12)


@dataclass(frozen=True)
class SequenceEvidence:
    status: SequenceStatus
    index: int | None
    source_seconds: float | None
    candidate_indices: tuple[int, ...]
    confidence_gap: float | None
    confirmations: int
    confirmation_sources: tuple[str, ...]
    checked_references: int
    reason: str
    position_confirmed: Literal[False] = field(default=False, init=False)
    execution_qualified: Literal[False] = field(default=False, init=False)


class RouteSequenceFilter:
    """Require three independent, temporally compatible unique image matches.

    ``checked=False`` means untested, not a failed match. Unchecked scores do not
    compete or enter the score gap; selection is conditional on the caller's
    verified proposal search, not proof that every reference was ruled out.
    The gap is a raw score difference between separated checked peaks, and is
    None when no separated runner-up was checked.

    Nonmaximum suppression merges peaks within ``peak_radius_seconds`` of a
    stronger peak. It never transitively merges a long plateau into one place.
    A confirmed, short-lived prior can order competing supported peaks, but
    cannot remove an alias, validate weak scores, or produce an output index.

    Motion limits use absolute displacement in *reference-media seconds*, so
    reverse travel and varying playback rates are allowed. A discontinuity
    starts a new three-frame acquisition instead of forcing the old location.
    There is no prediction, auto-advance, or special treatment of the last view.
    """

    def __init__(
        self,
        reference_seconds: tuple[float, ...],
        *,
        min_score: float = 0.35,
        relative_peak: float = 0.75,
        peak_radius_seconds: float = 0.6,
        max_frame_age: float = 0.25,
        max_observation_gap: float = 0.5,
        max_reference_speed: float = 5.0,
        reference_slack_seconds: float = 0.6,
        max_seen_sources: int = 4096,
    ):
        if (
            type(reference_seconds) is not tuple
            or not 2 <= len(reference_seconds) <= 256
            or any(not _number(t) or t < 0 for t in reference_seconds)
            or any(b <= a for a, b in zip(reference_seconds, reference_seconds[1:]))
            or not _number(min_score) or not 0 < min_score <= 1
            or not _number(relative_peak) or not 0 < relative_peak <= 1
            or not _number(peak_radius_seconds) or peak_radius_seconds <= 0
            or not _number(max_frame_age) or max_frame_age <= 0
            or not _number(max_observation_gap) or max_observation_gap <= 0
            or not _number(max_reference_speed) or max_reference_speed <= 0
            or not _number(reference_slack_seconds) or reference_slack_seconds < 0
            or type(max_seen_sources) is not int or not 3 <= max_seen_sources <= 65536
        ):
            raise ValueError("invalid_image_route_sequence_options")
        self.reference_seconds = tuple(float(t) for t in reference_seconds)
        self.min_score = float(min_score)
        self.relative_peak = float(relative_peak)
        self.peak_radius_seconds = float(peak_radius_seconds)
        self.max_frame_age = float(max_frame_age)
        self.max_observation_gap = float(max_observation_gap)
        self.max_reference_speed = float(max_reference_speed)
        self.reference_slack_seconds = float(reference_slack_seconds)
        self.max_seen_sources = max_seen_sources
        self._seen: set[str] = set()
        self._last_sequence: int | None = None
        self._last_received: float | None = None
        self._last_now: float | None = None
        self._candidate: int | None = None
        self._candidate_at: float | None = None
        self._confirmation_sources: tuple[str, ...] = ()
        self._prior: int | None = None
        self._prior_at: float | None = None

    def _forget_confirmation(self) -> None:
        self._candidate = self._candidate_at = None
        self._confirmation_sources = ()

    def _result(self, status: SequenceStatus, reason: str, *, candidates: tuple[int, ...] = (),
                gap: float | None = None, checked: int = 0) -> SequenceEvidence:
        selected = self._candidate if status == "reference_selected" else None
        # A stale request cannot export old confirmation as current evidence.
        sources = self._confirmation_sources if status != "stale" else ()
        return SequenceEvidence(
            status=status,
            index=selected,
            source_seconds=self.reference_seconds[selected] if selected is not None else None,
            candidate_indices=candidates,
            confidence_gap=gap,
            confirmations=len(sources),
            confirmation_sources=sources,
            checked_references=checked,
            reason=reason,
        )

    def _peaks(self, scores: Sequence[float], checked: Sequence[bool]) -> list[int]:
        peaks: list[int] = []
        for index in sorted((i for i, ok in enumerate(checked) if ok), key=lambda i: (-scores[i], i)):
            if all(
                not _at_least(self.peak_radius_seconds,
                              abs(self.reference_seconds[index] - self.reference_seconds[other]))
                for other in peaks
            ):
                peaks.append(index)
        return peaks

    def _admit(
        self,
        scores: list[float],
        *,
        source_sequence: int,
        received_at: float,
        source_sha256: str,
        now: float,
        checked: list[bool] | None = None,
    ) -> tuple[tuple[bool, ...], tuple[Literal["unknown", "stale"], str] | None]:
        """Shared delivery guards; rejection cannot advance geometric state."""
        if (
            type(scores) not in (list, tuple)
            or len(scores) != len(self.reference_seconds)
            or any(not _number(s) or not 0 <= s <= 1 for s in scores)
            or checked is not None and (
                type(checked) not in (list, tuple)
                or len(checked) != len(scores)
                or any(type(ok) is not bool for ok in checked)
            )
            or type(source_sequence) is not int or source_sequence < 0
            or not _number(received_at) or received_at < 0
            or not _number(now) or now < 0
            or type(source_sha256) is not str or len(source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in source_sha256)
        ):
            self._forget_confirmation()
            raise ValueError("invalid_image_route_sequence_observation")
        flags = tuple([True] * len(scores) if checked is None else checked)
        repeated = source_sha256 in self._seen
        old_sequence = self._last_sequence is not None and source_sequence <= self._last_sequence
        old_time = self._last_received is not None and received_at <= self._last_received
        clock_rollback = self._last_now is not None and now < self._last_now
        self._last_sequence = max(source_sequence, self._last_sequence or 0)
        self._last_now = max(now, self._last_now or 0.0)
        # A future receipt is not a clock watermark that can poison this epoch.
        if received_at <= now:
            self._last_received = max(received_at, self._last_received or 0.0)
        if len(self._seen) >= self.max_seen_sources and not repeated:
            self._forget_confirmation()
            return flags, ("unknown", "source_history_capacity")
        self._seen.add(source_sha256)
        if repeated or old_sequence or old_time or clock_rollback:
            return flags, ("stale", "replayed_or_out_of_order_source")
        if now < received_at or not _at_least(self.max_frame_age, now - received_at):
            return flags, ("stale", "source_outside_freshness_window")
        return flags, None

    def update(
        self,
        scores: list[float],
        *,
        source_sequence: int,
        received_at: float,
        source_sha256: str,
        now: float,
        checked: list[bool] | None = None,
    ) -> SequenceEvidence:
        """Consume one delivery using an explicit monotonic receipt/``now`` clock.

        Reject replays, nonincreasing sequence/receipt time, future or expired
        deliveries, and a backwards clock. These cannot change the image prior
        or confirmation chain. Identity high-watermarks still consume rejected
        deliveries, so changing their receipt timestamp cannot make them new.
        Exact SHA repeats are detected for the lifetime of the instance. At the
        bounded history limit the filter fails closed; it does not evict hashes
        and let old images independently confirm a new match.
        """
        flags, rejection = self._admit(
            scores, source_sequence=source_sequence, received_at=received_at,
            source_sha256=source_sha256, now=now, checked=checked,
        )
        checked_count = sum(flags)
        if rejection is not None:
            return self._result(*rejection, checked=checked_count)

        peaks = self._peaks(scores, flags)
        gap = scores[peaks[0]] - scores[peaks[1]] if len(peaks) >= 2 else None
        candidates = tuple(
            i for i in peaks if _at_least(scores[i], self.min_score)
            and _at_least(scores[i], self.relative_peak * scores[peaks[0]])
        )
        if not candidates:
            self._forget_confirmation()
            reason = "no_checked_reference" if not peaks else "geometric_support_below_threshold"
            return self._result("unknown", reason, gap=gap, checked=checked_count)
        if len(candidates) > 1:
            prior, prior_at = self._prior, self._prior_at
            if (prior is not None and prior_at is not None and 0 <= now - prior_at
                    and _at_least(self.max_observation_gap, now - prior_at)):
                limit = self.reference_slack_seconds + self.max_reference_speed * (received_at - prior_at)
                candidates = tuple(sorted(candidates, key=lambda i: (
                    abs(self.reference_seconds[i] - self.reference_seconds[prior]) > limit,
                    -scores[i], i,
                )))
            self._forget_confirmation()
            return self._result("ambiguous", "separated_verified_aliases", candidates=candidates,
                                gap=gap, checked=checked_count)

        index = candidates[0]
        previous, previous_at = self._candidate, self._candidate_at
        compatible = previous is not None and previous_at is not None and (
            0 < received_at - previous_at
            and _at_least(self.max_observation_gap, received_at - previous_at)
            and _at_least(
                self.reference_slack_seconds + self.max_reference_speed * (received_at - previous_at),
                abs(self.reference_seconds[index] - self.reference_seconds[previous]),
            )
        )
        self._confirmation_sources = (
            self._confirmation_sources + (source_sha256,) if compatible else (source_sha256,)
        )[-3:]
        self._candidate, self._candidate_at = index, float(received_at)
        if len(self._confirmation_sources) < 3:
            return self._result("unknown", "awaiting_independent_consistent_sources",
                                candidates=candidates, gap=gap, checked=checked_count)
        self._prior, self._prior_at = index, float(received_at)
        return self._result("reference_selected", "image_reference_not_pose_or_arrival",
                            candidates=candidates, gap=gap, checked=checked_count)


@dataclass(frozen=True)
class BeamEvidence(SequenceEvidence):
    """Max-product masses and margins are diagnostics, not probabilities."""

    uncalibrated_posterior: tuple[float, ...] = ()
    uncalibrated_confidence: float | None = None
    uncalibrated_log_margin: float | None = None
    runner_up_index: int | None = None
    uncalibrated_runner_up_mass: float | None = None
    support_lineage_indices: tuple[int, ...] = ()
    checked_indices: tuple[int, ...] = ()
    checked_fraction: float = 0.0
    confidence_is_calibrated: Literal[False] = field(default=False, init=False)


class CausalSequenceBeam(RouteSequenceFilter):
    """Keep every reference state and its best compatible causal path.

    This is max-product/Viterbi filtering, not an HMM sum-product posterior and
    not offline smoothing. The normalized exponentiated state values are called
    ``uncalibrated_posterior`` only for diagnostic display. They are not spatial
    confidence, and proposal-search omissions are not negative observations.

    A checked score >=.35 contributes 3*score; a checked weak score contributes
    -.5; an unchecked state contributes zero. Only three consecutive distinct
    *checked and supported* observations along the selected predecessor path
    permit selection. Neutral/weak path nodes reset that proof. All states,
    including neutral unchecked ones, compete in the .2 log-margin test outside
    the best peak's +/-.6s neighborhood. If the runner is untested,
    ``confidence_gap`` is None even though its all-state diagnostic log margin
    is still enforced. No runner exists if the whole reference fits one peak.

    Sliding window maxima use O(N) temporary state, without an NxN transition
    matrix. A ring of <=32 compact parent-index arrays supports auditable path
    ancestry. Source replay history has the same bounded fail-closed lifetime
    as RouteSequenceFilter. A fresh instance is required for a new source epoch.
    """

    def __init__(
        self,
        reference_seconds: tuple[float, ...],
        *,
        min_score: float = 0.35,
        peak_radius_seconds: float = 0.6,
        max_frame_age: float = 0.25,
        max_observation_gap: float = 0.5,
        max_reference_speed: float = 5.0,
        reference_slack_seconds: float = 0.6,
        max_seen_sources: int = 4096,
        log_margin: float = 0.2,
        emission_scale: float = 3.0,
        weak_emission: float = -0.5,
    ):
        super().__init__(
            reference_seconds, min_score=min_score, peak_radius_seconds=peak_radius_seconds,
            max_frame_age=max_frame_age, max_observation_gap=max_observation_gap,
            max_reference_speed=max_reference_speed, reference_slack_seconds=reference_slack_seconds,
            max_seen_sources=max_seen_sources,
        )
        if (not _number(log_margin) or log_margin < 0
                or not _number(emission_scale) or not 0 < emission_scale <= 100
                or not _number(weak_emission) or not -100 <= weak_emission < 0):
            raise ValueError("invalid_causal_sequence_beam_options")
        self.log_margin = float(log_margin)
        self.emission_scale = float(emission_scale)
        self.weak_emission = float(weak_emission)
        self._log_states = [0.0] * len(reference_seconds)
        self._counts = [0] * len(reference_seconds)
        self._ancestry: deque[tuple[array, str]] = deque(maxlen=32)
        self._dp_received: float | None = None

    def _forget_confirmation(self) -> None:
        super()._forget_confirmation()
        self._log_states = [0.0] * len(self.reference_seconds)
        self._counts = [0] * len(self.reference_seconds)
        self._ancestry.clear()
        self._dp_received = None

    def _predecessors(self, limit: float) -> array:
        """First-index argmax in each sorted reference-time transition window."""
        candidates: deque[int] = deque()
        parents = array("H")
        right = 0
        for timestamp in self.reference_seconds:
            while right < len(self.reference_seconds) and _at_least(
                limit, self.reference_seconds[right] - timestamp,
            ):
                while candidates and self._log_states[candidates[-1]] < self._log_states[right]:
                    candidates.pop()
                candidates.append(right)
                right += 1
            while candidates and not _at_least(limit, timestamp - self.reference_seconds[candidates[0]]):
                candidates.popleft()
            parents.append(candidates[0])  # Each state's own timestamp is in its window.
        return parents

    def _lineage(self, index: int) -> tuple[tuple[str, ...], tuple[int, ...]]:
        sources, indices = [], []
        remaining = self._counts[index]
        for parents, source in reversed(self._ancestry):
            if not remaining:
                break
            sources.append(source)
            indices.append(index)
            index = parents[index]
            remaining -= 1
        return tuple(reversed(sources)), tuple(reversed(indices))

    def update(
        self,
        scores: list[float],
        *,
        source_sequence: int,
        received_at: float,
        source_sha256: str,
        now: float,
        checked: list[bool] | None = None,
    ) -> BeamEvidence:
        flags, rejection = self._admit(
            scores, source_sequence=source_sequence, received_at=received_at,
            source_sha256=source_sha256, now=now, checked=checked,
        )
        checked_indices = tuple(i for i, ok in enumerate(flags) if ok)
        if rejection is not None:
            return BeamEvidence(status=rejection[0], reason=rejection[1], index=None,
                                source_seconds=None, candidate_indices=(), confidence_gap=None,
                                confirmations=0, confirmation_sources=(),
                                checked_references=len(checked_indices), checked_indices=checked_indices,
                                checked_fraction=len(checked_indices) / len(scores))

        dt = None if self._dp_received is None else received_at - self._dp_received
        if dt is None or not _at_least(self.max_observation_gap, dt):
            self._forget_confirmation()
            parents = array("H", range(len(scores)))
        else:
            parents = self._predecessors(self.max_reference_speed * dt + self.reference_slack_seconds)
        supported = tuple(flags[i] and _at_least(s, self.min_score) for i, s in enumerate(scores))
        next_states = [
            self._log_states[parent] + (
                self.emission_scale * scores[i] if supported[i]
                else self.weak_emission if flags[i] else 0.0
            ) for i, parent in enumerate(parents)
        ]
        highest = max(next_states)
        self._log_states = [score - highest for score in next_states]
        self._counts = [min(32, self._counts[parent] + 1) if supported[i] else 0
                        for i, parent in enumerate(parents)]
        self._ancestry.append((parents, source_sha256))
        self._dp_received = float(received_at)
        peaks = self._peaks(self._log_states, [True] * len(scores))
        best = peaks[0]
        runner = peaks[1] if len(peaks) > 1 else None
        margin = -self._log_states[runner] if runner is not None else None
        gap = margin if runner is not None and flags[runner] else None
        masses = tuple(math.exp(value) for value in self._log_states)
        total = sum(masses)
        posterior = tuple(value / total for value in masses)
        candidates = tuple(i for i in peaks if _at_least(self.log_margin, -self._log_states[i]))
        sources, lineage = self._lineage(best)
        status: SequenceStatus
        if not supported[best]:
            status, reason = "unknown", "best_path_has_no_current_checked_support"
        elif margin is not None and not _at_least(margin, self.log_margin):
            status, reason = "ambiguous", "competing_causal_paths"
        elif self._counts[best] < 3:
            status, reason = "unknown", "awaiting_three_supported_path_sources"
        else:
            status, reason = "reference_selected", "causal_image_reference_not_pose_or_arrival"
        selected = best if status == "reference_selected" else None
        return BeamEvidence(
            status=status, reason=reason, index=selected,
            source_seconds=self.reference_seconds[selected] if selected is not None else None,
            candidate_indices=candidates, confidence_gap=gap, confirmations=len(sources),
            confirmation_sources=sources, uncalibrated_posterior=posterior,
            uncalibrated_confidence=posterior[best] if supported[best] and gap is not None else None,
            uncalibrated_log_margin=margin, runner_up_index=runner,
            uncalibrated_runner_up_mass=posterior[runner] if runner is not None else None,
            support_lineage_indices=lineage, checked_references=len(checked_indices),
            checked_indices=checked_indices, checked_fraction=len(checked_indices) / len(scores),
        )
