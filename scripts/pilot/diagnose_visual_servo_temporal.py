"""Offline adjacent-time observations. No inference about steer or pose."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from motor_worker.visual_servo_diagnostic import compare
from motor_worker.visual_servo_epipolar_diagnostic import compare_epipolar
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]


def run(capture: Path, output: Path):
    import av
    import cv2 as cv
    import numpy as np

    findings = evaluate(collect(ROOT), min_ram_gib=12)
    if findings:
        raise RuntimeError("resource_guard: " + ", ".join(map(str, findings)))
    cv.setNumThreads(4)
    cv.setRNGSeed(17)
    meta = [
        json.loads(s) for s in (capture / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    times = np.array([r["relative_ticks_90k"] / 90000 for r in meta])
    pairs = []
    for t in np.linspace(6, 23, 10):
        reference = int(np.argmin(np.abs(times - t)))
        for dt in (0.25, 0.5, 1.0, 2.0):
            query = int(np.argmin(np.abs(times - (times[reference] + dt))))
            if query == reference:
                raise ValueError("unexpected_identical_frames")
            pairs.append((reference, query, dt))
    needed = {i for ref, query, _ in pairs for i in (ref, query)}
    frames = {}
    with av.open(str(capture / "video.h264")) as video:
        for index, frame in enumerate(video.decode(video=0)):
            if index in needed:
                frames[index] = cv.resize(
                    frame.to_ndarray(format="bgr24"), (960, 540), interpolation=cv.INTER_AREA
                )
    if set(frames) != needed:
        raise ValueError("missing_selected_frames")
    output.mkdir(parents=False, exist_ok=False)
    (output / "intent.json").write_text(
        json.dumps(
            {
                "offline": True,
                "physical_actions": 0,
                "same_recording": True,
                "synthetic_shifts": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    rows = []
    for ref, query, dt in pairs:
        result = compare(frames[ref], frames[query])
        epipolar = compare_epipolar(frames[ref], frames[query])
        disagreement = (
            abs(result.x_pixels - result.center_x_pixels)
            if result.x_pixels is not None and result.center_x_pixels is not None
            else None
        )
        rows.append(
            {
                "reference_frame": ref,
                "query_frame": query,
                "reference_seconds": float(times[ref]),
                "query_seconds": float(times[query]),
                "target_delta_seconds": dt,
                **asdict(result),
                "disagreement_px": disagreement,
                "epipolar": asdict(epipolar),
            }
        )
    by_gap = {}
    for gap in (0.25, 0.5, 1.0, 2.0):
        subset = [r for r in rows if r["target_delta_seconds"] == gap]
        measured = [r for r in subset if r["disagreement_px"] is not None]
        by_gap[str(gap)] = {
            "count": len(subset),
            "states": dict(Counter(r["state"] for r in subset)),
            "epipolar_states": dict(Counter(r["epipolar"]["state"] for r in subset)),
            "both_measured": sum(
                r["state"] == "measured" and r["epipolar"]["state"] == "measured" for r in subset
            ),
            "disagreement_above_5_px": sum(r["disagreement_px"] > 5 for r in measured),
            "median_disagreement_px": float(np.median([r["disagreement_px"] for r in measured]))
            if measured
            else None,
        }
    report = {
        "schema": "offline-temporal-image-displacement-v1",
        "physical_actions": 0,
        "same_recording": True,
        "synthetic_shifts": False,
        "not_pose_or_steering_accuracy": True,
        "source_sha256": hashlib.sha256((capture / "video.h264").read_bytes()).hexdigest(),
        "by_gap": by_gap,
        "samples": rows,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    # Actual frames, side by side. Text is diagnostic only, not a route/steering arrow.
    tiles = []
    for base in (0, 3, 6, 9):
        row = rows[base * 4 + 1]  # gap about 0.5 seconds
        ref, qry = (
            cv.resize(frames[i], (480, 270), interpolation=cv.INTER_AREA)
            for i in (row["reference_frame"], row["query_frame"])
        )
        tile = np.zeros((310, 960, 3), dtype=np.uint8)
        tile[:270, :480], tile[:270, 480:] = ref, qry
        cv.putText(
            tile,
            f"REF {row['reference_seconds']:.2f}s",
            (10, 24),
            cv.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv.LINE_AA,
        )
        cv.putText(
            tile,
            f"QUERY {row['query_seconds']:.2f}s",
            (490, 24),
            cv.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv.LINE_AA,
        )
        detail = (
            f"{row['state']} | inliers {row['inliers']} | median/center diff "
            + (
                f"{row['disagreement_px']:.1f}px"
                if row["disagreement_px"] is not None
                else "unknown"
            )
            + f" | epipolar {row['epipolar']['state']} ({row['epipolar']['inliers']})"
        )
        cv.putText(
            tile, detail, (10, 297), cv.FONT_HERSHEY_SIMPLEX, 0.55, (215, 225, 235), 1, cv.LINE_AA
        )
        tiles.append(tile)
    if not cv.imwrite(str(output / "actual-frame-pairs.png"), np.vstack(tiles)):
        raise RuntimeError("preview_write_failed")
    print(
        json.dumps({"by_gap": by_gap, "preview": str(output / "actual-frame-pairs.png")}, indent=2)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.capture, args.output)
