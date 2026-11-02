"""Offline image-region distribution of PnP inliers from saved matches.

Image bands are not semantic object labels; results are not navigation proof.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from motor_worker.route_localization import RouteLocalizer, SparseRoute
from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import checkpoint


def run(probe_dir, model, route_file, route_sha, output):
    import cv2
    import numpy as np
    import pycolmap

    cv2.setNumThreads(4)
    cv2.setRNGSeed(17)
    probe_dir, model, route_file, output = map(Path, (probe_dir, model, route_file, output))
    checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    report_path = probe_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    route = SparseRoute.load(route_file, sha256=route_sha)
    if (
        report.get("saved_correspondences") is not True
        or report.get("capture_manifest_sha256") != route.source_capture_sha256
        or report.get("execution_qualified") is not False
        or report.get("physical_actions") != 0
    ):
        raise ValueError("inlier_probe_binding_invalid")

    def digest(p):
        with Path(p).open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    models = sorted(model.glob("*.bin"))
    before = {str(p): digest(p) for p in [*models, report_path, route_file]}
    if not models or any(
        report.get("source_sha256", {}).get(str(p)) != before[str(p)] for p in models
    ):
        raise ValueError("inlier_model_binding_invalid")
    rec = pycolmap.Reconstruction(model)
    localizer = RouteLocalizer(
        route,
        capture_epoch=str(uuid.uuid4()),
        episode_id=str(uuid.uuid4()),
        goal_revision=str(uuid.uuid4()),
        diagnostic_partial_map=True,
        candidate_limit=5,
    )
    output.mkdir()
    write_json(
        output / "intent.json", {"scope": "offline_pnp_inlier_regions", "physical_actions": 0}
    )
    results = []
    for index, sample in enumerate(report["samples"]):
        if index % 4 == 0:
            checkpoint(output)
        successful = [c for c in sample["candidates"] if c["pnp_passed"]]
        if not successful:
            results.append(
                {
                    "source_index": sample["source_index"],
                    "seconds": sample["seconds"],
                    "state": "no_prior_pose",
                }
            )
            continue
        candidate = max(successful, key=lambda c: c["inliers"])
        name = sample["correspondence_file"]
        path = probe_dir / name
        if (
            Path(name).name != name
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 8 * 1024 * 1024
            or digest(path) != sample["correspondence_sha256"]
        ):
            raise ValueError("inlier_correspondence_integrity")
        with np.load(path, allow_pickle=False) as f:
            view, point, query, pixels = f["view"], f["point_id"], f["query_id"], f["pixels"]
            if (
                not (len(view) == len(point) == len(query) == len(pixels))
                or pixels.shape != (len(view), 2)
                or not np.isfinite(pixels).all()
            ):
                raise ValueError("inlier_correspondence_invalid")
            selected = np.flatnonzero(view == candidate["view"])
            ids = [int(point[i]) for i in selected]
            qs = [int(query[i]) for i in selected]
            if (
                len(ids) != len(set(ids))
                or len(qs) != len(set(qs))
                or any(i not in rec.points3D for i in ids)
            ):
                raise ValueError("inlier_correspondence_invalid")
            world = np.asarray([rec.points3D[i].xyz for i in ids], np.float64).reshape(-1, 3)
            xy = np.asarray(pixels[selected], np.float64).reshape(-1, 2)
            solution = localizer._verify_correspondences(world, xy) if len(ids) >= 24 else None
            if solution is None:
                results.append(
                    {
                        "source_index": sample["source_index"],
                        "seconds": sample["seconds"],
                        "view": candidate["view"],
                        "state": "repeat_not_verified",
                    }
                )
                continue
            accepted = xy[solution[4]]
            bands = [
                int(((accepted[:, 1] >= lo) & (accepted[:, 1] < hi)).sum())
                for lo, hi in ((0, 180), (180, 360), (360, 540))
            ]
            cols = [
                int(((accepted[:, 0] >= lo) & (accepted[:, 0] < hi)).sum())
                for lo, hi in ((0, 320), (320, 640), (640, 960))
            ]
            results.append(
                {
                    "source_index": sample["source_index"],
                    "seconds": sample["seconds"],
                    "view": candidate["view"],
                    "state": "verified_again",
                    "inliers": len(accepted),
                    "y_bands": bands,
                    "x_bands": cols,
                    "accepted_xy": [[float(x), float(y)] for x, y in accepted],
                    "median_error_px": solution[3],
                }
            )
    if {k: digest(k) for k in before} != before:
        raise ValueError("inlier_source_changed")
    completed = [s for s in results if s["state"] == "verified_again"]
    total = sum(s["inliers"] for s in completed)
    summary = {
        "samples": len(results),
        "verified_again": len(completed),
        "total_inliers": total,
        "y_band_counts": [sum(s["y_bands"][i] for s in completed) for i in range(3)],
        "x_band_counts": [sum(s["x_bands"][i] for s in completed) for i in range(3)],
    }
    result = {
        "schema": "sphere-pnp-inlier-regions-v1",
        "samples": results,
        "summary": summary,
        "image_size": [960, 540],
        "semantic_static_mask": False,
        "same_recording": True,
        "ground_truth": False,
        "physical_actions": 0,
        "execution_qualified": False,
    }
    write_json(output / "report.json", result)
    return result
