import struct
from pathlib import Path

import numpy as np
import pytest

from scripts.pilot.world_map_lab.browser_mip_levels import chunk, chunks
from scripts.pilot.world_map_lab.browser_world_materials import (
    bake,
    layers,
    local_sphere,
    native_texture,
)
from scripts.pilot.world_map_lab.stream_world_cells import ROW, collect


def test_two_scene_lod_families_remain_local(tmp_path):
    files = [Path("a.ipl"), Path("b.ipl")]
    for file, delta in zip(files, [0, 100]):
        (tmp_path / file).write_text(
            "inst\n"
            + "".join(
                f"{id_ + delta}, test, 0, {x}, 20, 3, 0, 0, 0, 1, {parent}\n"
                for id_, x, parent in [(40, 509, 1), (41, 513, 2), (42, 515, -1), (43, -33, -1)]
            )
            + "end\n"
        )
    cells = collect(tmp_path, files)
    first = [ROW.unpack(i) for i in cells[0, 0]]
    assert [r[-1] for r in first] == [1, 2, -1, 4, 5, -1]
    assert [r[-3] for r in first] == [40, 41, 42, 140, 141, 142]
    assert [r[0] for r in first] == [509, 513, 515] * 2
    assert len(cells[-1, 0]) == 2


def test_terrain_mask_keeps_original_detail_and_channels():
    red = np.array([[[1, 2, 3, 255], [4, 5, 6, 255]]], np.uint8)
    green = red + 5
    mask = np.array([[[0, 0, 255, 255], [0, 255, 0, 255]]], np.uint8)
    names = (("red", 1), ("green", 1), ("", 1), ("", 1), ("mask", 1))
    images = {"red": red, "green": green, "mask": mask}
    out = bake(names, images.get)
    assert out[:, :, :3].tolist() == [[[1, 2, 3], [9, 10, 11]]]
    with pytest.raises(KeyError):
        bake(names, lambda n: images.get(n) if n != "green" else None)
    d = next(chunks(native_texture(out, "landtest", 1)))[2]
    header = next(chunks(d))[2]
    assert header[92:100] == out.tobytes() and header[85] == 2


def test_local_bounds_enclose_all_vertices_without_changing_geometry():
    pts = np.float32([[-2, 0, -1], [2, 2, 1], [0, -2, 0]])

    def sample(cx):
        return (
            struct.pack("<4I", 0, 0, len(pts), 1)
            + struct.pack("<4fII", cx, 0, 0, 4, 1, 0)
            + pts.tobytes()
        )

    broken = sample(2642)
    fixed = local_sphere(broken)
    assert fixed[:16] == broken[:16] and fixed[32:] == broken[32:]
    sphere = struct.unpack_from("<4f", fixed, 16)
    assert np.all(np.linalg.norm(pts - sphere[:3], axis=1) <= sphere[3])
    assert local_sphere(sample(0)) == sample(0)
    partial = sample(3)
    corrected = local_sphere(partial)
    assert corrected != partial
    assert corrected[:16] == partial[:16] and corrected[32:] == partial[32:]
    assert local_sphere(corrected) == corrected


def test_truncated_named_terrain_layer_is_rejected():
    with pytest.raises((ValueError, struct.error)):
        layers(struct.pack("<III", 9, 0, 1) + chunk(6, 1, b""))


def test_block_profile_keeps_resolution_alpha_and_every_source_mip():
    pytest.importorskip("ispc_texcomp")
    from io import BytesIO

    from PIL import Image

    from scripts.pilot.world_map_lab.browser_block_textures import block_native

    for alpha in (False, True):
        im = np.zeros((64, 128, 4), np.uint8)
        im[:, :, :] = [35, 102, 209, 255]
        if alpha:
            im[:, 64:, 3] = 0
        native = next(chunks(next(chunks(native_texture(im, "test", 1)))[2]))[2]
        result = block_native(native)
        assert result[:76] == native[:76] and result[80:87] == native[80:87]
        assert result[76:80] == (b"DXT5" if alpha else b"DXT1")
        offset = 88
        for level in range(native[85]):
            h, w = max(1, 64 >> level), max(1, 128 >> level)
            (size,) = struct.unpack_from("<I", result, offset)
            offset += 4
            assert size == ((w + 3) // 4) * ((h + 3) // 4) * (16 if alpha else 8)
            if level == 0:
                header = bytearray(128)
                struct.pack_into("<4s7I", header, 0, b"DDS ", 124, 0x81007, h, w, size, 0, 1)
                struct.pack_into("<II4s", header, 76, 32, 4, result[76:80])
                struct.pack_into("<I", header, 108, 0x1000)
                decoded = np.array(
                    Image.open(BytesIO(header + result[offset : offset + size])).convert("RGBA")
                )
                assert np.abs(decoded[15, 7].astype(int) - [209, 102, 35, 255]).max() <= 8
                assert decoded[15, 96, 3] == (0 if alpha else 255)
            offset += size
        assert offset == len(result)


def test_angular_confirmation_rejects_reused_pixels_and_inconsistent_pose():
    from scripts.pilot.world_map_lab.check_journey_rgb import H, W
    from scripts.pilot.world_map_lab.rgbd_keyframe_pose import KeyframePose

    rng = np.random.default_rng(12)
    k = np.array([[140.0, 0, W / 2], [0, 140.0, H / 2], [0, 0, 1]])
    uv = rng.uniform([20, 20], [W - 20, H - 20], (80, 2))
    z = rng.uniform(3, 18, len(uv))
    xyz = np.column_stack(((uv - k[:2, 2]) * z[:, None] / 140, z))
    assert KeyframePose.independent_views((xyz, uv), (xyz, uv), k)
    assert not KeyframePose.independent_views((xyz, uv), (xyz + [1, 0, 0], uv), k)
    same = ((uv[:, 0] // (W / 6) + uv[:, 1] // (H / 4)) % 2) == 0
    assert not KeyframePose.independent_views((xyz[same], uv[same]), (xyz[same], uv[same]), k)


def test_only_mixed_cutout_alpha_qualifies_for_sorted_drawing():
    from scripts.pilot.world_map_lab.browser_cutout_order import alpha_cutout

    assert alpha_cutout(np.array([0, 0, 255, 255], dtype=np.uint8))
    for samples in ([255, 255], [0, 0], [0, 100, 120, 200, 255]):
        assert not alpha_cutout(np.array(samples, dtype=np.uint8))
