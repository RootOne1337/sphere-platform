"""Audit saved verified image matches that survive as shared SfM tracks.

Image bands are not semantic classes. Non-survival does not prove an error:
matches may be dynamic, outliers or lack triangulation geometry.
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


def band_counts(first_y, first_ids, second_ids, height):
    import numpy as np

    y, a, b = np.asarray(first_y, float), np.asarray(first_ids), np.asarray(second_ids)
    if (
        y.ndim != 1
        or a.shape != y.shape
        or b.shape != y.shape
        or a.dtype.kind not in "iu"
        or b.dtype.kind not in "iu"
        or not np.isfinite(y).all()
        or not 0 < height <= 8192
    ):
        raise ValueError("track_retention_input_invalid")
    total = [0, 0, 0]
    shared = [0, 0, 0]
    for yy, aa, bb in zip(y, a, b):
        if not 0 <= yy < height:
            continue
        band = min(int(yy * 3 / height), 2)
        total[band] += 1
        if aa >= 0 and bb >= 0 and aa == bb:
            shared[band] += 1
    return total, shared


def run(prepared, model, expected_model_receipt, output, *, start=28.0):
    import numpy as np
    import pycolmap

    prepared, model, expected_model_receipt, output = map(
        Path, (prepared, model, expected_model_receipt, output)
    )
    checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    database = prepared / "database.db"
    provenance = prepared / "reconstruction-input.json"
    if any(p.is_symlink() for p in (prepared, model, database, provenance, expected_model_receipt)):
        raise ValueError("track_retention_source_symlink")
    if (prepared / "database.db-wal").exists() and (prepared / "database.db-wal").stat().st_size:
        raise ValueError("track_retention_database_unstable")

    def digest(p):
        with p.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    sources = [database, provenance, expected_model_receipt, *sorted(model.glob("*.bin"))]
    before = {str(p): digest(p) for p in sources}
    source = json.loads(provenance.read_text(encoding="utf-8"))
    receipt = json.loads(expected_model_receipt.read_text(encoding="utf-8"))
    if receipt.get("source_database_sha256") != before[str(database)] or receipt.get(
        "source_manifest_sha256"
    ) != source.get("source_manifest_sha256"):
        raise ValueError("track_retention_source_binding_invalid")
    rec = pycolmap.Reconstruction(model)
    provenance_by_name = {Path(r["image"]).name: r for r in source["images"]}
    images = {im.image_id: im for im in rec.images.values()}
    output.mkdir()
    write_json(
        output / "intent.json",
        {"scope": "offline_saved_graph_track_retention", "physical_actions": 0},
    )
    bands_total = [0, 0, 0]
    bands_shared = [0, 0, 0]
    samples = []
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        names = {int(i): name for i, name in db.execute("SELECT image_id,name FROM images")}
        for image_id, im in images.items():
            if names.get(image_id) != im.name or im.name not in provenance_by_name:
                raise ValueError("track_retention_image_identity_mismatch")
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
                raise ValueError("track_retention_keypoint_identity_mismatch")
            kp = np.frombuffer(row[2], dtype="<f4").reshape(row[0], row[1])[:, :2]
            actual = np.asarray([p.xy for p in im.points2D])
            if not np.allclose(kp, actual, atol=1e-4, rtol=0):
                raise ValueError("track_retention_keypoint_identity_mismatch")
        for index, (pair, n, cols, raw) in enumerate(
            db.execute("SELECT pair_id,rows,cols,data FROM two_view_geometries")
        ):
            if index % 100 == 0:
                checkpoint(output)
            a, b = divmod(pair, PAIR_BASE)
            if a not in images or b not in images or n == 0:
                continue
            ta = provenance_by_name[names[a]]["relative_ticks_90k"] / 90000
            tb = provenance_by_name[names[b]]["relative_ticks_90k"] / 90000
            if min(ta, tb) < start:
                continue
            if cols != 2 or raw is None or len(raw) != n * cols * 4:
                raise ValueError("track_retention_matches_invalid")
            pairs = np.frombuffer(raw, dtype="<u4").reshape(n, 2)
            first = images[a]
            second = images[b]
            if len(pairs) and (
                pairs[:, 0].max() >= len(first.points2D)
                or pairs[:, 1].max() >= len(second.points2D)
            ):
                raise ValueError("track_retention_match_index_invalid")
            first_pts = [first.points2D[int(i)] for i in pairs[:, 0]]
            second_pts = [second.points2D[int(i)] for i in pairs[:, 1]]
            t, s = band_counts(
                [p.xy[1] for p in first_pts],
                [int(p.point3D_id) if p.has_point3D() else -1 for p in first_pts],
                [int(p.point3D_id) if p.has_point3D() else -1 for p in second_pts],
                rec.cameras[first.camera_id].height,
            )
            bands_total = [x + y for x, y in zip(bands_total, t)]
            bands_shared = [x + y for x, y in zip(bands_shared, s)]
            samples.append(
                {
                    "first": first.name,
                    "second": second.name,
                    "first_seconds": ta,
                    "second_seconds": tb,
                    "verified_by_band": t,
                    "shared_3d_by_band": s,
                }
            )
    if {key: digest(Path(key)) for key in before} != before:
        raise ValueError("track_retention_source_changed")
    result = {
        "schema": "sphere-graph-track-retention-v1",
        "samples": samples,
        "pairs": len(samples),
        "verified_by_band": bands_total,
        "shared_3d_by_band": bands_shared,
        "shared_ratios": [
            None if total == 0 else shared / total
            for total, shared in zip(bands_total, bands_shared)
        ],
        "bands": "three_equal_image_height_bands",
        "dynamic_filter": False,
        "same_recording": True,
        "ground_truth": False,
        "physical_actions": 0,
        "execution_qualified": False,
        "source_sha256": before,
    }
    write_json(output / "report.json", result)
    return result
