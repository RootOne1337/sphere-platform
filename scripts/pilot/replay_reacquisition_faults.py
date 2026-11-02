"""Fault injection on saved same-recording image-match results; no device input.

Recorded-media time is an evaluation surrogate only. Candidate references not
seen in the saved report are omitted; this is not a complete production index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from motor_worker.visual_place import PlaceResult
from motor_worker.visual_reacquisition import LocalReacquisition


def run(source: Path, output: Path):
    raw = source.read_bytes()
    inputs = json.loads(raw)["samples"]
    reference_times = {}
    for row in inputs:
        if row["state"] == "matched":
            previous = reference_times.setdefault(row["reference"], row["reference_seconds"])
            if previous != row["reference_seconds"]:
                raise ValueError("reference_time_changed")
    ordered = sorted(reference_times.items(), key=lambda item: item[1])
    if len(ordered) < 2 or len({v for _, v in ordered}) != len(ordered):
        raise ValueError("insufficient_unique_references")
    refs = tuple(float(t) for _, t in ordered)
    mapping = {old: i for i, (old, _) in enumerate(ordered)}
    if len(inputs) < 120:
        raise ValueError("insufficient_samples_for_preselected_faults")
    short_faults = {i for start in (30, 70, 110) for i in range(start, start + 3)}
    scenarios = {}
    for mode in ("baseline", "dropout", "far_match", "long_dropout"):
        fault_indices = set(range(50, 75)) if mode == "long_dropout" else short_faults
        tracker = LocalReacquisition(refs, epoch="recorded")
        rows = []
        for idx, row in enumerate(inputs):
            ref = mapping[row["reference"]] if row["state"] == "matched" else None
            candidate = PlaceResult(row["state"], ref, row["inliers"], "saved_image_match")
            injected = idx in fault_indices and mode != "baseline"
            if injected and mode in ("dropout", "long_dropout"):
                candidate = PlaceResult("unknown", None, 0, "synthetic_dropout")
            elif injected:
                # Pick the endpoint opposite the current anchor. This simulates
                # a strong false VPR candidate, not evidence of a real confusion.
                anchor = tracker.anchor
                if anchor is None:
                    raise ValueError("fault_precondition_no_confirmed_anchor")
                far = 0 if refs[anchor] > (refs[0] + refs[-1]) / 2 else len(refs) - 1
                if abs(refs[far] - refs[anchor]) <= 2:
                    raise ValueError("fault_reference_not_far_enough")
                candidate = PlaceResult("matched", far, 100, "synthetic_far_false_match")
            result = tracker.observe(
                candidate, row["seconds"], frame_id=row["source_index"], epoch="recorded"
            )
            difference = (
                None if result.reference is None else row["seconds"] - refs[result.reference]
            )
            rows.append(
                {
                    "frame_id": row["source_index"],
                    "seconds": row["seconds"],
                    "injected": injected,
                    "state": result.state,
                    "reason": result.reason,
                    "reference": result.reference,
                    "anchor": result.anchor,
                    "source_time_difference": difference,
                }
            )
        events = []
        if mode != "baseline":
            intervals = ((50, 74),) if mode == "long_dropout" else ((30, 32), (70, 72), (110, 112))
            for start, end in intervals:
                next_start = next((s for s, _ in intervals if s > start), len(rows))
                recovered = next(
                    (r for r in rows[end + 1 : next_start] if r["state"] == "matched"), None
                )
                events.append(
                    {
                        "first_frame": rows[start]["frame_id"],
                        "last_frame": rows[end]["frame_id"],
                        "duration_seconds": rows[end]["seconds"] - rows[start]["seconds"],
                        "recovered": recovered is not None,
                        "recovery_seconds_after_last_fault": None
                        if recovered is None
                        else recovered["seconds"] - rows[end]["seconds"],
                        "recovered_source_time_difference": None
                        if recovered is None
                        else recovered["source_time_difference"],
                    }
                )
        confirmed = [r for r in rows if r["state"] == "matched"]
        scenarios[mode] = {
            "counts": dict(Counter(r["state"] for r in rows)),
            "confirmed_with_time_difference_over_2s": sum(
                abs(r["source_time_difference"]) > 2 for r in confirmed
            ),
            "confirmed_during_injected_fault": sum(
                r["state"] == "matched" and r["injected"] for r in rows
            ),
            "events": events,
            "rows": rows,
        }
    report = {
        "schema": "offline-local-reacquisition-faults-v1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "same_recording": True,
        "saved_vpr_results": True,
        "omitted_unobserved_reference_views": True,
        "physical_actions": 0,
        "camera_pose_known": False,
        "independent_repeat": False,
        "synthetic_faults_only": True,
        "source_time_is_not_metric_ground_truth": True,
        "samples": len(inputs),
        "reference_count": len(refs),
        "scenarios": scenarios,
    }
    output.mkdir(parents=False, exist_ok=False)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "scenarios"}
            | {
                "scenarios": {
                    k: {a: b for a, b in v.items() if a != "rows"} for k, v in scenarios.items()
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
