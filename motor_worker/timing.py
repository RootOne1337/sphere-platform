"""Bounded receiver-clock telemetry, without source capture or input claims."""

from __future__ import annotations

import math
from collections import deque

from motor_worker.protocol import ProtocolError


class ResultTiming:
    """Count accepted results in fixed one-second windows from the first offer.

    Empty windows and leading/trailing silence count. Percentiles describe only
    the last 128 samples; lifetime maxima and window minima use constant memory.
    Reports are snapshots, never an implicit clock tick after session shutdown.
    """

    def __init__(self, expected_hz: float | None = None):
        if expected_hz is not None and (
            type(expected_hz) not in (int, float)
            or not 0 < expected_hz <= 120
        ):
            raise ProtocolError("invalid_result_timing_rate")
        self.expected_hz = expected_hz
        self.started_at: float | None = None
        self.observed_at: float | None = None
        self.last_result_at: float | None = None
        self.closed = False
        self.count = self.window_index = self.window_count = 0
        self.clock_reversals = 0
        self.minimum_window_count: int | None = None
        self.maximum_gap = self.maximum_age = 0.0
        self.gaps: deque[float] = deque(maxlen=128)
        self.ages: deque[float] = deque(maxlen=128)

    @staticmethod
    def _time(value: float) -> None:
        try:
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ProtocolError("invalid_result_timing_clock")

    def advance(self, now: float) -> None:
        self._time(now)
        if self.closed or self.started_at is None:
            return
        if now < self.observed_at:
            # Telemetry must not change the policy's existing rejection path.
            self.clock_reversals += 1
            return
        self.observed_at = now
        gap_origin = self.started_at if self.last_result_at is None else self.last_result_at
        self.maximum_gap = max(self.maximum_gap, now - gap_origin)
        index = int(now - self.started_at)
        if index > self.window_index:
            # More than one elapsed window necessarily contains an empty one.
            count = 0 if index > self.window_index + 1 else self.window_count
            self.minimum_window_count = (
                count if self.minimum_window_count is None else min(self.minimum_window_count, count)
            )
            self.window_index, self.window_count = index, 0

    def start(self, now: float) -> None:
        self._time(now)
        if self.started_at is None and not self.closed:
            self.started_at = self.observed_at = now
        self.advance(now)

    def accept(self, now: float, received_at: float) -> None:
        self._time(now)
        self._time(received_at)
        if received_at > now or self.started_at is None or self.closed:
            raise ProtocolError("invalid_result_timing_sample")
        self.advance(now)
        if now < self.observed_at:
            return
        if self.last_result_at is not None:
            self.gaps.append(now - self.last_result_at)
        age = now - received_at
        self.ages.append(age)
        self.maximum_age = max(self.maximum_age, age)
        self.last_result_at = now
        self.count += 1
        self.window_count += 1

    def close(self, now: float) -> None:
        self.advance(now)
        self.closed = True

    @staticmethod
    def _percentile(values: deque[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] * 1000, 3)

    def report(self) -> dict:
        elapsed = 0.0 if self.started_at is None else self.observed_at - self.started_at
        threshold = None if self.expected_hz is None else math.ceil(self.expected_hz)
        return {
            "clock": "worker_monotonic_receiver_not_source_capture",
            "meaning": "accepted_policy_results_not_android_applied_actions",
            "measurementStarted": self.started_at is not None,
            "measurementClosed": self.closed,
            "clockReversalsIgnored": self.clock_reversals,
            "elapsedSeconds": round(elapsed, 6),
            "acceptedResults": self.count,
            "averageAcceptedHz": round(self.count / elapsed, 3) if elapsed > 0 else None,
            "requestedHz": self.expected_hz,
            "completeOneSecondWindows": self.window_index,
            "minimumAcceptedInCompleteWindow": self.minimum_window_count,
            "requiredCountPerCompleteWindow": threshold,
            "allCompleteWindowsMeetRequestedCount": (
                self.minimum_window_count >= threshold
                if self.minimum_window_count is not None and threshold is not None
                else None
            ),
            "maximumSilenceIncludingLeadingTrailingMs": round(self.maximum_gap * 1000, 3),
            "gapP50Ms": self._percentile(self.gaps, 0.5),
            "gapP95Ms": self._percentile(self.gaps, 0.95),
            "receiverAgeAtResultP50Ms": self._percentile(self.ages, 0.5),
            "receiverAgeAtResultP95Ms": self._percentile(self.ages, 0.95),
            "receiverAgeAtResultMaxMs": round(self.maximum_age * 1000, 3) if self.count else None,
            "percentileTailLimit": 128,
            "gapTailSamples": len(self.gaps),
            "ageTailSamples": len(self.ages),
            "sourceCaptureAgeKnown": False,
        }
