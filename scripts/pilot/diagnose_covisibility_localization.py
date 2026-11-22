"""Compare offline PnP using covisible groups of saved query matches.

Groups use only reference-model tracks; media timestamps are never used for
selection. Results remain same-recording diagnostic evidence, not an actuator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from motor_worker.route_localization import RouteLocalizer, SparseRoute
from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import checkpoint


def covisibility_groups(views, tracks):
    if len(set(views)) != len(views) or any(v not in tracks for v in views):
        raise ValueError("covisibility_views_invalid")
    remaining = set(views)
    groups = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        group = {start}
        queue = [start]
        while queue:
            head = queue.pop()
            linked = {v for v in remaining if tracks[head] & tracks[v]}
            remaining -= linked
            group.update(linked)
            queue.extend(sorted(linked))
        groups.append(tuple(sorted(group)))
    return groups


def unique_votes(rows):
    """Require unique winning 3D point per 2D query and vice versa."""
    by_query = defaultdict(Counter)
    for view, point, query in rows:
        by_query[query][point] += 1
    proposals = []
    for query, votes in by_query.items():
        ranked = votes.most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue
        proposals.append((ranked[0][1], query, ranked[0][0]))
    chosen = []
    points = set()
    for votes, query, point in sorted(proposals, key=lambda x: (-x[0], x[1], x[2])):
        if point not in points:
            points.add(point)
            chosen.append((query, point, votes))
    return chosen


def run(probe_dir, model, provenance, route_file, route_sha, output):
    import cv2
    import numpy as np
    import pycolmap

    cv2.setNumThreads(4)
    cv2.setRNGSeed(17)
    probe_dir, model, provenance, output = map(Path, (probe_dir, model, provenance, output))
    checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    report_path = probe_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    route = SparseRoute.load(route_file, sha256=route_sha)
    if (
        report.get("saved_correspondences") is not True
        or report.get("same_capture") is not True
        or report.get("capture_manifest_sha256") != route.source_capture_sha256
        or report.get("physical_actions") != 0
        or report.get("execution_qualified") is not False
    ):
        raise ValueError("covisibility_probe_binding_invalid")
    source = json.loads(provenance.read_text(encoding="utf-8"))
    if source.get("source_manifest_sha256") != route.source_capture_sha256:
        raise ValueError("covisibility_source_binding_invalid")
    model_files = sorted(model.glob("*.bin"))

    def digest(p):
        with p.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    before = {str(p): digest(p) for p in [*model_files, provenance, report_path, Path(route_file)]}
    if any(
        report.get("source_sha256", {}).get(str(p)) != before[str(p)]
        for p in [*model_files, provenance]
    ):
        raise ValueError("covisibility_model_binding_invalid")
    rec = pycolmap.Reconstruction(model)
    rows = {Path(r["image"]).name: r for r in source["images"]}
    images = sorted(rec.images.values(), key=lambda im: rows[im.name]["relative_ticks_90k"])
    if len(images) != len(route.camera_trace):
        raise ValueError("covisibility_model_binding_invalid")
    tracks = {
        i: {int(pt.point3D_id) for pt in im.points2D if pt.has_point3D()}
        for i, im in enumerate(images)
    }
    probe = RouteLocalizer(
        route,
        capture_epoch=str(uuid.uuid4()),
        episode_id=str(uuid.uuid4()),
        goal_revision=str(uuid.uuid4()),
        diagnostic_partial_map=True,
        candidate_limit=5,
    )
    output.mkdir()
    write_json(output / "intent.json", {"scope": "offline_covisibility_pnp", "physical_actions": 0})
    samples = []
    for n, sample in enumerate(report["samples"]):
        if n % 4 == 0:
            checkpoint(output)
        name = sample["correspondence_file"]
        if Path(name).name != name:
            raise ValueError("covisibility_correspondence_path")
        path = probe_dir / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 8 * 1024 * 1024
            or digest(path) != sample["correspondence_sha256"]
        ):
            raise ValueError("covisibility_correspondence_integrity")
        with np.load(path, allow_pickle=False) as data:
            view = data["view"]
            point = data["point_id"]
            query = data["query_id"]
            pixels = data["pixels"]
            if (
                not (len(view) == len(point) == len(query) == len(pixels))
                or pixels.shape != (len(view), 2)
                or not np.isfinite(pixels).all()
            ):
                raise ValueError("covisibility_correspondence_invalid")
            views = [c["view"] for c in sample["candidates"]]
            if not set(map(int, view)).issubset(set(views)) or any(int(q) < 0 for q in query):
                raise ValueError("covisibility_correspondence_invalid")
            candidates = []
            for group in covisibility_groups(views, tracks):
                group_started = time.perf_counter()
                chosen_rows = []
                pixel_map = {}
                for v, p, q, xy in zip(view, point, query, pixels):
                    if int(v) not in group:
                        continue
                    if int(p) not in tracks[int(v)]:
                        raise ValueError("covisibility_point_not_observed")
                    if int(q) in pixel_map and not np.allclose(pixel_map[int(q)], xy, atol=1e-5):
                        raise ValueError("covisibility_query_pixel_mismatch")
                    pixel_map[int(q)] = xy
                    chosen_rows.append((int(v), int(p), int(q)))
                chosen = unique_votes(chosen_rows)
                xyz = np.asarray(
                    [rec.points3D[p].xyz for q, p, v in chosen], dtype=np.float64
                ).reshape(-1, 3)
                xy = np.asarray([pixel_map[q] for q, p, v in chosen], dtype=np.float64).reshape(
                    -1, 2
                )
                result = probe._verify_correspondences(xyz, xy) if len(chosen) >= 24 else None
                candidates.append(
                    {
                        "views": list(group),
                        "raw_matches": len(chosen_rows),
                        "unique_correspondences": len(chosen),
                        "pnp_passed": result is not None,
                        "inliers": None if result is None else result[2],
                        "median_error_px": None if result is None else result[3],
                        "compute_ms": (time.perf_counter() - group_started) * 1000,
                        "center": None if result is None else [float(x) for x in result[0]],
                    }
                )
        samples.append(
            {
                "source_index": sample["source_index"],
                "seconds": sample["seconds"],
                "original_any_pnp": any(c["pnp_passed"] for c in sample["candidates"]),
                "groups": candidates,
            }
        )
    if {p: digest(Path(p)) for p in before} != before:
        raise ValueError("covisibility_source_changed")
    result = {
        "schema": "sphere-covisibility-pnp-probe-v1",
        "samples": samples,
        "same_capture": True,
        "temporal_oracle_used_for_selection": False,
        "independent_pass": False,
        "physical_actions": 0,
        "execution_qualified": False,
        "source_bindings": before,
    }
    write_json(output / "report.json", result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("probe-dir", "model", "provenance", "route", "sha", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    r = run(a.probe_dir, a.model, a.provenance, a.route, a.sha, a.output)
    print(
        json.dumps(
            {
                "samples": len(r["samples"]),
                "group_pnp_passed": sum(
                    any(g["pnp_passed"] for g in s["groups"]) for s in r["samples"]
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
