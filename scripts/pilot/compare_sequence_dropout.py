"""Replay real saved proposals with one synthetic candidate dropout; no control."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from motor_worker.visual_global_recovery import GlobalRecovery
from motor_worker.visual_place import PlaceResult
from scripts.pilot.atomic_json import write_json


class Baseline:
    """Previous selection rule, used solely for an identical offline replay."""

    def __init__(self, times):
        self.times, self.paths = times, {}

    def observe(self, indices):
        updated = {}
        for index in indices:
            options = [
                history
                for prior, history in self.paths.items()
                if abs(self.times[index] - self.times[prior]) <= 1.5
            ]
            previous = max(options, key=lambda history: (len(history), history), default=())
            updated[index] = (*previous, index)[-4:]
        self.paths = updated
        eligible = sorted(
            index
            for index, history in updated.items()
            if len(history) == 4 and len(set(history)) >= 2
        )
        if not eligible:
            return "confirming" if updated else "unknown"
        if any(
            abs(self.times[index] - self.times[winner]) > 2
            for index in updated
            for winner in eligible
        ):
            return "ambiguous"
        return "hypothesis"


def run(source: Path, output: Path):
    if output.exists():
        raise ValueError("output_exists")
    raw = source.read_bytes()
    data = json.loads(raw)
    if data.get("same_recording") is not True or data.get("physical_actions") != 0:
        raise ValueError("invalid_source_scope")
    times = tuple(data["reference_times"])
    rows = data["multi_candidate"]["samples"]
    if any(
        b["frame"] <= a["frame"] or not 0 < b["seconds"] - a["seconds"] <= 0.5
        for a, b in zip(rows, rows[1:])
    ):
        raise ValueError("unsupported_replay_order_or_gap")
    # Predeclared evidence case: remove only the second sighting of the real
    # second proposal; this is an induced retrieval loss, not ground truth.
    selected = next((i for i, r in enumerate(rows) if r["frame"] == 279), None)
    if selected is None or 15 not in rows[selected]["candidate_indices"]:
        raise ValueError("expected_candidate_absent")
    baseline = Baseline(times)
    current = GlobalRecovery(times, epoch="recorded")
    compared = []
    for index, row in enumerate(rows):
        pairs = list(zip(row["candidate_indices"], row["candidate_inliers"], strict=True))
        if index == selected:
            pairs = [pair for pair in pairs if pair[0] != 15]
        candidates = tuple(
            PlaceResult("matched", reference, inliers, "saved_candidate")
            for reference, inliers in pairs
        )
        first = baseline.observe([c.reference for c in candidates])
        second = current.observe(
            candidates, row["seconds"], frame_id=row["frame"], epoch="recorded"
        )
        if first != second.state:
            compared.append(
                dict(
                    frame=row["frame"],
                    seconds=row["seconds"],
                    baseline=first,
                    current=second.state,
                    held_previous=second.held_previous,
                )
            )
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(raw).digest():
        raise ValueError("source_changed")
    output.mkdir(parents=False)
    result = dict(
        schema="sphere-sequence-candidate-dropout-v1",
        source_sha256=hashlib.sha256(raw).hexdigest(),
        same_recording=True,
        independent_repeat=False,
        synthetic_dropout=True,
        removed_reference=15,
        dropout_frame=279,
        different_decisions=compared,
        physical_actions=0,
        execution_qualified=False,
        limitation="Induced absence tests bookkeeping, not correctness of either place hypothesis.",
    )
    write_json(output / "report.json", result)
    return result


if __name__ == "__main__":
    base = Path(".local-pilot/fuflo228-20261027")
    result = run(
        base / "visual-place-multicandidate-diverse-v2/report.json",
        base / "sequence-candidate-dropout-v1",
    )
    print(json.dumps(result["different_decisions"]))
