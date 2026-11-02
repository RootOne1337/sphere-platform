"""Replay saved per-candidate PnP inputs with the current verification gate.

Input is offline same-recording evidence, not an independent navigation test.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from motor_worker.route_localization import PNP_VERIFICATION_POLICY, RouteLocalizer, SparseRoute
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
        raise ValueError("pnp_gate_probe_binding_invalid")

    def digest(p):
        with Path(p).open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    models = sorted(model.glob("*.bin"))
    before = {str(p): digest(p) for p in [*models, report_path, route_file]}
    if not models or any(
        report.get("source_sha256", {}).get(str(p)) != before[str(p)] for p in models
    ):
        raise ValueError("pnp_gate_model_binding_invalid")
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
        output / "intent.json", {"scope": "offline_saved_candidate_gate", "physical_actions": 0}
    )
    results = []
    for index, sample in enumerate(report["samples"]):
        if index % 4 == 0:
            checkpoint(output)
        name = sample["correspondence_file"]
        path = probe_dir / name
        if (
            Path(name).name != name
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 8 * 1024 * 1024
            or digest(path) != sample["correspondence_sha256"]
        ):
            raise ValueError("pnp_gate_correspondence_integrity")
        views = []
        with np.load(path, allow_pickle=False) as f:
            view, point, query, pixels = f["view"], f["point_id"], f["query_id"], f["pixels"]
            if (
                not (len(view) == len(point) == len(query) == len(pixels))
                or pixels.shape != (len(view), 2)
                or not np.isfinite(pixels).all()
            ):
                raise ValueError("pnp_gate_correspondence_invalid")
            for candidate in sample["candidates"]:
                indices = np.flatnonzero(view == candidate["view"])
                ids = [int(point[i]) for i in indices]
                qs = [int(query[i]) for i in indices]
                if (
                    len(ids) != len(set(ids))
                    or len(qs) != len(set(qs))
                    or any(i not in rec.points3D for i in ids)
                ):
                    raise ValueError("pnp_gate_correspondence_invalid")
                world = np.asarray([rec.points3D[i].xyz for i in ids], np.float64).reshape(-1, 3)
                xy = np.asarray(pixels[indices], np.float64).reshape(-1, 2)
                solved = localizer._verify_correspondences(world, xy) if len(ids) >= 24 else None
                views.append(
                    {
                        "view": candidate["view"],
                        "old_pnp": candidate["pnp_passed"],
                        "current_pnp": solved is not None,
                        "current_inliers": None if solved is None else solved[2],
                    }
                )
        results.append(
            {
                "source_index": sample["source_index"],
                "seconds": sample["seconds"],
                "candidates": views,
            }
        )
    if {k: digest(k) for k in before} != before:
        raise ValueError("pnp_gate_source_changed")
    result = {
        "schema": "sphere-saved-pnp-gate-replay-v1",
        "samples": results,
        "old_any": sum(any(c["old_pnp"] for c in s["candidates"]) for s in results),
        "current_any": sum(any(c["current_pnp"] for c in s["candidates"]) for s in results),
        "verification_policy": PNP_VERIFICATION_POLICY,
        "same_recording": True,
        "ground_truth": False,
        "physical_actions": 0,
        "execution_qualified": False,
    }
    write_json(output / "report.json", result)
    return result
