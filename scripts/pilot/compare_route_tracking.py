"""Finite read-only same-recording tracker comparison. No new world truth.

Reference source indices/RGBs are excluded in both runs. Pose agreement is with
the baseline map/localizer, not metric accuracy or an independent-game-session
test. Original capture and reconstruction files are never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from motor_worker.route_localization import SparseRoute
from scripts.pilot.atomic_json import write_json
from scripts.pilot.check_route_localization import check
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]


def checkpoint(job):
    if (job/"CANCEL").exists():
        raise RuntimeError("cancelled")
    snapshot = collect(ROOT)
    findings = evaluate(snapshot, min_ram_gib=12)
    if findings:
        if job.is_dir():
            write_json(job/"resource-refusal.json", dict(snapshot=snapshot, findings=findings))
        raise RuntimeError("resource_guard")


def summarize(first, second, route):
    import numpy as np

    a, b = first["samples"], second["samples"]
    if (first["capture_manifest_sha256"] != second["capture_manifest_sha256"]
            or [(x["source_index"], x["media_seconds"]) for x in a]
            != [(x["source_index"], x["media_seconds"]) for x in b]):
        raise ValueError("tracking_comparison_different_queries")
    scale = float(np.median(np.linalg.norm(np.diff(route.camera_trace, axis=0), axis=1)))
    comparisons = []
    for x, y in zip(a, b):
        both = all(row["pose"]["state"] == "localized" for row in (x, y))
        item = dict(index=x["source_index"], seconds=x["media_seconds"],
                    baseline=x["pose"]["state"], tracked=y["pose"]["state"],
                    method=y["tracking"]["method"])
        if both:
            item["center_difference_reference_steps"] = float(np.linalg.norm(
                np.array(x["pose"]["center"])-np.array(y["pose"]["center"]))/scale)
            A, B = (np.reshape(row["pose"]["rotation"], (3, 3)) for row in (x, y))
            item["rotation_difference_degrees"] = float(np.degrees(np.arccos(np.clip(
                (np.trace(A@B.T)-1)/2, -1, 1))))
        comparisons.append(item)

    def percentiles(values):
        return None if not values else dict(p50=float(np.median(values)), p95=float(np.percentile(values, 95)),
                                           maximum=float(max(values)))

    return dict(schema="sphere-anchored-tracking-comparison-v1", physical_actions=0,
        independent_new_session=False, offline_media_clock=True, navigation_qualified=False,
        metric_accuracy_known=False, camera_body_transform_known=False,
        reference_source_indices_excluded=first["reference_indices_excluded"],
        total=len(a), counts=dict(descriptor=first["counts"], anchored_flow=second["counts"]),
        compute_ms=dict(descriptor=first["compute_ms"], anchored_flow=second["compute_ms"]),
        method_counts=dict(Counter(row["method"] for row in comparisons)),
        baseline_localized_but_tracking_not=sum(row["baseline"] == "localized" and row["tracked"] != "localized"
                                               for row in comparisons),
        tracking_localized_but_baseline_not=sum(row["tracked"] == "localized" and row["baseline"] != "localized"
                                               for row in comparisons),
        center_agreement_reference_steps=percentiles([r["center_difference_reference_steps"]
                                                    for r in comparisons if "center_difference_reference_steps" in r]),
        rotation_agreement_degrees=percentiles([r["rotation_difference_degrees"]
                                               for r in comparisons if "rotation_difference_degrees" in r]),
        # Agreement may be excellent even if both share a wrong map. No automatic adoption.
        default_localizer_changed=False, samples=comparisons)


def compare(capture, route_path, sha256, output, *, threads=4):
    import cv2 as cv

    output = Path(output)
    if type(threads) is not int or not 1 <= threads <= 8:
        raise ValueError("tracking_comparison_thread_budget")
    checkpoint(output)
    output.mkdir(exist_ok=False)
    route = SparseRoute.load(route_path, sha256=sha256)
    write_json(output/"intent.json", dict(scope="OFFLINE_ANCHORED_TRACKER_COMPARISON",
        route_sha256=sha256, physical_actions=0, original_files_modified=False))
    reports = []
    for kind in ("descriptor", "anchored_flow"):
        cv.setNumThreads(threads)
        cv.setRNGSeed(17)
        check(capture, route, output/kind, tracker_kind=kind, checkpoint_fn=checkpoint)
        reports.append(json.loads((output/kind/"report.json").read_bytes()))
    result = summarize(*reports, route)
    result["route_sha256"] = sha256
    result["opencv_threads"] = threads
    result["resource_guard_min_ram_gib"] = 12
    result["capture_manifest_sha256"] = reports[0]["capture_manifest_sha256"]
    result["report_sha256"] = {kind: hashlib.sha256((output/kind/"report.json").read_bytes()).hexdigest()
                               for kind in ("descriptor", "anchored_flow")}
    write_json(output/"comparison.json", result)
    return {k: v for k, v in result.items() if k != "samples"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "route", "sha256", "output"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(compare(args.capture, args.route, args.sha256, args.output, threads=args.threads), indent=2))


if __name__ == "__main__":
    main()
