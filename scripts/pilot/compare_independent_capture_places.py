"""Compare a recorded route with another capture, without movement or pose claims."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import av
import cv2 as cv
import numpy as np

from motor_worker.browser_teach import browser_units, validate_browser
from motor_worker.visual_global_recovery import GlobalRecovery
from motor_worker.visual_place import VisualPlaceIndex
from scripts.pilot.atomic_json import write_json
from scripts.pilot.resource_guard import collect, evaluate


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(path, wanted):
    result = {}
    with av.open(str(path)) as video:
        for index, frame in enumerate(video.decode(video=0)):
            if index in wanted:
                rgb = frame.to_ndarray(format="rgb24")
                result[index] = cv.resize(rgb, (960, 540), interpolation=cv.INTER_AREA)
            if len(result) == len(wanted):
                break
    if set(result) != set(wanted):
        raise ValueError("requested_frame_missing")
    return result


def sample_frames(times, *, start=0.2, end=10.2, step=0.2):
    """Select increasing source IDs before matching, without reusing a frame."""
    values = np.asarray(times, dtype=np.float64)
    if (
        values.ndim != 1
        or len(values) < 2
        or not np.isfinite(values).all()
        or values[0] < 0
        or np.any(np.diff(values) <= 0)
        or not all(np.isfinite(v) for v in (start, end, step))
        or not 0 <= start < end
        or step <= 0
    ):
        raise ValueError("query_sampling_invalid")
    indices = []
    for t in np.arange(start, min(end, values[-1]), step):
        index = int(np.argmin(np.abs(values - t)))
        if not indices or index > indices[-1]:
            indices.append(index)
    if not 4 <= len(indices) <= 50:
        raise ValueError("query_sampling_invalid")
    return indices


def run(reference: Path, query: Path, prior: Path, output: Path, *, query_start=0.2):
    if output.exists():
        raise ValueError("output_exists")
    findings = evaluate(collect(Path.cwd()), min_ram_gib=12)
    if findings:
        raise RuntimeError("resource_guard:" + ",".join(findings))
    first, second = validate_browser(reference), validate_browser(query)
    if first.manifest["id"] == second.manifest["id"]:
        raise ValueError("captures_not_independent")
    for capture in (first, second):
        for _ in browser_units(capture):
            pass
    before = {
        name: sha(root / "video.h264")
        for name, root in (("reference", reference), ("query", query))
    }
    if before["reference"] == before["query"]:
        raise ValueError("captures_not_independent")
    saved = json.loads(prior.read_text("utf-8"))
    if saved["source_sha256"] != before["reference"] or saved["physical_actions"] != 0:
        raise ValueError("reference_binding_changed")
    references = saved["reference_frames"]
    reference_times = tuple(saved["reference_times"])
    if (
        len(references) != len(reference_times)
        or len(set(references)) != len(references)
        or any(type(i) is not int or not 0 <= i < len(first.frames) for i in references)
        or any(
            abs(first.frames[i]["relative_ticks_90k"] / 90000 - t) > 1e-9
            for i, t in zip(references, reference_times, strict=True)
        )
    ):
        raise ValueError("reference_frames_invalid")
    times = np.array([row["relative_ticks_90k"] / 90000 for row in second.frames])
    # One continuous, fixed-in-advance 10-second segment. No claim that the
    # second capture shows the same or a different physical place.
    indices = sample_frames(times, start=query_start, end=query_start + 10.0)
    cv.setNumThreads(4)
    cv.setRNGSeed(17)
    ref_images = extract(reference / "video.h264", set(references))
    query_images = extract(query / "video.h264", set(indices))
    index = VisualPlaceIndex(max_candidates=4)
    for frame, seconds in zip(references, reference_times, strict=True):
        index.add(ref_images[frame], seconds)
    results = {}
    for strategy in ("ranked", "diverse"):
        tracker = GlobalRecovery(reference_times, epoch="independent-recording")
        samples = []
        for frame in indices:
            started = time.perf_counter()
            candidates = index.compare_candidates(query_images[frame], strategy=strategy)
            result = tracker.observe(
                candidates.candidates,
                float(times[frame]),
                frame_id=frame,
                epoch="independent-recording",
            )
            samples.append(
                dict(
                    frame=frame,
                    seconds=float(times[frame]),
                    state=result.state,
                    reference=result.reference,
                    reference_seconds=None
                    if result.reference is None
                    else reference_times[result.reference],
                    candidates=[c.reference for c in candidates.candidates],
                    held_previous=result.held_previous,
                    reference_streak=result.reference_streak,
                    reference_streak_seconds=result.reference_streak_seconds,
                    near_reference_tail=result.near_reference_tail,
                    compute_ms=(time.perf_counter() - started) * 1000,
                )
            )
        results[strategy] = dict(
            states=dict(Counter(row["state"] for row in samples)),
            candidate_frames=sum(bool(row["candidates"]) for row in samples),
            p50_ms=float(np.median([r["compute_ms"] for r in samples])),
            p95_ms=float(np.percentile([r["compute_ms"] for r in samples], 95)),
            samples=samples,
        )
    if before != {
        name: sha(root / "video.h264")
        for name, root in (("reference", reference), ("query", query))
    }:
        raise ValueError("source_changed")
    output.mkdir(parents=False)
    report = dict(
        schema="sphere-place-other-capture-v1",
        source_sha256=before,
        distinct_recordings=True,
        same_place_ground_truth_known=False,
        query_start_seconds=float(times[indices[0]]),
        query_end_seconds=float(times[indices[-1]]),
        query_frames=len(indices),
        reference_frames=len(references),
        results=results,
        physical_actions=0,
        execution_qualified=False,
        limitations="Unlabelled other recording; no pose, road, obstacle, or full end-to-end timing truth.",
    )
    write_json(output / "report.json", report)
    return report


if __name__ == "__main__":
    import argparse

    base = Path(".local-pilot/fuflo228-20261027")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, default=base / "source")
    parser.add_argument(
        "--query",
        type=Path,
        default=Path(".local-pilot/reconstruction-jobs/b7bce94214db48e195dea1a2ac65faf2/input"),
    )
    parser.add_argument(
        "--prior", type=Path, default=base / "visual-place-multicandidate-diverse-v2/report.json"
    )
    parser.add_argument("--output", type=Path, default=base / "visual-place-other-capture-v1")
    parser.add_argument("--query-start", type=float, default=0.2)
    args = parser.parse_args()
    data = run(args.reference, args.query, args.prior, args.output, query_start=args.query_start)
    print(
        json.dumps(
            {
                k: {x: v for x, v in value.items() if x != "samples"}
                for k, value in data["results"].items()
            }
        )
    )
