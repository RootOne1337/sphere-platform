"""Explicit offline COLMAP cameras + RGB -> experimental sparse route.

No reconstruction adoption, download, service mutation or device actions. The
source model must already use the same coordinate scale as its camera intrinsics.
Requires optional pycolmap; the real-time localizer does not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

from motor_worker.landmarks import RouteViewProfile
from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError
from motor_worker.route_localization import (
    MAX_POINTS,
    MAX_VIEWS,
    SIZE,
    SparseRoute,
    extract_features,
    feature_mask,
    map_support,
    pipeline_id,
)


def _digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def export(model, provenance, images, output, *, profile, world_revision):
    import cv2
    import numpy as np
    import pycolmap

    from scripts.pilot.reconstruct_route import checkpoint
    from scripts.pilot.route_landmark_builder import build

    started = time.monotonic()

    def bounded():
        if time.monotonic()-started > 300:
            raise ProtocolError("sparse_export_time_quota")
        checkpoint(Path(output).resolve().parent)

    if Path(output).exists():
        raise FileExistsError(output)
    bounded()
    sources = tuple(Path(p) for p in (model, provenance, images))
    if any(p.is_symlink() for p in sources):
        raise ProtocolError("sparse_export_symlink")
    model, provenance, images = (p.resolve() for p in sources)
    bindings = {p.name: _digest(p) for p in sorted(model.glob("*.bin"))}
    bindings.update(provenance=_digest(provenance))
    rec = pycolmap.Reconstruction(model)
    if not 2 <= rec.num_reg_images() <= MAX_VIEWS or rec.num_cameras() != 1:
        raise ProtocolError("sparse_export_submap_quota_or_cameras")
    camera = next(iter(rec.cameras.values()))
    if camera.model_name not in {"PINHOLE", "SIMPLE_PINHOLE"} or camera.width*SIZE[1] != camera.height*SIZE[0]:
        raise ProtocolError("sparse_export_requires_pinhole")
    K = np.diag([SIZE[0]/camera.width, SIZE[1]/camera.height, 1.]) @ camera.calibration_matrix()
    source = json.loads(provenance.read_text(encoding="utf-8"))
    # Existing capture provenance binds selected PNGs to original media ticks.
    rows = {Path(row["image"]).name: row for row in source["images"]}
    ordered = sorted(rec.images.values(), key=lambda im: rows[im.name]["relative_ticks_90k"])
    if any(Path(im.name).name != im.name for im in ordered):
        raise ProtocolError("sparse_export_image_path")
    reference_hashes, trace, seconds, feature_observations, matrices = [], [], [], [], []
    mask = feature_mask(profile)
    for index, image in enumerate(ordered):
        if index % 8 == 0:
            bounded()
        path = images/image.name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64*1024*1024:
            raise ProtocolError("sparse_export_image_quota")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != rows[image.name]["png_sha256"]:
            raise ProtocolError("sparse_export_image_integrity")
        bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ProtocolError("sparse_export_image_decode")
        rgb = cv2.cvtColor(cv2.resize(bgr, (profile.width, profile.height), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        reference_hashes.append(hashlib.sha256(rgb.tobytes()).hexdigest())
        feature_observations.append(extract_features(PolicyFrame(world_revision, len(feature_observations)+1, 0.,
            profile.width, profile.height, rgb.tobytes()), mask))
        matrices.append(image.cam_from_world().matrix())
        trace.append(tuple(float(v) for v in image.cam_from_world().inverse().translation))
        seconds.append(rows[image.name]["relative_ticks_90k"]/90000)
    rebuilt, rebuild_report = build(feature_observations, matrices, K, checkpoint=bounded)
    xyz = [row[1] for row in rebuilt[:MAX_POINTS]]
    descriptors = [row[2] for row in rebuilt[:MAX_POINTS]]
    landmark_views = [row[3] for row in rebuilt[:MAX_POINTS]]
    source_sha = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    route = SparseRoute(str(uuid.uuid4()), world_revision, source_sha, pipeline_id(), profile,
        (float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])), tuple(xyz),
        np.asarray(descriptors, dtype="<f4").tobytes(), tuple(trace), tuple(seconds), tuple(reference_hashes), tuple(landmark_views),
        source["source_manifest_sha256"], tuple(rows[image.name]["source_index"] for image in ordered))
    current = {p.name: _digest(p) for p in sorted(model.glob("*.bin"))}
    current.update(provenance=_digest(provenance))
    if current != bindings:
        raise ProtocolError("sparse_export_source_changed")
    sha = route.save(output)
    return dict(schema="sphere-sparse-export-receipt-v1", route_id=route.id, sha256=sha,
        source_capture_sha256=route.source_capture_sha256, pipeline_sha256=route.pipeline_sha256,
        source_bindings=bindings, landmarks=len(xyz), cameras=len(trace),
        first_seconds=seconds[0], last_seconds=seconds[-1], camera_trace_only=True,
        omitted_landmarks=max(0, rebuild_report.get("accepted", rec.num_points3D())-len(xyz)),
        feature_build=rebuild_report, map_support=map_support(route), metric_scale=None,
        execution_qualified=False, input_events=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "provenance", "images", "output", "profile", "world-revision"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    profile = RouteViewProfile.parse(Path(args.profile).read_text(encoding="utf-8"))
    receipt = export(args.model, args.provenance, args.images, args.output,
                     profile=profile, world_revision=args.world_revision)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
