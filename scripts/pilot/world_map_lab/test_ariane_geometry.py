import unittest
from types import SimpleNamespace as NS

import numpy as np

from scripts.pilot.world_map_lab.ariane_geometry import scene_parts
from scripts.pilot.world_map_lab.render_ariane_world import compose_terrain_layers


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


def test_detail_terrain_keeps_original_layer_texture_and_mask():
    grass = np.full((4, 4, 4), 255, np.uint8)
    grass[:, :, :3] = (0, 255, 0)
    grass[:, 1::2, :3] = (0, 64, 0)
    rock = np.full((4, 4, 4), 120, np.uint8)
    mask = np.zeros((4, 4, 4), np.uint8)
    mask[:, :2, 0] = 255
    mask[:, 2:, 1] = 255
    detailed = compose_terrain_layers([grass, rock, None, None, mask], [1.0] * 5, 1024)
    np.testing.assert_array_equal(detailed[:, :2, :3], grass[:, :2, :3])
    np.testing.assert_array_equal(detailed[:, 2:, :3], rock[:, 2:, :3])
    assert np.all(detailed[..., 3] == 255)


if __name__ == "__main__":
    unittest.main()
