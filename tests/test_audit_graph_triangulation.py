import unittest

import numpy as np

from scripts.pilot.audit_graph_triangulation import assess_triangulation


class TriangulationAuditTests(unittest.TestCase):
    def test_positive_depth_and_parallax_are_checked(self):
        K = np.array([[500.0, 0, 480], [0, 500.0, 270], [0, 0, 1.0]])
        E1 = np.column_stack((np.eye(3), np.zeros(3)))
        E2 = np.column_stack((np.eye(3), np.array([-1.0, 0, 0])))
        xyz = np.array([[i * 0.2, j * 0.2, 8.0 + i * 0.2] for i in range(3) for j in range(3)])

        def project(E):
            q = (K @ E @ np.column_stack((xyz, np.ones(len(xyz)))).T).T
            return q[:, :2] / q[:, 2, None]

        good, strong = assess_triangulation(K, K, E1, E2, project(E1), project(E2))
        self.assertTrue(good.all())
        self.assertTrue(strong.all())
        behind = xyz.copy()
        behind[:, 2] *= -1

        def behind_project(E):
            q = (K @ E @ np.column_stack((behind, np.ones(len(behind)))).T).T
            return q[:, :2] / q[:, 2, None]

        good, _ = assess_triangulation(K, K, E1, E2, behind_project(E1), behind_project(E2))
        self.assertFalse(good.any())

    def test_rejects_mismatched_or_nonfinite_points(self):
        K = np.eye(3)
        E = np.column_stack((np.eye(3), np.zeros(3)))
        with self.assertRaisesRegex(ValueError, "triangulation_audit_input_invalid"):
            assess_triangulation(K, K, E, E, [[0, 0]], [[float("nan"), 0]])


if __name__ == "__main__":
    unittest.main()
