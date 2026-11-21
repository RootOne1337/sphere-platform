"""Check how saved 2D matches triangulate under an existing SfM model.

This is a same-recording consistency diagnostic; existing poses are not ground
truth and temporary points are not saved or admitted into the route map.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.filter_sfm_pair_graph import PAIR_BASE
from scripts.pilot.reconstruct_route import checkpoint


def assess_triangulation(K1, K2, E1, E2, points1, points2, *, max_error_px=3.0, min_angle_deg=1.0):
    import cv2
    import numpy as np

    k1, k2, e1, e2, a, b = (
        np.asarray(x, dtype=np.float64) for x in (K1, K2, E1, E2, points1, points2)
    )
    if (
        k1.shape != (3, 3)
        or k2.shape != (3, 3)
        or e1.shape != (3, 4)
        or e2.shape != (3, 4)
        or a.ndim != 2
        or a.shape[1] != 2
        or b.shape != a.shape
        or len(a) < 1
        or len(a) > 10000
        or not all(np.isfinite(x).all() for x in (k1, k2, e1, e2, a, b))
        or not 0 < max_error_px <= 10
        or not 0 < min_angle_deg <= 10
    ):
        raise ValueError("triangulation_audit_input_invalid")
    p1, p2 = k1 @ e1, k2 @ e2
    homogeneous = cv2.triangulatePoints(p1, p2, a.T, b.T).T
    valid = np.isfinite(homogeneous).all(axis=1) & (np.abs(homogeneous[:, 3]) > 1e-10)
    xyz = np.zeros((len(a), 3), dtype=np.float64)
    xyz[valid] = homogeneous[valid, :3] / homogeneous[valid, 3, None]
    depth1 = (xyz @ e1[:, :3].T + e1[:, 3])[:, 2]
    depth2 = (xyz @ e2[:, :3].T + e2[:, 3])[:, 2]
    valid &= np.isfinite(xyz).all(axis=1) & (depth1 > 1e-6) & (depth2 > 1e-6)
    hom = np.column_stack((xyz, np.ones(len(xyz))))
    proj1 = hom @ p1.T
    proj2 = hom @ p2.T
    proj_valid = (np.abs(proj1[:, 2]) > 1e-10) & (np.abs(proj2[:, 2]) > 1e-10)
    reproj = np.zeros((len(a), 2), dtype=np.float64)
    reproj[proj_valid, 0] = np.linalg.norm(
        proj1[proj_valid, :2] / proj1[proj_valid, 2, None] - a[proj_valid], axis=1
    )
    reproj[proj_valid, 1] = np.linalg.norm(
        proj2[proj_valid, :2] / proj2[proj_valid, 2, None] - b[proj_valid], axis=1
    )
    geometric = (
        valid
        & proj_valid
        & np.isfinite(reproj).all(axis=1)
        & (reproj[:, 0] <= max_error_px)
        & (reproj[:, 1] <= max_error_px)
    )
    c1 = -e1[:, :3].T @ e1[:, 3]
    c2 = -e2[:, :3].T @ e2[:, 3]
    rays1 = xyz - c1
    rays2 = xyz - c2
    norms = np.linalg.norm(rays1, axis=1) * np.linalg.norm(rays2, axis=1)
    cos = np.ones(len(a))
    nz = norms > 1e-12
    cos[nz] = np.clip(np.sum(rays1[nz] * rays2[nz], axis=1) / norms[nz], -1, 1)
    angles = np.degrees(np.arccos(cos))
    strong = geometric & nz & (angles >= min_angle_deg)
    return geometric, strong


def run(prepared, model, receipt, output, *, start=28.0):
    import cv2
    import numpy as np
    import pycolmap

    cv2.setNumThreads(4)
    prepared, model, receipt, output = map(Path, (prepared, model, receipt, output))
    checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    database = prepared / "database.db"
    provenance = prepared / "reconstruction-input.json"
    if any(p.is_symlink() for p in (prepared, model, database, provenance, receipt)):
        raise ValueError("triangulation_audit_symlink")
    wal = prepared / "database.db-wal"
    if wal.exists() and wal.stat().st_size:
        raise ValueError("triangulation_audit_database_unstable")

    def digest(p):
        with p.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    paths = [database, provenance, receipt, *sorted(model.glob("*.bin"))]
    before = {str(p): digest(p) for p in paths}
    source = json.loads(provenance.read_text(encoding="utf-8"))
    expected = json.loads(receipt.read_text(encoding="utf-8"))
    if expected.get("source_database_sha256") != before[str(database)] or expected.get(
        "source_manifest_sha256"
    ) != source.get("source_manifest_sha256"):
        raise ValueError("triangulation_audit_source_binding")
    by_name = {Path(r["image"]).name: r for r in source["images"]}
    rec = pycolmap.Reconstruction(model)
    ims = {im.image_id: im for im in rec.images.values()}
    output.mkdir()
    write_json(
        output / "intent.json",
        {"scope": "offline_temporary_triangulation_audit", "physical_actions": 0},
    )
    total = np.zeros(3, dtype=np.int64)
    geometry = np.zeros(3, dtype=np.int64)
    parallax = np.zeros(3, dtype=np.int64)
    pairs = 0
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        names = {int(i): n for i, n in db.execute("SELECT image_id,name FROM images")}
        for image_id, im in ims.items():
            if names.get(image_id) != im.name or im.name not in by_name:
                raise ValueError("triangulation_audit_image_mismatch")
            row = db.execute(
                "SELECT rows,cols,data FROM keypoints WHERE image_id=?", (image_id,)
            ).fetchone()
            if (
                not row
                or row[1] < 2
                or row[2] is None
                or len(row[2]) != row[0] * row[1] * 4
                or row[0] != len(im.points2D)
            ):
                raise ValueError("triangulation_audit_keypoints_mismatch")
            stored = np.frombuffer(row[2], dtype="<f4").reshape(row[0], row[1])[:, :2]
            actual = np.asarray([p.xy for p in im.points2D])
            if not np.allclose(stored, actual, atol=1e-4, rtol=0):
                raise ValueError("triangulation_audit_keypoints_mismatch")
        for index, (pair, n, cols, raw) in enumerate(
            db.execute("SELECT pair_id,rows,cols,data FROM two_view_geometries")
        ):
            if index % 100 == 0:
                checkpoint(output)
            a, b = divmod(pair, PAIR_BASE)
            if a not in ims or b not in ims or n == 0:
                continue
            if (
                min(
                    by_name[names[a]]["relative_ticks_90k"], by_name[names[b]]["relative_ticks_90k"]
                )
                / 90000
                < start
            ):
                continue
            if cols != 2 or raw is None or len(raw) != n * cols * 4 or n > 10000:
                raise ValueError("triangulation_audit_matches_invalid")
            matches = np.frombuffer(raw, dtype="<u4").reshape(n, 2)
            im1, im2 = ims[a], ims[b]
            if len(matches) and (
                matches[:, 0].max() >= len(im1.points2D) or matches[:, 1].max() >= len(im2.points2D)
            ):
                raise ValueError("triangulation_audit_match_index_invalid")
            c1, c2 = rec.cameras[im1.camera_id], rec.cameras[im2.camera_id]
            xy1 = np.asarray([im1.points2D[int(i)].xy for i in matches[:, 0]], dtype=np.float64) * [
                960 / c1.width,
                540 / c1.height,
            ]
            xy2 = np.asarray([im2.points2D[int(i)].xy for i in matches[:, 1]], dtype=np.float64) * [
                960 / c2.width,
                540 / c2.height,
            ]
            k1 = np.diag([960 / c1.width, 540 / c1.height, 1.0]) @ c1.calibration_matrix()
            k2 = np.diag([960 / c2.width, 540 / c2.height, 1.0]) @ c2.calibration_matrix()
            good, strong = assess_triangulation(
                k1, k2, im1.cam_from_world().matrix(), im2.cam_from_world().matrix(), xy1, xy2
            )
            band = np.floor(xy1[:, 1] / 180).astype(int)
            for nband in range(3):
                select = band == nband
                total[nband] += int(select.sum())
                geometry[nband] += int((select & good).sum())
                parallax[nband] += int((select & strong).sum())
            pairs += 1
    if {str(p): digest(p) for p in paths} != before:
        raise ValueError("triangulation_audit_source_changed")
    result = {
        "schema": "sphere-saved-graph-triangulation-audit-v1",
        "pairs": pairs,
        "matches_by_band": total.tolist(),
        "positive_depth_reprojection_3px_by_band": geometry.tolist(),
        "also_parallax_1deg_by_band": parallax.tolist(),
        "image_geometry": [960, 540],
        "bands": "three_equal_image_height_bands",
        "poses_are_ground_truth": False,
        "same_recording": True,
        "dynamic_filter": False,
        "physical_actions": 0,
        "execution_qualified": False,
        "source_sha256": before,
    }
    write_json(output / "report.json", result)
    return result
