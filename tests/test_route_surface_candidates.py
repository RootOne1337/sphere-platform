import unittest

from scripts.pilot.audit_route_surface import fit
from tests.test_route_trace_preview import camera


class SurfaceCandidateTests(unittest.TestCase):
    def test_supported_horizontal_points_produce_a_reproducible_plane_not_a_navigation_permit(self):
        import numpy as np

        points = [
            [x, 0.4, z] for x in np.linspace(-1.5, 1.5, 30) for z in np.linspace(0.6, 2.5, 60)
        ]
        geometry = dict(points=points, cameras=[camera(i * 45000, z=i * 0.2) for i in range(5)])
        result = fit(geometry)
        self.assertGreater(result["accepted"], 0)
        self.assertEqual(result, fit(geometry))
        self.assertFalse(result["executionQualified"])
        self.assertFalse(result["cameraBodyCalibrated"])
        for row in result["rows"]:
            if row["accepted"]:
                self.assertAlmostEqual(row["heightUnits"], 0.4, places=6)

    def test_no_ground_evidence_or_zero_camera_baseline_is_not_filled(self):
        geometry = dict(
            points=[[i * 0.01, 0, 2] for i in range(100)], cameras=[camera(0), camera(45000, z=0.2)]
        )
        self.assertEqual(fit(geometry)["accepted"], 0)
        geometry["cameras"][1] = camera(45000)
        with self.assertRaises(ValueError):
            fit(geometry)
