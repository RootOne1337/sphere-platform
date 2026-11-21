"""Read-only audit of saved SfM candidate views and verified pair graph.

No heavy reconstruction or image decoding; SQLite is opened immutable only
after verifying the WAL is empty. Inlier edges are evidence, not proof of
camera pose, geometry, or why the mapper did not register an image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
from contextlib import closing
from pathlib import Path


def audit(root: Path, capture: Path, output: Path):
    database = root / "prepared/database.db"
    wal = root / "prepared/database.db-wal"
    if output.exists() or not database.is_file() or wal.exists() and wal.stat().st_size:
        raise ValueError("existing_output_or_database_not_immutable")
    raw_geometry = (root / "geometry.json").read_bytes()
    geometry = json.loads(raw_geometry)
    raw_manifest = (capture / "manifest.json").read_bytes()
    manifest = json.loads(raw_manifest)
    manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
    frame_index = (capture / "frames.jsonl").read_bytes()
    if (
        geometry.get("source_manifest_sha256") != manifest_hash
        or manifest.get("files", {}).get("frames.jsonl", {}).get("sha256")
        != hashlib.sha256(frame_index).hexdigest()
    ):
        raise ValueError("capture_provenance_mismatch")
    recorded = [json.loads(line) for line in frame_index.decode("utf-8").splitlines()]
    if manifest.get("frames") != len(recorded):
        raise ValueError("capture_frame_count_mismatch")
    camera_names = {c["image"] for c in geometry["cameras"]}
    with closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    ) as db:
        images = db.execute("select image_id, name from images order by image_id").fetchall()
        keypoints = dict(db.execute("select image_id, rows from keypoints"))
        graph = db.execute(
            "select pair_id, rows from two_view_geometries where rows > 0"
        ).fetchall()
    ids = {int(i): name for i, name in images}
    if len(ids) != len(images) or not camera_names.issubset(ids.values()):
        raise ValueError("geometry_and_database_inconsistent")
    frame_ids = {}
    for image_id, name in images:
        if not name.endswith(".png") or not name[:-4].isdigit():
            raise ValueError("unexpected_image_name")
        frame = int(name[:-4])
        if frame >= len(recorded) or recorded[frame]["index"] != frame:
            raise ValueError("source_frame_not_bound")
        frame_ids[int(image_id)] = frame
    divisor = 2147483647
    edges = {i: [] for i in ids}
    for pair, matches in graph:
        a, b = int(pair) // divisor, int(pair) % divisor
        if a not in ids or b not in ids:
            raise ValueError("invalid_pair_image_id")
        edges[a].append((b, int(matches)))
        edges[b].append((a, int(matches)))
    rows = []
    for image_id, name in images:
        frame = frame_ids[int(image_id)]
        seconds = recorded[frame]["relative_ticks_90k"] / 90000
        all_edges = edges[int(image_id)]
        anchor = [n for other, n in all_edges if ids[other] in camera_names]
        adjacent = [
            (other, n)
            for other, n in all_edges
            if ids[other] in camera_names
            and abs(recorded[frame_ids[other]]["relative_ticks_90k"] / 90000 - seconds) <= 1
        ]
        strongest = max(adjacent, key=lambda item: item[1], default=None)
        rows.append(
            dict(
                image=name,
                source_frame=frame,
                seconds=seconds,
                registered_primary=name in camera_names,
                keypoints=keypoints.get(int(image_id), 0),
                verified_pair_count=len(all_edges),
                primary_neighbor_count=len(anchor),
                primary_pair_max=max(anchor, default=0),
                primary_pair_median=statistics.median(anchor) if anchor else None,
                nearby_primary_count=len(adjacent),
                nearby_primary_max=max((n for _, n in adjacent), default=0),
                nearby_strongest_seconds=None
                if strongest is None
                else recorded[frame_ids[strongest[0]]]["relative_ticks_90k"] / 90000,
            )
        )
    rows.sort(key=lambda r: r["source_frame"])
    missing = [r for r in rows if not r["registered_primary"]]
    report = dict(
        schema="saved-sfm-coverage-audit-v1",
        source_geometry_sha256=hashlib.sha256(raw_geometry).hexdigest(),
        source_manifest_sha256=manifest_hash,
        frame_index_sha256=hashlib.sha256(frame_index).hexdigest(),
        selected=len(rows),
        registered_primary=len(rows) - len(missing),
        missing_primary=len(missing),
        source_video_frames=len(recorded),
        database_read_only=True,
        physical_actions=0,
        pair_edges_do_not_prove_pose_or_explain_failure=True,
        missing_with_verified_primary_neighbors=sum(
            r["primary_neighbor_count"] > 0 for r in missing
        ),
        missing_with_at_least_24_pair_inliers=sum(r["primary_pair_max"] >= 24 for r in missing),
        missing_with_neighbor_within_1s=sum(r["nearby_primary_count"] > 0 for r in missing),
        missing_with_at_least_24_nearby_inliers=sum(r["nearby_primary_max"] >= 24 for r in missing),
        missing=missing,
        rows=rows,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2, allow_nan=False)
    print(
        json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.root, args.capture, args.output)
