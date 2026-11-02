import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.pilot.filter_sfm_pair_graph import PAIR_BASE
from scripts.pilot.filter_sfm_temporal_graph import restrict_copied_database


class TemporalGraphTests(unittest.TestCase):
    def make_database(self, path):
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(
                "CREATE TABLE images(image_id INTEGER,name TEXT);"
                "CREATE TABLE two_view_geometries(pair_id INTEGER,payload BLOB);"
                "CREATE TABLE matches(pair_id INTEGER,payload BLOB);"
            )
            for i in range(1, 12):
                db.execute("INSERT INTO images VALUES (?,?)", (i, f"{i}.png"))
            for a, b in [(i, i + 1) for i in range(1, 10)] + [(1, 3), (10, 11)]:
                pair = a * PAIR_BASE + b
                db.execute("INSERT INTO two_view_geometries VALUES (?,?)", (pair, b"original"))
                db.execute("INSERT INTO matches VALUES (?,?)", (pair, b"raw"))

    def test_selected_neighbors_preserve_verified_data_and_raw_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "copy.db"
            self.make_database(path)
            result = restrict_copied_database(
                path, [f"{i}.png" for i in range(1, 11)], 1, checkpoint=lambda: None
            )
            self.assertEqual((result["retained_pairs"], result["removed_pairs"]), (9, 2))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM matches").fetchone()[0], 11)
                self.assertEqual(
                    db.execute("SELECT DISTINCT payload FROM two_view_geometries").fetchall(),
                    [(b"original",)],
                )

    def test_failed_checkpoint_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "copy.db"
            self.make_database(path)

            def fail():
                raise RuntimeError("cancelled")

            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                restrict_copied_database(
                    path, [f"{i}.png" for i in range(1, 11)], 1, checkpoint=fail
                )
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(
                    db.execute("SELECT count(*) FROM two_view_geometries").fetchone()[0], 11
                )


if __name__ == "__main__":
    unittest.main()
