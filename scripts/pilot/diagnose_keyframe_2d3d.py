"""Offline comparison of query-to-reference 2D matching followed by 3D PnP.

Temporal-nearest results are an oracle diagnostic of the *same* recording,
never a live localization method or a navigation permit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

from motor_worker.browser_teach import decoded_browser, validate_browser
from motor_worker.policy import PolicyFrame
from motor_worker.route_localization import (
    SIZE,
    RouteLocalizer,
    SparseRoute,
    extract_features,
    feature_mask,
)
from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import checkpoint


def unique_correspondences(pairs):
    """Use the smallest descriptor distance, once per query and 3D point."""
    selected, seen_query, seen_points = [], set(), set()
    for _, query_idx, point_id in sorted(pairs):
        if query_idx in seen_query or point_id in seen_points:
            continue
        seen_query.add(query_idx)
        seen_points.add(point_id)
        selected.append((query_idx, point_id))
    return selected


def run(
    capture,
    prepared,
    model,
    route_path,
    route_sha,
    heldout_report,
    retrieval_report,
    output,
    *,
    full_resolution=False,
):
    import cv2 as cv
    import numpy as np
    import pycolmap

    out = Path(output)
    checkpoint(out.parent)
    out.mkdir(exist_ok=False)
    write_json(
        out / "intent.json", {"scope": "offline_same_recording_keyframe_pnp", "physical_actions": 0}
    )
    started = time.monotonic()

    def bounded():
        if time.monotonic() - started > 300:
            raise RuntimeError("keyframe_probe_timeout")
        checkpoint(out)

    prepared, model = Path(prepared), Path(model)
    route = SparseRoute.load(route_path, sha256=route_sha)
    rec = pycolmap.Reconstruction(model)
    source = json.loads((prepared / "reconstruction-input.json").read_text(encoding="utf-8"))
    rows = {Path(r["image"]).name: r for r in source["images"]}
    images = sorted(rec.images.values(), key=lambda im: rows[im.name]["relative_ticks_90k"])
    if len(images) != len(route.camera_trace):
        raise ValueError("keyframe_model_mismatch")
    mask, references = feature_mask(route.profile), []
    db = (
        sqlite3.connect((prepared / "database.db").resolve().as_uri() + "?mode=ro", uri=True)
        if full_resolution
        else None
    )
    for at, im in enumerate(images):
        if at % 8 == 0:
            bounded()
        image = prepared / "images" / im.name
        if (
            image.is_symlink()
            or hashlib.sha256(image.read_bytes()).hexdigest() != rows[im.name]["png_sha256"]
        ):
            raise ValueError("keyframe_image_integrity")
        bgr = cv.imread(str(image))
        if bgr is None:
            raise ValueError("keyframe_image_decode")
        rgb = cv.cvtColor(
            cv.resize(
                bgr, (route.profile.width, route.profile.height), interpolation=cv.INTER_AREA
            ),
            cv.COLOR_BGR2RGB,
        )
        frame = PolicyFrame(
            str(uuid.uuid4()), at + 1, 0.0, route.profile.width, route.profile.height, rgb.tobytes()
        )
        if full_resolution:
            entry = db.execute(
                "SELECT rows,cols,data FROM descriptors WHERE image_id=?", (im.image_id,)
            ).fetchone()
            if not entry or entry[1] != 128 or len(entry[2]) != entry[0] * 128:
                raise ValueError("keyframe_descriptors_invalid")
            desc = (
                np.frombuffer(entry[2], np.uint8).reshape(entry[0], 128).astype(np.float32) / 512.0
            )
            desc /= np.maximum(np.linalg.norm(desc, axis=1, keepdims=True), 1e-8)
            pixels = np.empty((len(desc), 2), np.float64)
            assoc = {
                i: int(pt.point3D_id)
                for i, pt in enumerate(im.points2D)
                if pt.has_point3D() and len(rec.points3D[pt.point3D_id].track.elements) >= 3
            }
            if len(im.points2D) != len(desc):
                raise ValueError("keyframe_descriptor_index_mismatch")
            references.append((pixels, desc, assoc))
            continue
        pixels, desc = extract_features(frame, mask)
        tracked = [
            (p.xy, p.point3D_id)
            for p in im.points2D
            if p.has_point3D() and len(rec.points3D[p.point3D_id].track.elements) >= 3
        ]
        uv = np.array([xy for xy, _ in tracked], np.float32)
        camera = rec.cameras[im.camera_id]
        uv *= np.array([SIZE[0] / camera.width, SIZE[1] / camera.height], np.float32)
        assoc, used = {}, set()
        if len(uv) and len(pixels):
            for m in sorted(
                cv.BFMatcher(cv.NORM_L2).match(uv, pixels.astype(np.float32)),
                key=lambda m: m.distance,
            ):
                if m.distance <= 1.5 and m.trainIdx not in used:
                    used.add(m.trainIdx)
                    assoc[m.trainIdx] = int(tracked[m.queryIdx][1])
        references.append((pixels, desc, assoc))
    if db is not None:
        db.close()
    samples = json.loads(Path(heldout_report).read_text(encoding="utf-8"))["samples"]
    retrieval = json.loads(Path(retrieval_report).read_text(encoding="utf-8"))
    if len(samples) != len(retrieval):
        raise ValueError("keyframe_samples_mismatch")
    needed = {s["source_index"]: (s, r) for s, r in zip(samples, retrieval)}
    if len(needed) != len(samples) or any(
        abs(s["media_seconds"] - r["seconds"]) > 0.0001 for s, r in zip(samples, retrieval)
    ):
        raise ValueError("keyframe_samples_mismatch")
    capture = validate_browser(capture)
    if (
        hashlib.sha256(capture.originals["manifest.json"]).hexdigest()
        != route.source_capture_sha256
    ):
        raise ValueError("keyframe_capture_mismatch")
    probe = RouteLocalizer(
        route,
        capture_epoch=str(uuid.uuid4()),
        episode_id=str(uuid.uuid4()),
        goal_revision=str(uuid.uuid4()),
        diagnostic_partial_map=True,
        candidate_limit=5,
    )
    results = []
    for row, decoded in decoded_browser(capture):
        if row["index"] not in needed:
            continue
        if len(results) % 8 == 0:
            bounded()
        sample, retrieval_row = needed[row["index"]]
        query_start = time.perf_counter()
        rgb = decoded.to_ndarray(format="rgb24")
        if full_resolution:
            gray = cv.cvtColor(rgb, cv.COLOR_RGB2GRAY)
            query_mask = np.full(gray.shape, 255, np.uint8)
            query_mask[int(gray.shape[0] * 0.975) :] = 0
            keypoints, desc = cv.SIFT_create(
                nfeatures=4096, contrastThreshold=0.0066667, edgeThreshold=10
            ).detectAndCompute(gray, query_mask)
            if desc is None:
                continue
            desc = np.sqrt(desc / np.maximum(desc.sum(axis=1, keepdims=True), 1e-8))
            desc /= np.maximum(np.linalg.norm(desc, axis=1, keepdims=True), 1e-8)
            pixels = np.asarray([point.pt for point in keypoints], np.float64)
            pixels *= np.asarray([SIZE[0] / gray.shape[1], SIZE[1] / gray.shape[0]])
        else:
            rgb = cv.resize(
                rgb, (route.profile.width, route.profile.height), interpolation=cv.INTER_AREA
            )
            frame = PolicyFrame(
                str(uuid.uuid4()),
                row["index"] + 1,
                0.0,
                route.profile.width,
                route.profile.height,
                rgb.tobytes(),
            )
            pixels, desc = extract_features(frame, mask)
        feature_ms = (time.perf_counter() - query_start) * 1000
        oracle = int(np.argmin(np.abs(np.asarray(route.source_seconds) - sample["media_seconds"])))
        retrieved = [v["view"] for v in retrieval_row["candidates"]]
        measured = {}
        retrieved_pairs = []
        for at in dict.fromkeys([oracle, *retrieved]):
            candidate_start = time.perf_counter()
            ref_pixels, ref_desc, assoc = references[at]
            if len(desc) < 2 or len(ref_desc) < 2:
                continue
            pairs = cv.BFMatcher(cv.NORM_L2).knnMatch(desc, ref_desc, k=2)
            matches = [
                a
                for pair in pairs
                if len(pair) == 2
                for a, b in [pair]
                if a.distance < 0.75 * b.distance and a.distance < 0.7
            ]
            unique = {}
            for m in sorted(matches, key=lambda x: x.distance):
                point_id = assoc.get(m.trainIdx)
                if point_id is not None and point_id not in unique:
                    unique[point_id] = m
                    if at in retrieved:
                        retrieved_pairs.append((float(m.distance), int(m.queryIdx), point_id))
            xyz = np.asarray([rec.points3D[i].xyz for i in unique], dtype=np.float64).reshape(-1, 3)
            xy = np.asarray(
                [pixels[m.queryIdx] for m in unique.values()], dtype=np.float64
            ).reshape(-1, 2)
            solution = probe._verify_correspondences(xyz, xy) if len(unique) >= 24 else None
            measured[str(at)] = {
                "raw_2d_matches": len(matches),
                "associated_3d": len(unique),
                "pnp_passed": solution is not None,
                "inliers": None if solution is None else solution[2],
                "median_error_px": None if solution is None else solution[3],
                "center": None if solution is None else [float(x) for x in solution[0]],
                "rotation": None if solution is None else [float(x) for x in solution[1].ravel()],
                "compute_ms": (time.perf_counter() - candidate_start) * 1000,
            }
        # Conservative one-to-one aggregation; do not count the same query
        # feature or landmark multiple times. The unchanged PnP gate follows.
        aggregate_start = time.perf_counter()
        selected = unique_correspondences(retrieved_pairs)
        xyz = np.asarray(
            [rec.points3D[point_id].xyz for _, point_id in selected], dtype=np.float64
        ).reshape(-1, 3)
        xy = np.asarray([pixels[query_idx] for query_idx, _ in selected], dtype=np.float64).reshape(
            -1, 2
        )
        combined = probe._verify_correspondences(xyz, xy) if len(selected) >= 24 else None
        aggregation = {
            "unique_correspondences": len(selected),
            "pnp_passed": combined is not None,
            "inliers": None if combined is None else combined[2],
            "median_error_px": None if combined is None else combined[3],
            "center": None if combined is None else [float(x) for x in combined[0]],
            "compute_ms": (time.perf_counter() - aggregate_start) * 1000,
        }
        results.append(
            {
                "source_index": row["index"],
                "seconds": sample["media_seconds"],
                "oracle_view": oracle,
                "retrieved_views": retrieved,
                "views": measured,
                "aggregation": aggregation,
                "feature_compute_ms": feature_ms,
            }
        )
    if len(results) != len(needed):
        raise ValueError("keyframe_samples_missing")
    report = {
        "schema": "sphere-keyframe-2d3d-probe-v1",
        "samples": results,
        "full_resolution_query": full_resolution,
        "oracle_uses_video_time": True,
        "same_capture": True,
        "independent_pass": False,
        "execution_qualified": False,
        "physical_actions": 0,
    }
    write_json(out / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "prepared", "model", "route", "sha", "heldout", "retrieval", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--full-resolution", action="store_true")
    a = parser.parse_args()
    r = run(
        a.capture,
        a.prepared,
        a.model,
        a.route,
        a.sha,
        a.heldout,
        a.retrieval,
        a.output,
        full_resolution=a.full_resolution,
    )
    print(json.dumps({"samples": len(r["samples"])}))


if __name__ == "__main__":
    main()
