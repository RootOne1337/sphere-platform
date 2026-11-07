"""Replay matched fuflo-style frame pairs with artificial image shifts.

Read-only source, no physical input or vehicle simulation. Comparisons are
between frames of the same recording; shifts are image transformations, not
independent camera positions. The result cannot qualify a route for driving.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from motor_worker.visual_servo_diagnostic import compare
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]


def run(
    capture: Path,
    matches: Path,
    output: Path,
    *,
    shifts=(-24, 24),
    selection="endpoints",
    exclude_report: Path | None = None,
):
    import av
    import cv2 as cv
    import numpy as np

    findings = evaluate(collect(ROOT), min_ram_gib=12)
    if findings:
        raise RuntimeError("resource_guard: " + ", ".join(map(str, findings)))
    cv.setNumThreads(4)
    cv.setRNGSeed(17)
    if (
        not shifts
        or any(type(s) is not int or s == 0 or abs(s) > 96 for s in shifts)
        or len(set(shifts)) != len(shifts)
    ):
        raise ValueError("invalid_pixel_shifts")
    if selection not in {"endpoints", "midpoints"}:
        raise ValueError("invalid_sample_selection")
    frame_rows = [
        json.loads(line)
        for line in (capture / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    times = [row["relative_ticks_90k"] / 90000 for row in frame_rows]
    samples = json.loads(matches.read_text(encoding="utf-8"))["samples"]
    excluded = set()
    if exclude_report is not None:
        excluded = {
            s["query_frame"]
            for s in json.loads(exclude_report.read_text(encoding="utf-8"))["samples"]
        }
    candidates = [
        s
        for s in samples
        if s["state"] == "matched" and 6 <= s["seconds"] <= 24 and s["source_index"] not in excluded
    ]
    if len(candidates) < 16:
        raise ValueError("insufficient_candidate_frames")
    selected = []
    targets = (
        np.linspace(6, 24, 16)
        if selection == "endpoints"
        else np.linspace(6 + 18 / 32, 24 - 18 / 32, 16)
    )
    for target in targets:
        sample = min(candidates, key=lambda s: abs(s["seconds"] - target))
        ref = min(range(len(times)), key=lambda i: abs(times[i] - sample["reference_seconds"]))
        if ref != sample["source_index"] and all(p[0] != sample["source_index"] for p in selected):
            selected.append(
                (sample["source_index"], ref, sample["seconds"], sample["reference_seconds"])
            )
    if len(selected) < 10:
        raise ValueError("insufficient_separate_frame_pairs")
    required = {i for pair in selected for i in pair[:2]}
    frames = {}
    with av.open(str(capture / "video.h264")) as stream:
        for index, frame in enumerate(stream.decode(video=0)):
            if index in required:
                frames[index] = cv.resize(
                    frame.to_ndarray(format="bgr24"), (960, 540), interpolation=cv.INTER_AREA
                )
    if set(frames) != required:
        raise ValueError("missing_decoded_selected_frames")
    output.mkdir(parents=False, exist_ok=False)
    (output / "intent.json").write_text(
        json.dumps(
            {
                "offline": True,
                "physical_actions": 0,
                "same_recording": True,
                "synthetic_pixel_shifts": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    results = []
    elapsed = []
    for query_index, ref_index, seconds, ref_seconds in selected:
        ref, query = frames[ref_index], frames[query_index]
        variants = {}
        for shift in (0, *shifts):
            transformed = (
                query
                if shift == 0
                else cv.warpAffine(query, np.float32([[1, 0, shift], [0, 1, 0]]), (960, 540))
            )
            start = time.perf_counter()
            value = compare(ref, transformed)
            elapsed.append((time.perf_counter() - start) * 1000)
            variants[str(shift)] = asdict(value)
        baseline = variants["0"]["x_pixels"]
        for shift in shifts:
            row = variants[str(shift)]
            row["delta_vs_baseline_px"] = (
                None if baseline is None or row["x_pixels"] is None else row["x_pixels"] - baseline
            )
            base_center = variants["0"]["center_x_pixels"]
            row["center_delta_vs_baseline_px"] = (
                None
                if base_center is None or row["center_x_pixels"] is None
                else row["center_x_pixels"] - base_center
            )
            row["expected_delta_px"] = -shift
        results.append(
            {
                "query_frame": query_index,
                "reference_frame": ref_index,
                "query_seconds": seconds,
                "reference_seconds": ref_seconds,
                "variants": variants,
            }
        )
    known = [
        row["variants"][str(shift)]
        for row in results
        for shift in shifts
        if row["variants"][str(shift)]["delta_vs_baseline_px"] is not None
    ]
    errors = [abs(v["delta_vs_baseline_px"] - v["expected_delta_px"]) for v in known]
    center_known = [v for v in known if v["center_delta_vs_baseline_px"] is not None]
    center_errors = [
        abs(v["center_delta_vs_baseline_px"] - v["expected_delta_px"]) for v in center_known
    ]
    # Distant in recording time does not necessarily mean a different physical
    # place. This is a stress test, not labelled false-positive ground truth.
    temporal_stress = []
    for query, other in zip(selected, reversed(selected)):
        if abs(query[2] - other[3]) < 6:
            continue
        result = compare(frames[other[1]], frames[query[0]])
        temporal_stress.append(
            {
                "query_frame": query[0],
                "query_seconds": query[2],
                "reference_frame": other[1],
                "reference_seconds": other[3],
                **asdict(result),
            }
        )
    summary = {
        "schema": "offline-image-displacement-v1",
        "source_sha256": hashlib.sha256((capture / "video.h264").read_bytes()).hexdigest(),
        "same_recording": True,
        "physical_actions": 0,
        "synthetic_pixel_shifts": list(shifts),
        "selection": selection,
        "excluded_query_frames_from_prior_report": len(excluded),
        "image_size": [960, 540],
        "not_a_pose_or_steering_test": True,
        "selected_pairs": len(results),
        "measured_shift_pairs": len(known),
        "within_3_pixels": sum(e <= 3 for e in errors),
        "wrong_direction": sum(
            v["delta_vs_baseline_px"] * v["expected_delta_px"] <= 0 for v in known
        ),
        "absolute_error_px_p50": float(np.median(errors)) if errors else None,
        "absolute_error_px_p95": float(np.percentile(errors, 95)) if errors else None,
        "center_shift_pairs": len(center_known),
        "center_within_3_pixels": sum(e <= 3 for e in center_errors),
        "center_wrong_direction": sum(
            v["center_delta_vs_baseline_px"] * v["expected_delta_px"] <= 0 for v in center_known
        ),
        "center_absolute_error_px_p50": float(np.median(center_errors)) if center_errors else None,
        "center_absolute_error_px_p95": float(np.percentile(center_errors, 95))
        if center_errors
        else None,
        "compare_ms_p50": float(np.median(elapsed)),
        "compare_ms_p95": float(np.percentile(elapsed, 95)),
        "compute_excludes_decode_retrieval_transport_actions": True,
        "distant_time_stress_pairs": len(temporal_stress),
        "distant_time_stress_measured": sum(s["state"] == "measured" for s in temporal_stress),
        "distant_time_is_not_ground_truth_for_different_places": True,
        "temporal_stress": temporal_stress,
        "samples": results,
    }
    (output / "report.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("samples", "temporal_stress")}, indent=2
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("matches", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--shifts", type=int, nargs="+", default=[-24, 24])
    parser.add_argument("--selection", choices=("endpoints", "midpoints"), default="endpoints")
    parser.add_argument("--exclude-report", type=Path)
    args = parser.parse_args()
    run(
        args.capture,
        args.matches,
        args.output,
        shifts=tuple(args.shifts),
        selection=args.selection,
        exclude_report=args.exclude_report,
    )
