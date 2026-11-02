import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import numpy as np

from scripts.pilot.filter_sfm_pair_graph import PAIR_BASE, filter_copied_database, filter_upper


class SpatialPairFilterTests(unittest.TestCase):
    def test_both_observations_must_be_in_upper_region(self):
        first = np.array([[50, 20], [50, 80], [50, 20], [0, 20]], dtype=np.float32)
        second = np.array([[50, 20], [50, 20], [50, 80], [50, 20]], dtype=np.float32)
        matches = np.array([[0, 0], [1, 1], [2, 2], [3, 3]], dtype=np.uint32)
        np.testing.assert_array_equal(filter_upper(matches, first, second, 100, 100), [[0, 0]])
        with self.assertRaisesRegex(ValueError, "spatial_pair_index_invalid"):
            filter_upper(np.array([[4, 0]], np.uint32), first, second, 100, 100)

    def test_copied_db_removes_old_geometry_and_preserves_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbpath = Path(tmp) / "copy.db"
            pairfile = Path(tmp) / "pairs.txt"
            with closing(sqlite3.connect(dbpath)) as db, db:
                db.executescript(
                    "CREATE TABLE images(image_id INTEGER,name TEXT,camera_id INTEGER);"
                    "CREATE TABLE cameras(camera_id INTEGER,width INTEGER,height INTEGER);"
                    "CREATE TABLE keypoints(image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
                    "CREATE TABLE matches(pair_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
                    "CREATE TABLE two_view_geometries(pair_id INTEGER);"
                )
                db.execute("INSERT INTO cameras VALUES (1,100,100)")
                xy = np.array([[50, 20]] * 16 + [[50, 80]] * 4, dtype="<f4")
                matches = np.array([[i, i] for i in range(20)], dtype="<u4")
                for i in range(1, 11):
                    db.execute("INSERT INTO images VALUES (?,?,1)", (i, f"{i}.png"))
                    db.execute("INSERT INTO keypoints VALUES (?,?,?,?)", (i, 20, 2, xy.tobytes()))
                for i in range(1, 10):
                    pair = i * PAIR_BASE + i + 1
                    db.execute(
                        "INSERT INTO matches VALUES (?,?,?,?)", (pair, 20, 2, matches.tobytes())
                    )
                    db.execute("INSERT INTO two_view_geometries VALUES (?)", (pair,))
                db.execute("INSERT INTO matches VALUES (?,?,?,NULL)", (1 * PAIR_BASE + 3, 0, 2))
            receipt = filter_copied_database(
                dbpath, [f"{i}.png" for i in range(1, 11)], pairfile, checkpoint=lambda: None
            )
            self.assertEqual((receipt["retained_pairs"], receipt["retained_matches"]), (9, 144))
            self.assertEqual(len(pairfile.read_text().splitlines()), 9)
            with closing(sqlite3.connect(dbpath)) as db:
                self.assertEqual(
                    db.execute("SELECT count(*) FROM two_view_geometries").fetchone()[0], 0
                )
                count, blob = db.execute("SELECT rows,data FROM matches LIMIT 1").fetchone()
                self.assertEqual(count, 16)
                np.testing.assert_array_equal(
                    np.frombuffer(blob, dtype="<u4").reshape(-1, 2), matches[:16]
                )


if __name__ == "__main__":
    unittest.main()
