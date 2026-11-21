"""Bounded offline LightGlue/RootSIFT to SfM point matching diagnostic.

Input candidates are precomputed from the same recording. Neither successful
PnP nor media-time proximity is a driving authorization or independent replay.
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
from motor_worker.route_localization import SIZE, RouteLocalizer, SparseRoute
from scripts.pilot.atomic_json import write_json
from scripts.pilot.learned_route_features import load_matcher
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]


def checkpoint(job):
    """One complete disk/commit/RAM check, using the stricter 12 GiB floor."""
    if (job / "CANCEL").exists():
        raise RuntimeError("cancelled")
    snapshot = collect(ROOT)
    findings = evaluate(snapshot, min_ram_gib=12)
    if findings:
        if job.is_dir():
            write_json(job / "resource-refusal.json", {"snapshot": snapshot, "findings": findings})
        raise RuntimeError("lightglue_resource_guard")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_match_pairs(pairs, query_count, reference_count):
    import numpy as np

    if (
        not isinstance(pairs, np.ndarray)
        or pairs.ndim != 2
        or pairs.shape[1] != 2
        or pairs.dtype.kind not in "iu"
        or type(query_count) is not int
        or type(reference_count) is not int
        or query_count < 0
        or reference_count < 0
    ):
        raise ValueError("lightglue_match_indices_invalid")
    if len(pairs) and (
        pairs.min() < 0
        or pairs[:, 0].max() >= query_count
        or pairs[:, 1].max() >= reference_count
        or len(np.unique(pairs[:, 0])) != len(pairs)
        or len(np.unique(pairs[:, 1])) != len(pairs)
    ):
        raise ValueError("lightglue_match_indices_invalid")
    return pairs


def run(
    capture,
    prepared,
    model,
    route_path,
    route_sha,
    heldout,
    retrieval,
    output,
    *,
    save_correspondences=False,
):
    import cv2 as cv
    import numpy as np
    import pycolmap
    import torch

    if type(save_correspondences) is not bool:
        raise ValueError("lightglue_output_mode_invalid")
    out = Path(output)
    checkpoint(out.parent)
    out.mkdir(exist_ok=False)
    write_json(
        out / "intent.json",
        {
            "scope": "offline_lightglue_keyframe_pnp",
            "physical_actions": 0,
            "gpu_memory_fraction": 0.35,
            "candidate_limit": 5,
        },
    )
    started = time.monotonic()

    def bounded():
        if time.monotonic() - started > 600:
            raise RuntimeError("lightglue_probe_timeout")
        checkpoint(out)

    cv.setNumThreads(4)
    cv.setRNGSeed(17)
    prepared, model = Path(prepared), Path(model)
    paths = [
        prepared / "database.db",
        prepared / "features.json",
        prepared / "reconstruction-input.json",
        *sorted(model.glob("*.bin")),
        Path(heldout),
        Path(retrieval),
        Path(route_path),
    ]
    before = {str(p): digest(p) for p in paths}
    metadata = json.loads((prepared / "features.json").read_text(encoding="utf-8"))
    if metadata.get("method") != "opencv-rootsift-lightglue" or not metadata.get(
        "geometric_verification_complete"
    ):
        raise ValueError("lightglue_source_graph_invalid")
    route = SparseRoute.load(route_path, sha256=route_sha)
    rec = pycolmap.Reconstruction(model)
    source = json.loads((prepared / "reconstruction-input.json").read_text(encoding="utf-8"))
    rows = {Path(r["image"]).name: r for r in source["images"]}
    images = sorted(rec.images.values(), key=lambda im: rows[im.name]["relative_ticks_90k"])
    if len(images) != len(route.camera_trace):
        raise ValueError("lightglue_model_mismatch")
    # CPU arrays only: candidate tensors are transferred one at a time.
    references = []
    with sqlite3.connect(
        (prepared / "database.db").resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        for im in images:
            key = db.execute(
                "SELECT rows,cols,data FROM keypoints WHERE image_id=?", (im.image_id,)
            ).fetchone()
            desc = db.execute(
                "SELECT rows,cols,data FROM descriptors WHERE image_id=?", (im.image_id,)
            ).fetchone()
            if (
                not key
                or not desc
                or key[1] != 4
                or desc[1] != 128
                or key[0] != desc[0]
                or len(im.points2D) != key[0]
            ):
                raise ValueError("lightglue_features_invalid")
            kp = np.frombuffer(key[2], np.float32).reshape(key[0], 4).copy()
            ds = np.frombuffer(desc[2], np.uint8).reshape(desc[0], 128).astype(np.float32) / 512.0
            ds /= np.maximum(np.linalg.norm(ds, axis=1, keepdims=True), 1e-8)
            assoc = {
                i: int(pt.point3D_id)
                for i, pt in enumerate(im.points2D)
                if pt.has_point3D() and len(rec.points3D[pt.point3D_id].track.elements) >= 3
            }
            references.append((kp, ds, assoc))
    samples = json.loads(Path(heldout).read_text(encoding="utf-8"))["samples"]
    retrieval_rows = json.loads(Path(retrieval).read_text(encoding="utf-8"))
    if len(samples) != len(retrieval_rows) or any(
        abs(s["media_seconds"] - r["seconds"]) > 0.0001 for s, r in zip(samples, retrieval_rows)
    ):
        raise ValueError("lightglue_samples_mismatch")
    needed = {s["source_index"]: (s, r) for s, r in zip(samples, retrieval_rows)}
    source_capture = validate_browser(capture)
    if (
        hashlib.sha256(source_capture.originals["manifest.json"]).hexdigest()
        != route.source_capture_sha256
    ):
        raise ValueError("lightglue_capture_mismatch")
    bounded()
    matcher = load_matcher(ROOT, memory_fraction=0.35)
    probe = RouteLocalizer(
        route,
        capture_epoch=str(uuid.uuid4()),
        episode_id=str(uuid.uuid4()),
        goal_revision=str(uuid.uuid4()),
        diagnostic_partial_map=True,
        candidate_limit=5,
    )
    results = []

    def tensor_features(kp, desc, width, height):
        return {
            "keypoints": torch.from_numpy(kp[:, :2].copy())[None].to("cuda"),
            "scales": torch.from_numpy(kp[:, 2].copy())[None].to("cuda"),
            "oris": torch.from_numpy(kp[:, 3].copy())[None].to("cuda"),
            "descriptors": torch.from_numpy(desc.copy())[None].to("cuda"),
            "image_size": torch.tensor([[width, height]], dtype=torch.float32, device="cuda"),
        }

    try:
        for row, decoded in decoded_browser(source_capture):
            if row["index"] not in needed:
                continue
            bounded()
            sample, retrieval_row = needed[row["index"]]
            start = time.perf_counter()
            rgb = decoded.to_ndarray(format="rgb24")
            gray = cv.cvtColor(rgb, cv.COLOR_RGB2GRAY)
            mask = np.full(gray.shape, 255, np.uint8)
            mask[int(gray.shape[0] * 0.975) :] = 0
            keypoints, desc = cv.SIFT_create(
                nfeatures=4096, contrastThreshold=0.0066667, edgeThreshold=10
            ).detectAndCompute(gray, mask)
            if desc is None or len(keypoints) < 24:
                raise ValueError("lightglue_query_features_missing")
            desc = np.sqrt(desc / np.maximum(desc.sum(axis=1, keepdims=True), 1e-8))
            desc /= np.maximum(np.linalg.norm(desc, axis=1, keepdims=True), 1e-8)
            kp = np.column_stack(
                [
                    np.asarray([k.pt for k in keypoints], np.float32) + 0.5,
                    np.asarray([k.size for k in keypoints], np.float32),
                    np.deg2rad(np.asarray([k.angle for k in keypoints], np.float32)),
                ]
            ).astype(np.float32)
            feature_ms = (time.perf_counter() - start) * 1000
            query = tensor_features(kp, desc, gray.shape[1], gray.shape[0])
            candidate_results = []
            correspondence_rows = []
            with torch.inference_mode():
                for item in retrieval_row["candidates"][:5]:
                    bounded()
                    at = item["view"]
                    if type(at) is not int or not 0 <= at < len(references):
                        raise ValueError("lightglue_candidate_invalid")
                    ref_kp, ref_desc, assoc = references[at]
                    reference = tensor_features(ref_kp, ref_desc, gray.shape[1], gray.shape[0])
                    torch.cuda.synchronize()
                    match_start = time.perf_counter()
                    output_pair = matcher({"image0": query, "image1": reference})
                    torch.cuda.synchronize()
                    matching_ms = (time.perf_counter() - match_start) * 1000
                    pairs = validate_match_pairs(
                        output_pair["matches"][0].cpu().numpy(), len(kp), len(ref_kp)
                    )
                    points = {}
                    for q, r in pairs:
                        point_id = assoc.get(int(r))
                        if point_id is not None:
                            points.setdefault(point_id, int(q))
                    if save_correspondences:
                        correspondence_rows.extend(
                            (
                                at,
                                point_id,
                                q,
                                float(kp[q, 0]) * SIZE[0] / gray.shape[1],
                                float(kp[q, 1]) * SIZE[1] / gray.shape[0],
                            )
                            for point_id, q in points.items()
                        )
                    xyz = np.asarray([rec.points3D[i].xyz for i in points], np.float64).reshape(
                        -1, 3
                    )
                    xy = np.asarray([kp[q, :2] for q in points.values()], np.float64).reshape(-1, 2)
                    xy *= np.asarray([SIZE[0] / gray.shape[1], SIZE[1] / gray.shape[0]])
                    verify_start = time.perf_counter()
                    solution = probe._verify_correspondences(xyz, xy) if len(points) >= 24 else None
                    candidate_results.append(
                        {
                            "view": at,
                            "matches": int(len(pairs)),
                            "associated_3d": len(points),
                            "pnp_passed": solution is not None,
                            "inliers": None if solution is None else solution[2],
                            "median_error_px": None if solution is None else solution[3],
                            "center": None if solution is None else [float(x) for x in solution[0]],
                            "matching_ms": matching_ms,
                            "verify_ms": (time.perf_counter() - verify_start) * 1000,
                        }
                    )
                    del reference, output_pair
            del query
            record = {
                "source_index": row["index"],
                "seconds": sample["media_seconds"],
                "source_rgb_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
                "feature_ms": feature_ms,
                "candidates": candidate_results,
            }
            if save_correspondences:
                path = out / f"correspondences-{row['index']:08d}.npz"
                values = np.asarray(correspondence_rows, dtype=np.float64).reshape(-1, 5)
                with path.open("xb") as file:
                    np.savez_compressed(
                        file,
                        view=values[:, 0].astype(np.int32),
                        point_id=values[:, 1].astype(np.int64),
                        query_id=values[:, 2].astype(np.int32),
                        pixels=values[:, 3:5],
                    )
                record["correspondence_file"] = path.name
                record["correspondence_sha256"] = digest(path)
            results.append(record)
            write_json(
                out / "partial.json",
                {
                    "schema": "sphere-lightglue-keyframe-partial-v1",
                    "samples": results,
                    "same_capture": True,
                    "complete": False,
                    "execution_qualified": False,
                },
            )
            write_json(
                out / "state.json",
                {
                    "phase": "matching",
                    "samples_processed": len(results),
                    "samples_total": len(needed),
                    "execution_qualified": False,
                },
            )
        if len(results) != len(needed):
            raise ValueError("lightglue_samples_missing")
        if {key: digest(key) for key in before} != before:
            raise ValueError("lightglue_source_changed")
        report = {
            "schema": "sphere-lightglue-keyframe-probe-v1",
            "samples": results,
            "same_capture": True,
            "independent_pass": False,
            "candidate_source": "previous_same_video_retrieval",
            "capture_manifest_sha256": route.source_capture_sha256,
            "saved_correspondences": save_correspondences,
            "physical_actions": 0,
            "execution_qualified": False,
            "gpu": torch.cuda.get_device_name(0),
            "source_sha256": before,
        }
        write_json(out / "report.json", report)
        write_json(
            out / "state.json",
            {
                "phase": "complete",
                "samples_processed": len(results),
                "samples_total": len(needed),
                "execution_qualified": False,
            },
        )
        return report
    finally:
        del matcher
        torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "prepared", "model", "route", "sha", "heldout", "retrieval", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--save-correspondences", action="store_true")
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
        save_correspondences=a.save_correspondences,
    )
    print(json.dumps({"samples": len(r["samples"])}))


if __name__ == "__main__":
    main()
