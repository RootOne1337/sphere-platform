import struct

import numpy as np
import pytest

from scripts.pilot.world_map_lab.browser_mip_levels import chunk
from scripts.pilot.world_map_lab.browser_world_materials import payload
from scripts.pilot.world_map_lab.check_world_fidelity import (
    INSTANCE,
    cell_rows,
    collisions,
    count_parented,
    model_signature,
    placed,
    source_rows,
)
from scripts.pilot.world_map_lab.inspect_world_cells import sample_sites
from scripts.pilot.world_map_lab.native_collisions import COL


def test_missing_fence_and_wrong_lod_are_detected_after_repacking(tmp_path):
    # Source and native use unrelated model IDs. Two identical bushes still count twice.
    scene = tmp_path / "source.ipl"
    scene.write_text(
        "inst\n2,fence,0,1,2,3,0,0,0,1,1\n3,low,0,1,2,3,0,0,0,1,-1\n"
        + "4,bush,0,4,2,3,0,0,0,1,-1\n" * 2
        + "end\n"
    )
    expected, gaps = source_rows(tmp_path, scene.name, {"fence": 2, "low": 3, "bush": 4})
    names = {100: "fence", 101: "low", 102: "bush"}

    def capture(rows):
        return cell_rows(
            b"BRC1"
            + struct.pack("<I", len(rows))
            + b"".join(INSTANCE.pack(x, 2, 3, 0, 0, 0, 1, i, 0, lod) for x, i, lod in rows),
            names,
        )

    rows = [(4, 102, -1), (4, 102, -1), (1, 101, -1), (1, 100, 2)]
    assert not gaps and capture(rows) == expected
    assert (expected - capture(rows[:-1])).total() == 1
    wrong_parent = [*rows[:-1], (1, 100, 0)]
    assert (expected - capture(wrong_parent)).total() == 1
    wrong_position = [*rows[:-1], (1.125, 100, 2)]
    assert (expected - capture(wrong_position)).total() == 1
    with pytest.raises(ValueError, match="LOD"):
        capture([*rows[:-1], (1, 100, 9)])


def test_actor_area_and_rotation_are_part_of_instance_identity():
    def key(area, rotation):
        return count_parented([(placed("bush", area, [1, 2, 3, *rotation]), -1)])

    assert key(0, [0, 0, 0, 1]) != key(1, [0, 0, 0, 1])
    assert key(0, [0, 0, 0, 1]) != key(0, [0, 0, 1, 0])


def test_geometry_fingerprint_catches_vertex_and_uv_changes_and_ignores_bound_refit():
    def mesh(vertex=1, uv=0.3, radius=1):
        data = (
            struct.pack("<4I", 4, 0, 1, 1)
            + struct.pack("<2f", uv, 0.6)
            + struct.pack("<4fII", 0, 0, 0, radius, 1, 0)
            + struct.pack("<3f", vertex, 0.4, 0.7)
        )
        return chunk(16, 1, chunk(26, 1, chunk(15, 1, chunk(1, 1, data))))

    assert model_signature(mesh()) == model_signature(mesh(radius=87))
    assert model_signature(mesh()) != model_signature(mesh(vertex=2))
    assert model_signature(mesh()) != model_signature(mesh(uv=0.7))


def test_animated_model_reader_includes_clump_after_uv_dictionary(tmp_path):
    value = chunk(0x2B, 1, b"animation") + chunk(16, 1, b"geometry")
    f = tmp_path / "bank"
    f.write_bytes(value + b"\x00" * 32)
    assert payload({"model.dff": (f, 0, f.stat().st_size)}, "model.dff") == value


def test_collision_id_can_change_but_original_shapes_must_match():
    def read(ident, body):
        return next(collisions(COL.pack(b"COL3", COL.size - 8 + len(body), b"fence", ident) + body))

    left = read(1, b"original")
    assert left[2] == read(102, b"original")[2] and left[2] != read(102, b"changed!")[2]


def test_grid_inspection_uses_only_real_polygon_vertices(tmp_path):
    dtype = [("xyz", "<f4", (6, 3)), ("vertices", "<u4")]
    faces = np.zeros(1, dtype=dtype)
    faces["vertices"] = 3
    faces["xyz"][0, :3] = [[524, 0, 3], [530, 0, 3], [527, 12, 3]]
    f = tmp_path / "faces.npz"
    np.savez(f, faces=faces, geometry="same")
    result = sample_sites({(1, 0), (-5, 3)}, [f])
    assert len(result["sites"]) == 1 and result["sites"][0]["ground"] == [527, 4, 3]
    assert result["cellsWithoutSample"] == [(-5, 3)]


def test_native_draw_distance_restoration_preserves_collision_role_and_timed_fields():
    from scripts.pilot.world_map_lab.restore_world_ranges import original_ranges

    lines = ["tobj", "17, fence, pack, 150, 4, 8, 23", "end"]
    restored, ids = original_ranges(lines, {"fence": 299.0})
    assert restored[1] == "17, fence, pack, 299, 4, 8, 23"
    assert ids == {17}
    row = INSTANCE.pack(1, 2, 3, 0, 0, 0, 1, 17, 0, -1)
    head = b"BRC2" + struct.pack("<I", 1)
    assert cell_rows(head + row + struct.pack("<I", 1), {17: "fence"}, ids).total() == 1
    with pytest.raises(ValueError, match="role"):
        cell_rows(head + row + struct.pack("<I", 0), {17: "fence"}, ids)
    with pytest.raises(ValueError, match="unexpected"):
        original_ranges(restored, {"fence": 299.0})


def test_search_rechecks_coasting_range_without_advancing_last_known_position():
    from scripts.pilot.world_map_lab.rgbd_keyframe_pose import search_station

    assert search_station(15, 12, 2.5, 1) > 45
    assert search_station(15, 12, 2.5, 4) == 15
    assert search_station(15, 0, 3, 1) == 15
    assert search_station(15, 20, 60, 1) <= 15 + 48
