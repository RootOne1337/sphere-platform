"""Read-only bounded pair diagnostics on previously extracted PNG frames.

Uses 960x540, one pair, one CPU thread and no GPU/torch/models/reconstruction.
Pairwise geometric inliers are not world positions, pose accuracy, road or
navigation evidence. Input PNGs and video are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from scripts.pilot.resource_guard import windows_memory


def memory_checkpoint():
    # Separate bounded lightweight diagnostic admission, not a change or bypass
    # to the 12 GiB heavy SfM/model resource guard. This never starts SfM.
    s = windows_memory()
    if (
        s["availableRamBytes"] < 4 * 2**30
        or s["commitLimitBytes"] - s["committedBytes"] < 4 * 2**30
    ):
        raise RuntimeError("lightweight_diagnostic_memory_low")


def inspect(a, b, kind):
    import cv2 as cv
    import numpy as np

    mask = np.zeros((540, 960), np.uint8)
    mask[45:420, 15:945] = 255
    detector = (
        cv.ORB_create(nfeatures=2400, fastThreshold=9)
        if kind == "orb"
        else cv.SIFT_create(nfeatures=2400)
    )
    start = time.perf_counter()
    ka, da = detector.detectAndCompute(cv.cvtColor(a, cv.COLOR_BGR2GRAY), mask)
    kb, db = detector.detectAndCompute(cv.cvtColor(b, cv.COLOR_BGR2GRAY), mask)
    summary = {
        "method": kind,
        "features": [len(ka), len(kb)],
        "matches": 0,
        "homography_inliers": None,
        "fundamental_inliers": None,
    }
    if da is not None and db is not None and len(db) >= 2:
        norm = cv.NORM_HAMMING if kind == "orb" else cv.NORM_L2
        pairs = cv.BFMatcher(norm).knnMatch(da, db, k=2)
        good = [
            m
            for pair in pairs
            if len(pair) == 2
            for m, n in [pair]
            if m.distance < 0.75 * n.distance
        ]
        good = list(
            {m.trainIdx: m for m in sorted(good, key=lambda m: m.distance, reverse=True)}.values()
        )
        summary["matches"] = len(good)
        if len(good) >= 20:
            pa = np.float32([ka[m.queryIdx].pt for m in good])
            pb = np.float32([kb[m.trainIdx].pt for m in good])
            for model in ("homography", "fundamental"):
                cv.setRNGSeed(17)
                try:
                    matrix, keep = (
                        cv.findHomography(pa, pb, cv.RANSAC, 3.0)
                        if model == "homography"
                        else cv.findFundamentalMat(pa, pb, cv.FM_RANSAC, 1.5, 0.995)
                    )
                except cv.error:
                    # E.g. repeated views can be degenerate for F. Keep this
                    # model unknown rather than discarding the other result.
                    summary[model + "_error"] = "estimation_failed_or_degenerate"
                    continue
                if matrix is not None and keep is not None and np.isfinite(matrix).all():
                    accepted = keep.ravel().astype(bool)
                    summary[model + "_inliers"] = int(accepted.sum())
                    summary[model + "_occupied_cells"] = min(
                        len({(int(x // 240), int(y // 180)) for x, y in p[accepted]})
                        for p in (pa, pb)
                    )
    summary["compute_ms"] = round((time.perf_counter() - start) * 1000, 1)
    return summary


def run(audit_path, images_dir, output):
    import cv2 as cv

    if output.exists():
        raise FileExistsError("output_exists")
    cv.setNumThreads(1)
    memory_checkpoint()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    by_frame = {r["source_frame"]: r for r in audit["rows"]}
    # Exact source frames, selected before inspecting the pairwise results.
    pairs = ((299, 309), (323, 336), (772, 788), (804, 818), (873, 888), (905, 914))
    rows = []
    for left, right in pairs:
        memory_checkpoint()
        if left not in by_frame or right not in by_frame:
            raise ValueError("selected_pair_not_in_saved_sfm")
        arrays = []
        for frame in (left, right):
            path = images_dir / f"{frame:08d}.png"
            img = cv.imread(str(path), cv.IMREAD_REDUCED_COLOR_2)
            if img is None or img.shape != (540, 960, 3):
                raise ValueError("unexpected_saved_image_geometry")
            arrays.append(img)
        methods = [inspect(*arrays, kind) for kind in ("orb", "sift")]
        rows.append(
            {
                "frames": [left, right],
                "seconds": [by_frame[left]["seconds"], by_frame[right]["seconds"]],
                "primary_registered": [
                    by_frame[left]["registered_primary"],
                    by_frame[right]["registered_primary"],
                ],
                "methods": methods,
            }
        )
        del arrays
    report = {
        "schema": "sfm-saved-frame-pairs-lightweight-v1",
        "scope": "pairwise_not_reconstruction",
        "source_audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        "source_pngs_modified": False,
        "source_video_modified": False,
        "physical_actions": 0,
        "semantic_dynamic_mask": False,
        "pairwise_inliers_not_pose_or_route": True,
        "opencv_threads": 1,
        "dimensions": [960, 540],
        "pairs": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2, allow_nan=False)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("audit", type=Path)
    p.add_argument("images", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    run(args.audit, args.images, args.output)
