"""Bound a copied COLMAP verified pair graph to nearby recorded views.

The retained verified geometries and matches are never recomputed or altered.
The caller must provide chronological selected names and an isolated DB copy.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.pilot.filter_sfm_pair_graph import PAIR_BASE


def restrict_copied_database(database, selected_names, max_view_gap, *, checkpoint):
    database = Path(database)
    if not database.is_file() or database.is_symlink():
        raise ValueError("temporal_graph_path_invalid")
    if (
        type(max_view_gap) is not int
        or not 1 <= max_view_gap <= 16
        or not 10 <= len(selected_names) <= 240
        or len(set(selected_names)) != len(selected_names)
        or any(Path(name).name != name for name in selected_names)
    ):
        raise ValueError("temporal_graph_selection_invalid")
    with closing(sqlite3.connect(database)) as db, db:
        ids = {
            name: int(image_id)
            for image_id, name in db.execute("SELECT image_id,name FROM images")
            if name in selected_names
        }
        if len(ids) != len(selected_names):
            raise ValueError("temporal_graph_images_missing")
        order = {ids[name]: index for index, name in enumerate(selected_names)}
        pairs = db.execute("SELECT pair_id FROM two_view_geometries").fetchall()
        retained = removed = 0
        for i, (pair_id,) in enumerate(pairs):
            if i % 100 == 0:
                checkpoint()
            a, b = divmod(pair_id, PAIR_BASE)
            if a in order and b in order and abs(order[a] - order[b]) <= max_view_gap:
                retained += 1
            else:
                db.execute("DELETE FROM two_view_geometries WHERE pair_id=?", (pair_id,))
                removed += 1
        if retained < len(selected_names) - 1:
            raise ValueError("temporal_graph_sparse")
    return {
        "selected_images": len(selected_names),
        "max_view_gap": max_view_gap,
        "retained_pairs": retained,
        "removed_pairs": removed,
        "geometry_reverified": False,
        "retained_geometry_unchanged": True,
        "elapsed_media_time_is_not_distance": True,
    }
