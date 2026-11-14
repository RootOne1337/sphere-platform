"""Offline hypothesis-only recovery after synthetic loss on saved matches."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from motor_worker.visual_global_recovery import GlobalRecovery
from motor_worker.visual_place import PlaceResult


def run(source, output):
    raw = source.read_bytes()
    samples = json.loads(raw)["samples"]
    references = {}
    for sample in samples:
        if sample["state"] == "matched":
            old = references.setdefault(sample["reference"], sample["reference_seconds"])
            if old != sample["reference_seconds"]:
                raise ValueError("reference_time_changed")
    ordered = sorted(references.items(), key=lambda item: item[1])
    times = tuple(v for _, v in ordered)
    if len(samples) < 120 or len(set(times)) != len(times):
        raise ValueError("invalid_saved_samples")
    lookup = {key: i for i, (key, _) in enumerate(ordered)}
    # Match the previously reported injected loss at source sample indices
    # 50..74. No outputs during the loss; start global recovery at 75.
    recovery = GlobalRecovery(times, epoch="offline")
    rows = []
    for sample in samples[75:]:
        candidates = ()
        if sample["state"] == "matched":
            candidates = (
                PlaceResult("matched", lookup[sample["reference"]], sample["inliers"], "saved"),
            )
        result = recovery.observe(
            candidates, sample["seconds"], frame_id=sample["source_index"], epoch="offline"
        )
        delta = None if result.reference is None else sample["seconds"] - times[result.reference]
        rows.append(
            {
                "source_index": sample["source_index"],
                "seconds": sample["seconds"],
                "state": result.state,
                "reference": result.reference,
                "source_time_difference": delta,
            }
        )
    first = next((row for row in rows if row["state"] == "hypothesis"), None)
    accepted = [row for row in rows if row["state"] == "hypothesis"]
    report = {
        "schema": "offline-global-recovery-v1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "same_recording": True,
        "independent_repeat": False,
        "physical_actions": 0,
        "candidates_per_frame_at_most_one": True,
        "can_test_competing_hypotheses": False,
        "source_time_not_metric_truth": True,
        "not_connected_to_control": True,
        "post_loss_samples": len(rows),
        "counts": dict(Counter(row["state"] for row in rows)),
        "first_hypothesis": first,
        "first_hypothesis_seconds_after_last_fault": None
        if first is None
        else first["seconds"] - samples[74]["seconds"],
        "hypotheses_over_2s_media_difference": sum(
            abs(row["source_time_difference"]) > 2 for row in accepted
        )
        if accepted
        else None,
        "rows": rows,
    }
    output.mkdir(parents=False, exist_ok=False)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    run(arguments.source, arguments.output)
