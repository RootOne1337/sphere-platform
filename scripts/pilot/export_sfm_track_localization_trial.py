"""Offline experiment: export COLMAP tracks using saved RootSIFT descriptors.

Not a navigation approval. Source images, model and database remain immutable;
the existing route localizer and its geometric checks are not relaxed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

from motor_worker.policy import PolicyFrame
from motor_worker.route_localization import (
    MAX_POINTS,
    SIZE,
    SparseRoute,
    extract_features,
    feature_mask,
    map_support,
    pipeline_id,
)
from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import checkpoint


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def balanced_tracks(candidates, view_count, limit):
    """Select across views without duplicating a track or exceeding the cap."""
    candidates = sorted(candidates, key=lambda row: -row[0])
    per_view = [[] for _ in range(view_count)]
    for idx, row in enumerate(candidates):
        for view in row[3]:
            if type(view) is not int or not 0 <= view < view_count:
                raise ValueError("sfm_track_view_invalid")
            per_view[view].append(idx)
    selected, used, cursor = [], set(), [0] * view_count
    while len(selected) < min(limit, len(candidates)):
        progress = False
        for view, choices in enumerate(per_view):
            while cursor[view] < len(choices) and choices[cursor[view]] in used:
                cursor[view] += 1
            if cursor[view] < len(choices):
                idx = choices[cursor[view]]
                used.add(idx)
                selected.append(candidates[idx])
                progress = True
                if len(selected) == limit:
                    break
        if not progress:
            break
    return selected


def run(
    model,
    database,
    provenance,
    images,
    template,
    template_sha,
    output,
    *,
    descriptor_source="saved",
):
    import cv2
    import numpy as np
    import pycolmap

    from scripts.pilot.reconstruction_quality import pinhole_condition

    started = time.monotonic()
    output = Path(output)
    checkpoint(output.parent)
    output.mkdir(exist_ok=False)
    write_json(output / "intent.json", {"scope": "offline_sfm_track_export", "physical_actions": 0})

    def bounded():
        if time.monotonic() - started > 300:
            raise RuntimeError("sfm_track_export_timeout")
        checkpoint(output)

    model, database, provenance, images = map(Path, (model, database, provenance, images))
    if any(p.is_symlink() for p in (model, database, provenance, images)):
        raise ValueError("sfm_track_source_symlink")
    paths = sorted(model.glob("*.bin")) + [database, provenance]
    before = {str(p): digest(p) for p in paths}
    profile = SparseRoute.load(template, sha256=template_sha).profile
    rec = pycolmap.Reconstruction(model)
    if rec.num_cameras() != 1 or not 2 <= rec.num_reg_images() <= 256:
        raise ValueError("sfm_track_model_invalid")
    camera = next(iter(rec.cameras.values()))
    if (
        camera.model_name not in {"PINHOLE", "SIMPLE_PINHOLE"}
        or camera.width * SIZE[1] != camera.height * SIZE[0]
    ):
        raise ValueError("sfm_track_camera_invalid")
    raw_k = camera.calibration_matrix()
    if not pinhole_condition(camera.width, camera.height, float(raw_k[0, 0]), float(raw_k[1, 1]))[
        "passed"
    ]:
        raise ValueError("sfm_track_camera_degenerate")
    k = np.diag([SIZE[0] / camera.width, SIZE[1] / camera.height, 1.0]) @ raw_k
    source = json.loads(provenance.read_text(encoding="utf-8"))
    rows = {Path(row["image"]).name: row for row in source["images"]}
    ordered = sorted(rec.images.values(), key=lambda im: rows[im.name]["relative_ticks_90k"])
    by_id = {im.image_id: idx for idx, im in enumerate(ordered)}
    if descriptor_source not in {"saved", "runtime"}:
        raise ValueError("sfm_track_descriptor_source_invalid")
    reference_hashes, trace, seconds, indices, runtime_descriptors = [], [], [], [], {}
    mask = feature_mask(profile) if descriptor_source == "runtime" else None
    for i, image in enumerate(ordered):
        if i % 8 == 0:
            bounded()
        if Path(image.name).name != image.name:
            raise ValueError("sfm_track_image_name_invalid")
        path = images / image.name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("sfm_track_image_invalid")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != rows[image.name]["png_sha256"]:
            raise ValueError("sfm_track_image_hash")
        decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            raise ValueError("sfm_track_decode")
        rgb = cv2.cvtColor(
            cv2.resize(decoded, (profile.width, profile.height), interpolation=cv2.INTER_AREA),
            cv2.COLOR_BGR2RGB,
        )
        reference_hashes.append(hashlib.sha256(rgb.tobytes()).hexdigest())
        if descriptor_source == "runtime":
            frame = PolicyFrame(
                "00000000-0000-4000-8000-000000000000",
                i + 1,
                0.0,
                profile.width,
                profile.height,
                rgb.tobytes(),
            )
            pixels, runtime = extract_features(frame, mask)
            tracked = [(idx, pt.xy) for idx, pt in enumerate(image.points2D) if pt.has_point3D()]
            associated = {}
            if len(pixels) and tracked:
                original_xy = np.asarray([xy for _, xy in tracked], dtype=np.float32)
                original_xy *= np.asarray(
                    [SIZE[0] / camera.width, SIZE[1] / camera.height], dtype=np.float32
                )
                matches = cv2.BFMatcher(cv2.NORM_L2).match(
                    original_xy, np.asarray(pixels, dtype=np.float32)
                )
                # A runtime descriptor can represent at most one tracked feature.
                used = set()
                for match in sorted(matches, key=lambda m: m.distance):
                    if match.distance > 1.5 or match.trainIdx in used:
                        continue
                    used.add(match.trainIdx)
                    associated[tracked[match.queryIdx][0]] = runtime[match.trainIdx]
            runtime_descriptors[image.image_id] = associated
        trace.append(tuple(float(v) for v in image.cam_from_world().inverse().translation))
        seconds.append(rows[image.name]["relative_ticks_90k"] / 90000)
        indices.append(rows[image.name]["source_index"])
    # These descriptors came from the saved RootSIFT/LightGlue graph, not an
    # unrelated COLMAP SIFT database. Restrict use to a declared input method.
    features_path = database.parent / "features.json"
    feature_meta = json.loads(features_path.read_text(encoding="utf-8"))
    if feature_meta.get("method") != "opencv-rootsift-lightglue" or not feature_meta.get(
        "geometric_verification_complete"
    ):
        raise ValueError("sfm_track_graph_method_unsupported")
    before[str(features_path)] = digest(features_path)
    descriptors = {}
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        for image in ordered:
            row = db.execute(
                "SELECT rows, cols, data FROM descriptors WHERE image_id=?", (image.image_id,)
            ).fetchone()
            if not row or row[1] != 128 or len(row[2]) != row[0] * 128:
                raise ValueError("sfm_track_descriptors_invalid")
            descriptors[image.image_id] = np.frombuffer(row[2], dtype=np.uint8).reshape(row[0], 128)
    candidates = []
    for n, point in enumerate(rec.points3D.values()):
        if n % 1024 == 0:
            bounded()
        observations = [
            (el.image_id, el.point2D_idx)
            for el in point.track.elements
            if el.image_id in by_id
            and (descriptor_source == "saved" or el.point2D_idx in runtime_descriptors[el.image_id])
        ]
        views = tuple(sorted({by_id[image_id] for image_id, _ in observations}))
        if len(views) < 3 or len(views) != len(observations) or not np.isfinite(point.xyz).all():
            continue
        if any(idx >= len(descriptors[im]) for im, idx in observations):
            raise ValueError("sfm_track_index_mismatch")
        samples = (
            np.array([descriptors[im][idx] for im, idx in observations], dtype=np.float32) / 512.0
            if descriptor_source == "saved"
            else np.array(
                [runtime_descriptors[im][idx] for im, idx in observations], dtype=np.float32
            )
        )
        norms = np.linalg.norm(samples, axis=1)
        if (norms < 1e-8).any():
            continue
        samples /= norms[:, None]
        medoid = int(
            np.argmin(np.linalg.norm(samples[:, None] - samples[None, :], axis=2).sum(axis=1))
        )
        candidates.append((len(views), tuple(float(v) for v in point.xyz), samples[medoid], views))
    # Round-robin by least represented reference view to avoid filling the
    # fixed map budget exclusively with long tracks from the beginning.
    selected = balanced_tracks(candidates, len(ordered), MAX_POINTS)
    bindings = {key: digest(Path(key)) for key in before}
    if bindings != before:
        raise ValueError("sfm_track_source_changed")
    source_sha = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    route = SparseRoute(
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        source_sha,
        pipeline_id(),
        profile,
        (float(k[0, 0]), float(k[1, 1]), float(k[0, 2]), float(k[1, 2])),
        tuple(row[1] for row in selected),
        np.asarray([row[2] for row in selected], dtype="<f4").tobytes(),
        tuple(trace),
        tuple(seconds),
        tuple(reference_hashes),
        tuple(row[3] for row in selected),
        source["source_manifest_sha256"],
        tuple(indices),
    )
    sha = route.save(output / "route.json")
    report = dict(
        schema="sphere-sfm-track-export-trial-v1",
        sha256=sha,
        candidates=len(candidates),
        landmarks=len(selected),
        cameras=len(ordered),
        map_support=map_support(route),
        descriptor_source=descriptor_source,
        runtime_association_radius_px=1.5 if descriptor_source == "runtime" else None,
        source_bindings=before,
        camera_trace_only=True,
        metric_scale=None,
        physical_actions=0,
        execution_qualified=False,
    )
    write_json(output / "export.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "database", "provenance", "images", "template", "template-sha", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--descriptor-source", choices=("saved", "runtime"), default="saved")
    args = parser.parse_args()
    result = run(
        args.model,
        args.database,
        args.provenance,
        args.images,
        args.template,
        args.template_sha,
        args.output,
        descriptor_source=args.descriptor_source,
    )
    print(json.dumps({k: result[k] for k in ("sha256", "candidates", "landmarks", "cameras")}))


if __name__ == "__main__":
    main()
