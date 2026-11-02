"""Same-video offline route-progress experiment; no physical or model input.

Reference and query frame indices are disjoint. Source timestamps are used only
for evaluation, not for matching. Frame time simulated for deterministic replay;
the result is not an independent run, a road model, or a steering benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections import Counter
from pathlib import Path

from motor_worker.landmarks import RouteViewMatcher, RouteViewProfile
from motor_worker.policy import PolicyFrame
from motor_worker.route_memory import RouteProgress, TaughtRoute
from motor_worker.visual_global_recovery import GlobalRecovery
from motor_worker.visual_place import VisualPlaceIndex
from motor_worker.visual_place_sequence import VisualPlaceSequence
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]
EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
EPISODE = "f3867238-d651-4ce0-9e71-e892ce6e28fb"
GOAL = "7be1db61-acab-4c6b-8bea-b5330594fdcf"


def run(
    capture: Path,
    output: Path,
    *,
    reference_interval: float = 1.0,
    compare_global: bool = False,
    compare_multi: bool = False,
    selection_strategy: str = "ranked",
):
    import av
    import cv2 as cv
    import numpy as np

    findings = evaluate(collect(ROOT), min_ram_gib=12)
    if findings:
        raise RuntimeError("resource_guard: " + ", ".join(map(str, findings)))
    cv.setNumThreads(4)
    cv.setRNGSeed(17)
    if reference_interval not in (0.5, 1.0, 2.0):
        raise ValueError("unsupported_reference_interval")
    if selection_strategy not in {"ranked", "diverse"}:
        raise ValueError("unsupported_selection_strategy")
    meta = [
        json.loads(line)
        for line in (capture / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    times = np.array([r["relative_ticks_90k"] / 90000 for r in meta])
    # Scenario is selected in advance, not by successful matching results.
    refs = [int(np.argmin(np.abs(times - t))) for t in np.arange(6.0, 14.0, reference_interval)]
    # Reserve the same dense reference set in both variants so queries are
    # identical and none can be a reference in either run.
    reserved = {int(np.argmin(np.abs(times - t))) for t in np.arange(6.0, 14.0, 0.5)}
    queries = []
    for t in np.arange(6.1, 14.0, 0.2):
        candidates = np.argsort(np.abs(times - t))
        index = next(int(i) for i in candidates if int(i) not in reserved and int(i) not in queries)
        queries.append(index)
    if len(set(refs)) != len(refs) or any(a >= b for a, b in zip(queries, queries[1:])):
        raise ValueError("offline_sampling_order")
    required = set(refs + queries)
    images, full_images = {}, {}
    with av.open(str(capture / "video.h264")) as video:
        for index, frame in enumerate(video.decode(video=0)):
            if index in required:
                rgb = frame.to_ndarray(format="rgb24")
                images[index] = cv.resize(rgb, (480, 270), interpolation=cv.INTER_AREA)
                if compare_global or compare_multi:
                    full_images[index] = cv.resize(rgb, (960, 540), interpolation=cv.INTER_AREA)
    if set(images) != required:
        raise ValueError("missing_decoded_samples")
    profile = RouteViewProfile(GOAL, 480, 270, (0, 0, 1, 1), ((0, 0, 1, 0.08), (0, 0.78, 1, 1)))
    matcher = RouteViewMatcher(profile, clock=lambda: 100.0)
    views = []
    for index in refs:
        view = matcher.learn(
            PolicyFrame(EPOCH, index + 1, 100.0, 480, 270, images[index].tobytes()),
            keyframe_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"fuflo228-frame-{index}")),
        )
        if view is None:
            raise ValueError(f"reference_features_unavailable_{index}")
        views.append(view)
    manifest_sha = hashlib.sha256((capture / "manifest.json").read_bytes()).hexdigest()
    route = TaughtRoute(
        str(uuid.uuid4()),
        GOAL,
        EPISODE,
        "vehicle",
        manifest_sha,
        profile,
        tuple(views),
        tuple(meta[i]["relative_ticks_90k"] for i in refs),
    )
    simulated = [100.0]
    progress = RouteProgress(
        route,
        capture_epoch=EPOCH,
        episode_id=EPISODE,
        goal_revision=GOAL,
        clock=lambda: simulated[0],
    )
    rows = []
    for seq, index in enumerate(queries, 1):
        simulated[0] = 100.0 + float(times[index] - times[queries[0]])
        frame = PolicyFrame(EPOCH, seq, simulated[0], 480, 270, images[index].tobytes())
        result = progress.observe(frame, episode_id=EPISODE, goal_revision=GOAL, scene="active")
        checkpoint_time = (
            None if result.checkpoint is None else float(times[refs[result.checkpoint]])
        )
        next_time = (
            None if result.next_checkpoint is None else float(times[refs[result.next_checkpoint]])
        )
        rows.append(
            {
                "frame": index,
                "seconds": float(times[index]),
                "state": result.state,
                "reason": result.reason,
                "checkpoint": result.checkpoint,
                "checkpoint_time": checkpoint_time,
                "next_checkpoint": result.next_checkpoint,
                "next_time": next_time,
                # Source time is an offline consistency check, not a physical pose truth.
                "source_time_difference": None
                if checkpoint_time is None
                else float(times[index] - checkpoint_time),
            }
        )
    tracking_rows = [r for r in rows if r["state"] == "tracking"]
    alternate = None
    if compare_global:
        import time

        place = VisualPlaceIndex(max_candidates=4)
        for index in refs:
            place.add(full_images[index], float(times[index]))
        sequence = VisualPlaceSequence(tuple(float(times[index]) for index in refs), epoch=EPOCH)
        alternative_rows = []
        for index in queries:
            start = time.perf_counter()
            candidate = place.compare(full_images[index])
            confirmed = sequence.observe(
                candidate, float(times[index]), frame_id=index, epoch=EPOCH
            )
            elapsed = (time.perf_counter() - start) * 1000
            reference_time = (
                None if confirmed.reference is None else float(times[refs[confirmed.reference]])
            )
            alternative_rows.append(
                {
                    "frame": index,
                    "seconds": float(times[index]),
                    "place_state": candidate.state,
                    "candidate_reference": candidate.reference,
                    "candidate_inliers": candidate.inliers,
                    "candidate_reason": candidate.reason,
                    "state": confirmed.state,
                    "reference": confirmed.reference,
                    "source_time_difference": None
                    if reference_time is None
                    else float(times[index] - reference_time),
                    "compute_ms": elapsed,
                }
            )
        known = [r for r in alternative_rows if r["state"] == "matched"]
        alternate = {
            "scope": "global_image_resemblance_not_route_progress_or_pose",
            "matches": dict(Counter(r["place_state"] for r in alternative_rows)),
            "sequence_states": dict(Counter(r["state"] for r in alternative_rows)),
            "matched_time_error_over_2s": sum(abs(r["source_time_difference"]) > 2 for r in known)
            if known
            else None,
            "compute_ms_p50": float(np.median([r["compute_ms"] for r in alternative_rows])),
            "compute_ms_p95": float(np.percentile([r["compute_ms"] for r in alternative_rows], 95)),
            "not_full_transport_or_control_latency": True,
            "samples": alternative_rows,
        }
    multi = None
    if compare_multi:
        import time

        place = VisualPlaceIndex(max_candidates=4)
        for index in refs:
            place.add(full_images[index], float(times[index]))
        recovery = GlobalRecovery(tuple(float(times[index]) for index in refs), epoch=EPOCH)
        multi_rows = []
        for index in queries:
            start = time.perf_counter()
            candidates = place.compare_candidates(full_images[index], strategy=selection_strategy)
            evidence = recovery.observe(
                candidates.candidates, float(times[index]), frame_id=index, epoch=EPOCH
            )
            elapsed = (time.perf_counter() - start) * 1000
            reference_time = (
                None if evidence.reference is None else float(times[refs[evidence.reference]])
            )
            multi_rows.append(
                {
                    "frame": index,
                    "seconds": float(times[index]),
                    "candidate_indices": [c.reference for c in candidates.candidates],
                    "candidate_inliers": [c.inliers for c in candidates.candidates],
                    "state": evidence.state,
                    "reference": evidence.reference,
                    "surviving": evidence.surviving,
                    "held_previous": evidence.held_previous,
                    "source_time_difference": None
                    if reference_time is None
                    else float(times[index] - reference_time),
                    "compute_ms": elapsed,
                }
            )
        known = [r for r in multi_rows if r["state"] == "hypothesis"]
        multi = {
            "scope": "multi_candidate_image_sequence_not_route_or_pose",
            "selection_strategy": selection_strategy,
            "states": dict(Counter(r["state"] for r in multi_rows)),
            "more_than_one_candidate_frames": sum(
                len(r["candidate_indices"]) > 1 for r in multi_rows
            ),
            "hypothesis_time_error_over_2s": sum(
                abs(r["source_time_difference"]) > 2 for r in known
            )
            if known
            else None,
            "compute_ms_p50": float(np.median([r["compute_ms"] for r in multi_rows])),
            "compute_ms_p95": float(np.percentile([r["compute_ms"] for r in multi_rows], 95)),
            "not_exhaustive_top_k": True,
            "not_full_transport_or_control_latency": True,
            "samples": multi_rows,
        }
    summary = {
        "schema": "route-progress-same-video-offline-v1",
        "same_recording": True,
        "independent_replay": False,
        "physical_actions": 0,
        "motor_model_used": False,
        "reference_query_indices_disjoint": not bool(set(refs) & set(queries)),
        "query_excludes_dense_reference_set": not bool(reserved & set(queries)),
        "source_sha256": hashlib.sha256((capture / "video.h264").read_bytes()).hexdigest(),
        "reference_interval_seconds": reference_interval,
        "reference_frames": refs,
        "reference_times": [float(times[i]) for i in refs],
        "queries": len(rows),
        "states": dict(Counter(r["state"] for r in rows)),
        "reasons": dict(Counter(r["reason"] for r in rows)),
        "tracking_with_next": sum(
            r["state"] == "tracking" and r["next_checkpoint"] is not None for r in rows
        ),
        "tracking_time_error_over_2s": (
            sum(abs(r["source_time_difference"]) > 2 for r in tracking_rows)
            if tracking_rows
            else None
        ),
        "no_target_while_unconfirmed": all(
            r["next_checkpoint"] is None for r in rows if r["state"] != "tracking"
        ),
        "source_time_is_evaluation_only": True,
        "simulated_clock_not_latency": True,
        "alternate_global": alternate,
        "multi_candidate": multi,
        "samples": rows,
    }
    output.mkdir(parents=False, exist_ok=False)
    (output / "report.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    printable = {
        k: v
        for k, v in summary.items()
        if k not in ("samples", "alternate_global", "multi_candidate")
    }
    printable["alternate_global"] = (
        None if alternate is None else {k: v for k, v in alternate.items() if k != "samples"}
    )
    printable["multi_candidate"] = (
        None if multi is None else {k: v for k, v in multi.items() if k != "samples"}
    )
    print(json.dumps(printable, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference-interval", type=float, choices=(0.5, 1.0, 2.0), default=1.0)
    parser.add_argument("--compare-global", action="store_true")
    parser.add_argument("--compare-multi", action="store_true")
    parser.add_argument("--selection-strategy", choices=("ranked", "diverse"), default="ranked")
    args = parser.parse_args()
    run(
        args.capture,
        args.output,
        reference_interval=args.reference_interval,
        compare_global=args.compare_global,
        compare_multi=args.compare_multi,
        selection_strategy=args.selection_strategy,
    )
