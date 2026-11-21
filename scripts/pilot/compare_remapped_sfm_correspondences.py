"""Replay saved LightGlue matches through a second SfM model, offline only.

Both models must use the same keypoint indices and source recording. Similarity
alignment is fitted only to earlier reference cameras; it is not ground truth.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from motor_worker.route_localization import RouteLocalizer, SparseRoute
from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import checkpoint


def fit_similarity(source, target):
    import numpy as np

    x, y = np.asarray(source, float), np.asarray(target, float)
    if (
        x.ndim != 2
        or x.shape != y.shape
        or x.shape[1] != 3
        or len(x) < 4
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
    ):
        raise ValueError("remap_alignment_invalid")
    mx, my = x.mean(axis=0), y.mean(axis=0)
    xc, yc = x - mx, y - my
    if np.linalg.matrix_rank(xc) < 2:
        raise ValueError("remap_alignment_degenerate")
    u, s, vt = np.linalg.svd(xc.T @ yc / len(x))
    sign = np.ones(3)
    if np.linalg.det(vt.T @ u.T) < 0:
        sign[-1] = -1
    rotation = vt.T @ np.diag(sign) @ u.T
    variance = float(np.sum(xc * xc) / len(x))
    scale = float(np.sum(s * sign) / variance)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("remap_alignment_invalid")
    return scale, rotation, my - scale * (rotation @ mx)


def run(
    saved_probe, original_model, candidate_model, provenance, candidate_route, candidate_sha, output
):
    import cv2
    import numpy as np
    import pycolmap

    cv2.setNumThreads(4)
    cv2.setRNGSeed(17)
    saved_probe, original_model, candidate_model, provenance, output = map(
        Path, (saved_probe, original_model, candidate_model, provenance, output)
    )
    checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    report_path = saved_probe / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    route = SparseRoute.load(candidate_route, sha256=candidate_sha)
    if (
        report.get("saved_correspondences") is not True
        or report.get("capture_manifest_sha256") != route.source_capture_sha256
        or report.get("execution_qualified") is not False
        or report.get("physical_actions") != 0
    ):
        raise ValueError("remap_probe_binding_invalid")
    source = json.loads(provenance.read_text(encoding="utf-8"))
    if source.get("source_manifest_sha256") != route.source_capture_sha256:
        raise ValueError("remap_source_binding_invalid")

    def digest(p):
        with Path(p).open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    paths = [
        *sorted(original_model.glob("*.bin")),
        *sorted(candidate_model.glob("*.bin")),
        provenance,
        report_path,
        Path(candidate_route),
    ]
    before = {str(p): digest(p) for p in paths}
    if any(
        report.get("source_sha256", {}).get(str(p)) != before[str(p)]
        for p in sorted(original_model.glob("*.bin"))
    ):
        raise ValueError("remap_original_model_changed")
    old, new = pycolmap.Reconstruction(original_model), pycolmap.Reconstruction(candidate_model)
    rows = {Path(r["image"]).name: r for r in source["images"]}
    old_images = sorted(old.images.values(), key=lambda im: rows[im.name]["relative_ticks_90k"])
    new_by_name = {im.name: im for im in new.images.values()}
    if len(old_images) != len(route.camera_trace) or set(im.name for im in old_images) != set(
        new_by_name
    ):
        raise ValueError("remap_model_views_mismatch")
    prior = [im for im in old_images if 25 <= rows[im.name]["relative_ticks_90k"] / 90000 < 28.5]
    target = np.asarray([im.cam_from_world().inverse().translation for im in prior])
    original = np.asarray(
        [new_by_name[im.name].cam_from_world().inverse().translation for im in prior]
    )
    scale, rotation, translation = fit_similarity(original, target)
    old_step = float(np.median(np.linalg.norm(np.diff(target, axis=0), axis=1)))
    if not np.isfinite(old_step) or old_step <= 1e-8:
        raise ValueError("remap_alignment_degenerate")
    fit_errors = (
        np.linalg.norm((scale * (rotation @ original.T)).T + translation - target, axis=1)
        / old_step
    )
    mappings = {}
    for view, im in enumerate(old_images):
        other = new_by_name[im.name]
        if im.image_id != other.image_id or len(im.points2D) != len(other.points2D):
            raise ValueError("remap_keypoint_identity_mismatch")
        mapping = {}
        for idx, (a, b) in enumerate(zip(im.points2D, other.points2D)):
            if np.linalg.norm(a.xy - b.xy) > 1e-4:
                raise ValueError("remap_keypoint_identity_mismatch")
            if (
                a.has_point3D()
                and b.has_point3D()
                and len(new.points3D[b.point3D_id].track.elements) >= 3
            ):
                mapping[int(a.point3D_id)] = int(b.point3D_id)
        mappings[view] = mapping
    probe = RouteLocalizer(
        route,
        capture_epoch=str(uuid.uuid4()),
        episode_id=str(uuid.uuid4()),
        goal_revision=str(uuid.uuid4()),
        diagnostic_partial_map=True,
        candidate_limit=5,
    )
    output.mkdir()
    write_json(
        output / "intent.json", {"scope": "offline_correspondence_remap", "physical_actions": 0}
    )
    results = []
    for index, sample in enumerate(report["samples"]):
        if index % 4 == 0:
            checkpoint(output)
        name = sample["correspondence_file"]
        path = saved_probe / name
        if (
            Path(name).name != name
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 8 * 1024 * 1024
            or digest(path) != sample["correspondence_sha256"]
        ):
            raise ValueError("remap_correspondence_integrity")
        candidates = []
        with np.load(path, allow_pickle=False) as f:
            view, point, query, pixels = f["view"], f["point_id"], f["query_id"], f["pixels"]
            if (
                not (len(view) == len(point) == len(query) == len(pixels))
                or pixels.shape != (len(view), 2)
                or not np.isfinite(pixels).all()
            ):
                raise ValueError("remap_correspondence_invalid")
            for old_candidate in sample["candidates"]:
                at = old_candidate["view"]
                if at not in mappings:
                    raise ValueError("remap_view_invalid")
                selected = {}
                used_query = set()
                for v, p, q, xy in zip(view, point, query, pixels):
                    if int(v) != at:
                        continue
                    new_id = mappings[at].get(int(p))
                    if new_id is None or new_id in selected or int(q) in used_query:
                        continue
                    selected[new_id] = xy
                    used_query.add(int(q))
                xyz = np.asarray([new.points3D[p].xyz for p in selected], np.float64).reshape(-1, 3)
                xy = np.asarray(list(selected.values()), np.float64).reshape(-1, 2)
                sol = probe._verify_correspondences(xyz, xy) if len(selected) >= 24 else None
                aligned = None if sol is None else scale * (rotation @ sol[0]) + translation
                oldcenter = old_candidate["center"]
                disagreement = (
                    None
                    if aligned is None or oldcenter is None
                    else float(np.linalg.norm(aligned - np.asarray(oldcenter)) / old_step)
                )
                candidates.append(
                    {
                        "view": at,
                        "remapped_matches": len(selected),
                        "original_pnp": old_candidate["pnp_passed"],
                        "new_pnp": sol is not None,
                        "new_inliers": None if sol is None else sol[2],
                        "new_center": None if sol is None else [float(x) for x in sol[0]],
                        "same_candidate_disagreement_old_steps": disagreement,
                    }
                )
        results.append(
            {
                "source_index": sample["source_index"],
                "seconds": sample["seconds"],
                "candidates": candidates,
            }
        )
    if {p: digest(p) for p in before} != before:
        raise ValueError("remap_source_changed")
    result = {
        "schema": "sphere-remapped-sfm-correspondences-v1",
        "samples": results,
        "alignment_fit_views": len(prior),
        "alignment_scale": float(scale),
        "alignment_fit_median_old_steps": float(np.median(fit_errors)),
        "alignment_fit_p95_old_steps": float(np.percentile(fit_errors, 95)),
        "old_median_step_units": old_step,
        "same_recording": True,
        "ground_truth": False,
        "metric_scale": None,
        "physical_actions": 0,
        "execution_qualified": False,
        "source_sha256": before,
    }
    write_json(output / "report.json", result)
    return result
