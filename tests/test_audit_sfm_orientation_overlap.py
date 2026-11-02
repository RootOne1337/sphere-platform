import unittest

import numpy as np

from scripts.pilot.audit_sfm_orientation_overlap import audit


class OrientationOverlapTests(unittest.TestCase):
    def test_same_cameras_in_shifted_frame(self):
        centers = [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [2, 1, 0],
            [3, 1, 0],
            [4, 1, 0],
            [4, 2, 0],
            [5, 2, 0],
        ]

        def make(offset):
            cams = []
            for i, center in enumerate(centers):
                point = np.asarray(center, dtype=float) + offset
                pose = np.column_stack([np.eye(3), point]).tolist()
                cams.append(
                    {
                        "image": str(i),
                        "ticks_90k": i * 90000,
                        "center": point.tolist(),
                        "camera_to_world": pose,
                    }
                )
            return {"source_manifest_sha256": "a" * 64, "cameras": cams}

        result = audit(
            make(np.zeros(3)),
            make(np.array([2.0, 3.0, 4.0])),
            fit_start=0.0,
            fit_end=4.0,
            test_start=4.0,
        )
        self.assertAlmostEqual(result["heldout"]["centers"]["max"], 0.0, places=7)
        self.assertAlmostEqual(result["heldout"]["orientations"]["max"], 0.0, places=5)
        self.assertFalse(result["execution_qualified"])

    def test_rejects_bad_rotation_and_source_mismatch(self):
        with self.assertRaisesRegex(ValueError, "orientation_source_mismatch"):
            audit({"source_manifest_sha256": "a" * 64}, {"source_manifest_sha256": "b" * 64})
        camera = {
            "image": "1",
            "ticks_90k": 0,
            "center": [0, 0, 0],
            "camera_to_world": [[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
        }
        with self.assertRaisesRegex(ValueError, "orientation_camera_invalid"):
            audit(
                {"source_manifest_sha256": "a" * 64, "cameras": [camera]},
                {"source_manifest_sha256": "a" * 64, "cameras": [camera]},
            )


if __name__ == "__main__":
    unittest.main()
