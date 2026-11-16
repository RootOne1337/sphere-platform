import unittest
from types import SimpleNamespace as NS

import numpy as np

from scripts.pilot.world_map_lab.ariane_geometry import scene_parts


def frame(position, parent=-1, name=None):
    return NS(position=position, parent=parent, name=name, rotation_matrix=np.eye(3))


class ArianePlacementFrameTest(unittest.TestCase):
    def test_static_model_uses_undamaged_geometry_in_ipl_frame(self):
        original = NS(vertices=[(1, 2, 3)])
        damaged = NS(vertices=[(5, 9, 8)])
        model = NS(
            clumps=[
                NS(
                    geometry_list=[original, damaged],
                    atomic_list=[NS(geometry=0, frame=0), NS(geometry=1, frame=1)],
                    frame_list=[frame((2266, -1767, 20)), frame((10, 0, 0), 0, "object_dam")],
                )
            ]
        )
        [(points, mesh)] = list(scene_parts(model, "objs"))
        np.testing.assert_array_equal(points, original.vertices)
        self.assertIs(mesh, original)

    def test_clump_keeps_child_offsets_but_replaces_root_frame(self):
        mesh = NS(vertices=[(1, 2, 3)])
        model = NS(
            clumps=[
                NS(
                    geometry_list=[mesh],
                    atomic_list=[NS(geometry=0, frame=2)],
                    frame_list=[
                        frame((2266, -1767, 20)),
                        frame((0, -4, 0), 0),
                        frame((5, 7, 8), 1),
                    ],
                )
            ]
        )
        [(points, _)] = list(scene_parts(model, "anim"))
        np.testing.assert_array_equal(points, [(6, 5, 11)])


if __name__ == "__main__":
    unittest.main()
