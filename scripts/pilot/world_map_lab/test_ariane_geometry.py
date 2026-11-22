import gzip
import json
import struct
import unittest
from types import SimpleNamespace as NS

import numpy as np

from scripts.pilot.world_map_lab.ariane_geometry import scene_parts
from scripts.pilot.world_map_lab.build_detail_scene import layered_material, mesh_file
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


def test_street_pack_preserves_separate_source_mask_and_detail_coordinates():
    grass = np.full((8, 8, 4), (18, 50, 1, 255), np.uint8)
    mask = np.full((4, 4, 4), (255, 0, 0, 0), np.uint8)
    textures = NS(find=lambda _pack, name: {"grass": grass, "mask": mask}.get(name), texture_size=8)
    xyz = np.array([[0.0, 0, 0], [160, 0, 0], [0, 80, 0]])
    uv = np.array([[0.0, 0], [1, 0], [0, 1]])
    layer = layered_material(
        textures, "map", tuple((n, 1.0) for n in ("grass", "", "", "", "mask")), xyz, uv
    )

    def store(data):
        return ("mask" if data is mask else "grass"), False

    glb, _, _, _ = mesh_file([(xyz, uv, np.array([[0, 1, 2]]), np.array([0]), {0: layer})], store)
    decoded = gzip.decompress(glb)
    desc = json.loads(decoded[20 : 20 + struct.unpack_from("<I", decoded, 12)[0]])
    payload = desc["materials"][0]["extras"]["arianeTerrain"]
    assert payload["layers"] == [0, None, None, None, 1]
    assert payload["repeats"] == [1.0] * 5
    np.testing.assert_allclose(payload["detailRepeats"], [20.0, 10.0])
    assert desc["images"][1]["uri"].endswith("/mask.png")


if __name__ == "__main__":
    unittest.main()
