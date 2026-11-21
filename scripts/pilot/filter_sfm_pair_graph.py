"""Create a spatially filtered *copied* COLMAP pair graph for an offline trial.

Only selected image IDs and a copy of the database may be passed here. Keypoint
indices are preserved; callers must re-run geometric verification afterwards.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

PAIR_BASE = 2147483647


def filter_upper(matches, first_keypoints, second_keypoints, width, height):
    import numpy as np

    if (
        matches.ndim != 2
        or matches.shape[1] != 2
        or matches.dtype.kind not in "iu"
        or first_keypoints.ndim != 2
        or second_keypoints.ndim != 2
        or first_keypoints.shape[1] < 2
        or second_keypoints.shape[1] < 2
        or not 0 < width <= 8192
        or not 0 < height <= 8192
    ):
        raise ValueError("spatial_pair_input_invalid")
    if len(matches) and (
        matches.min() < 0
        or matches[:, 0].max() >= len(first_keypoints)
        or matches[:, 1].max() >= len(second_keypoints)
    ):
        raise ValueError("spatial_pair_index_invalid")
    a = first_keypoints[matches[:, 0], :2]
    b = second_keypoints[matches[:, 1], :2]

    def inside(points):
        return (
            np.isfinite(points).all(axis=1)
            & (points[:, 0] >= 0.0125 * width)
            & (points[:, 0] < 0.9875 * width)
            & (points[:, 1] >= 0.0833333333 * height)
            & (points[:, 1] < 0.5 * height)
        )

    return matches[inside(a) & inside(b)]


def filter_copied_database(database, selected_names, pair_file, *, checkpoint):
    import numpy as np

    database, pair_file = Path(database), Path(pair_file)
    if not database.is_file() or database.is_symlink() or pair_file.exists():
        raise ValueError("spatial_pair_path_invalid")
    if (
        len(selected_names) < 10
        or len(selected_names) > 240
        or len(set(selected_names)) != len(selected_names)
    ):
        raise ValueError("spatial_pair_selection_invalid")
    if any(Path(name).name != name or "\n" in name or "\r" in name for name in selected_names):
        raise ValueError("spatial_pair_selection_invalid")
    retained = []
    counts = []
    with closing(sqlite3.connect(database)) as db, db:
        images = {
            name: (int(image_id), int(camera_id))
            for image_id, name, camera_id in db.execute(
                "SELECT image_id,name,camera_id FROM images"
            )
            if name in selected_names
        }
        if len(images) != len(selected_names):
            raise ValueError("spatial_pair_images_missing")
        names = {image_id: name for name, (image_id, _) in images.items()}
        cameras = {
            int(cid): (int(width), int(height))
            for cid, width, height in db.execute("SELECT camera_id,width,height FROM cameras")
        }
        dimensions = {cameras[cid] for _, cid in images.values()}
        if len(dimensions) != 1:
            raise ValueError("spatial_pair_camera_mismatch")
        width, height = dimensions.pop()
        points = {}
        for image_id, nrows, ncols, raw in db.execute(
            "SELECT image_id,rows,cols,data FROM keypoints"
        ):
            if image_id not in names:
                continue
            if ncols < 2 or raw is None or len(raw) != nrows * ncols * 4:
                raise ValueError("spatial_pair_keypoints_invalid")
            points[image_id] = np.frombuffer(raw, dtype="<f4").reshape(nrows, ncols)
        if set(points) != set(names):
            raise ValueError("spatial_pair_keypoints_missing")
        original = db.execute("SELECT pair_id,rows,cols,data FROM matches").fetchall()
        db.execute("DELETE FROM two_view_geometries")
        for i, (pair_id, nrows, ncols, raw) in enumerate(original):
            if i % 50 == 0:
                checkpoint()
            a, b = divmod(pair_id, PAIR_BASE)
            if a not in names or b not in names:
                continue
            if nrows == 0 and ncols == 2 and (raw is None or len(raw) == 0):
                counts.append((0, 0))
                continue
            if ncols != 2 or raw is None or len(raw) != nrows * ncols * 4:
                raise ValueError("spatial_pair_matches_invalid")
            matches = np.frombuffer(raw, dtype="<u4").reshape(nrows, 2)
            kept = filter_upper(matches, points[a], points[b], width, height).astype(
                "<u4", copy=False
            )
            db.execute(
                "UPDATE matches SET rows=?,data=? WHERE pair_id=?",
                (len(kept), kept.tobytes(), pair_id),
            )
            counts.append((len(matches), len(kept)))
            if len(kept) >= 15:
                retained.append((names[a], names[b]))
        if len(retained) < len(selected_names) - 1:
            raise ValueError("spatial_pair_graph_sparse")
    with pair_file.open("x", encoding="utf-8", newline="\n") as file:
        for a, b in retained:
            file.write(f"{a} {b}\n")
    return {
        "selected_images": len(selected_names),
        "examined_pairs": len(counts),
        "retained_pairs": len(retained),
        "raw_matches": sum(a for a, _ in counts),
        "retained_matches": sum(b for _, b in counts),
        "region": "x=1.25%-98.75%, y=8.33%-50%",
        "semantic_object_filter": False,
    }
