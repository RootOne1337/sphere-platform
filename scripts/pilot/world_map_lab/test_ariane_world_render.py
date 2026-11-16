import unittest
from struct import pack

from scripts.pilot.world_map_lab.render_ariane_world import splat_textures


def chunk(kind, value):
    return pack("<3I", kind, len(value), 0x1803FFFF) + value


def matfx(layers):
    return (
        pack("<2I", 9, 9)
        + b"".join(
            pack("<f", tile)
            + chunk(6, chunk(1, pack("<I", 2)) + chunk(2, name.encode("ascii") + b"\0"))
            for tile, name in enumerate(layers, 1)
        )
        + pack("<f", 0)
    )


class ArianeTerrainTest(unittest.TestCase):
    def test_matfx9_reads_all_layer_names_followed_by_mask(self):
        layers = ("Sand", "Rock", "Grass", "Soil", "Mask")
        self.assertEqual(splat_textures(matfx(layers)), ("sand", "rock", "grass", "soil", "mask"))

    def test_matfx9_rejects_an_incomplete_mask_texture(self):
        self.assertEqual(splat_textures(matfx(("a", "b", "c", "d", "e"))[:-6]), ())


if __name__ == "__main__":
    unittest.main()
