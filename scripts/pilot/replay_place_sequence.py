"""Offline replay of saved place results, including one duplicated source frame.

The recorded frame IDs and media times are used; no device, network, inference
or real control. Place matches are hypotheses on the same recorded video.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from motor_worker.visual_place import PlaceResult
from motor_worker.visual_place_sequence import VisualPlaceSequence


def replay(source: Path, output: Path):
    import cv2 as cv
    import numpy as np

    content = source.read_bytes()
    inputs = json.loads(content)["samples"]
    if not inputs:
        raise ValueError("empty_replay")
    # Compact reference IDs while retaining each observed reference's real time.
    seconds_by_id = {}
    for row in inputs:
        if row["state"] == "matched":
            previous = seconds_by_id.setdefault(row["reference"], row["reference_seconds"])
            if previous != row["reference_seconds"]:
                raise ValueError("reference_time_changed")
    ordered = sorted(seconds_by_id.items(), key=lambda item: item[1])
    if len(ordered) < 2 or len({v for _, v in ordered}) != len(ordered):
        raise ValueError("reference_times_not_unique")
    mapping = {old: new for new, (old, _) in enumerate(ordered)}
    times = tuple(float(seconds) for _, seconds in ordered)
    epoch = "recorded-replay"
    normal, duplicate = (
        VisualPlaceSequence(times, epoch=epoch),
        VisualPlaceSequence(times, epoch=epoch),
    )
    rows, injected = [], None
    for row in inputs:
        reference = mapping[row["reference"]] if row["state"] == "matched" else None
        result = PlaceResult(row["state"], reference, row["inliers"], "saved_offline_result")
        observed, frame_id = row["seconds"], row["source_index"]
        a = normal.observe(result, observed, frame_id=frame_id, epoch=epoch)
        b = duplicate.observe(result, observed, frame_id=frame_id, epoch=epoch)
        rows.append(
            {
                "frame_id": frame_id,
                "seconds": observed,
                "place": row["state"],
                "normal": a.state,
                "normal_reason": a.reason,
                "duplicate_replay": b.state,
                "duplicate_reason": b.reason,
            }
        )
        if injected is None and b.state == "matched":
            # Give a duplicate an apparently newer delivery time, preserving
            # the source frame ID. The duplicate must clear confirmation.
            rejected = duplicate.observe(result, observed + 0.001, frame_id=frame_id, epoch=epoch)
            injected = {
                "frame_id": frame_id,
                "seconds": observed,
                "returned": rejected.state,
                "reason": rejected.reason,
            }
    if injected is None or injected["reason"] != "source_frame_not_increasing":
        raise RuntimeError("duplicate_injection_not_rejected")
    summary = {
        "schema": "offline-place-sequence-replay-v1",
        "same_recording": True,
        "saved_matches_not_pose_or_control": True,
        "physical_actions": 0,
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "samples": len(rows),
        "normal_counts": dict(Counter(row["normal"] for row in rows)),
        "duplicate_replay_counts": dict(Counter(row["duplicate_replay"] for row in rows)),
        "duplicate_injected": injected,
        "rows": rows,
    }
    output.mkdir(parents=False, exist_ok=False)
    (output / "report.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    image = np.full((300, 1280, 3), (24, 26, 33), dtype=np.uint8)
    colors = {"matched": (125, 201, 65), "confirming": (43, 183, 241), "unknown": (88, 89, 230)}
    cv.putText(
        image,
        "Recorded frame replay | no control or independent run",
        (30, 38),
        cv.FONT_HERSHEY_SIMPLEX,
        0.67,
        (245, 245, 245),
        2,
        cv.LINE_AA,
    )
    for y, label, key in (
        (90, "Normal", "normal"),
        (160, "Duplicate injected", "duplicate_replay"),
    ):
        cv.putText(
            image, label, (30, y + 12), cv.FONT_HERSHEY_SIMPLEX, 0.5, (225, 225, 225), 1, cv.LINE_AA
        )
        for i, row in enumerate(rows):
            x = 225 + int(990 * i / max(1, len(rows) - 1))
            cv.rectangle(image, (x, y - 8), (x + 5, y + 13), colors[row[key]], -1)
    x = 225 + int(
        990
        * next(i for i, row in enumerate(rows) if row["frame_id"] == injected["frame_id"])
        / max(1, len(rows) - 1)
    )
    cv.line(image, (x, 135), (x, 184), (240, 240, 240), 2)
    cv.putText(
        image,
        "White mark: repeated source frame rejected, confirmation resets",
        (30, 224),
        cv.FONT_HERSHEY_SIMPLEX,
        0.55,
        (240, 240, 240),
        1,
        cv.LINE_AA,
    )
    cv.putText(
        image,
        "Green = match hypothesis    Yellow = confirming    Red = unknown",
        (30, 262),
        cv.FONT_HERSHEY_SIMPLEX,
        0.55,
        (230, 230, 230),
        1,
        cv.LINE_AA,
    )
    if not cv.imwrite(str(output / "timeline.png"), image):
        raise RuntimeError("timeline_write_failed")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    replay(args.source, args.output)
