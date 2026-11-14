"""Single decoded-frame slot. Receiver timing is never called capture latency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Observation:
    receiver_sequence: int
    received_at: float
    pts: int
    time_base: Any
    frame: Any


class LatestFrame:
    def __init__(self) -> None:
        self.latest: Observation | None = None
        self.decoded = 0
        self.duplicate_or_reordered_pts = 0
        self.last_pts: int | None = None
        self.last_time_base = None
        self.selected_sequence = 0
        self.observations = 0
        self.max_unique_arrival_gap_ms = 0.0
        self.unique_arrival_gaps_over_250ms = 0
        self.last_unique_arrival_at = None

    def put(self, frame: Any, now: float) -> bool:
        self.decoded += 1
        if (
            type(frame.pts) is not int
            or frame.time_base is None
            or self.last_time_base is not None
            and frame.time_base != self.last_time_base
            or self.last_pts is not None
            and frame.pts <= self.last_pts
        ):
            self.duplicate_or_reordered_pts += 1
            return False
        if self.last_unique_arrival_at is not None:
            gap_ms = (now - self.last_unique_arrival_at) * 1000
            self.max_unique_arrival_gap_ms = max(self.max_unique_arrival_gap_ms, gap_ms)
            self.unique_arrival_gaps_over_250ms += int(gap_ms > 250)
        self.last_unique_arrival_at = now
        self.last_pts, self.last_time_base = frame.pts, frame.time_base
        self.latest = Observation(self.decoded, now, frame.pts, frame.time_base, frame)
        return True

    def take(self, now: float, max_age: float = 1) -> Observation | None:
        item = self.latest
        if (
            item is None
            or item.receiver_sequence == self.selected_sequence
            or not 0 <= now - item.received_at <= max_age
        ):
            return None
        self.selected_sequence = item.receiver_sequence
        self.observations += 1
        return item

    def clear(self) -> None:
        self.latest = None
