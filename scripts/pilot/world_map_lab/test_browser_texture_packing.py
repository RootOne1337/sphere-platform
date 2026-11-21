from struct import pack

import pytest

from scripts.pilot.world_map_lab.browser_mip_levels import trim_native
from scripts.pilot.world_map_lab.browser_solid_models import near_model_distances
from scripts.pilot.world_map_lab.compact_browser_textures import (
    dictionary,
    read_bindings,
    rewrite_ide,
    write_archive,
)
from scripts.pilot.world_map_lab.export_full_game_world import img_directory
from scripts.pilot.world_map_lab.stage_game_quarter import local_water, neutral_postfx
from scripts.pilot.world_map_lab.test_full_game_world import archive


def chunk(t, data):
    return pack("<III", t, len(data), 0x1803FFFF) + data


def tex(name, value):
    header = pack("<II32s32s", 9, 0, name.encode(), b"") + value
    return chunk(22, chunk(1, pack("<HH", 1, 2)) + chunk(21, chunk(1, header)) + chunk(3, b""))


def test_lossless_disjoint_merge_and_local_name_conflict(tmp_path):
    old, new = tmp_path / "old.img", tmp_path / "new.img"
    archive(
        old,
        [
            ("a.txd", tex("wall", b"one")),
            ("b.txd", tex("road", b"two")),
            ("c.txd", tex("WALL", b"three")),
            ("street.dff", b"original mesh"),
        ],
    )
    mapping = {}
    assert write_archive(old, new, 2, mapping) == 2
    assert mapping["a"] == mapping["b"] and mapping["a"] != mapping["c"]
    directories = img_directory(new)
    with new.open("rb") as stream:
        for key, expected in [("a", [b"wall", b"road"]), ("c", [b"wall"])]:
            _, start, size = directories[mapping[key] + ".txd"]
            _, records = dictionary(stream, start, size)
            assert [record[0] for record in records] == expected
        _, start, size = directories["street.dff"]
        stream.seek(start)
        assert stream.read(size).rstrip(b"\0") == b"original mesh"


def test_truncated_dictionary_stops_packing(tmp_path):
    source = tmp_path / "bad.img"
    archive(source, [("road.txd", pack("<III", 22, 4096, 0))])
    with pytest.raises(ValueError, match="truncated"):
        write_archive(source, tmp_path / "out.img", 0, {})


def test_water_keeps_original_faces_enclosing_the_sector(tmp_path):
    def quad(x, y):
        return (
            " ".join(
                f"{a} {b} 3 0 0 0 0"
                for a, b in ((x, y), (x + 20, y), (x, y + 20), (x + 20, y + 20))
            )
            + " 1"
        )

    source = tmp_path / "source.dat"
    source.write_text("\n".join(["processed", quad(0, 0), quad(20, 0)]))
    result = tmp_path / "local.dat"
    local_water(source, result, [3, 5, 1, 2])
    assert result.read_text().splitlines() == ["processed", quad(0, 0)]


def test_shadowed_and_missing_materials_keep_original_resolution(tmp_path):
    old, new = tmp_path / "original.img", tmp_path / "packed.img"
    archive(
        old,
        [
            ("shared.txd", tex("road", b"parent")),
            ("a.txd", tex("wall", b"wall")),
            ("b.txd", tex("road", b"near")),
            ("c.txd", tex("sign", b"sign")),
        ],
    )
    parents = dict(a="shared", b="shared", c="shared")
    # Model a needs the road from its parent. Adding b to that pack would change it.
    used = {"a": {b"wall", b"road"}, "b": {b"road"}, "c": {b"sign"}}
    binding = {}
    assert write_archive(old, new, 0, binding, parents, used) == 3
    assert binding["shared"] not in {binding["a"], binding["b"], binding["c"]}
    assert binding["a"] != binding["b"]
    rows = [
        "objs",
        "1001, floor, a, 240, 0",
        "end",
        "",
        "txdp",
        "a shared",
        "b shared",
        "end",
        "",
        "txdp",
        "c shared",
        "end",
    ]
    rewritten_models, rewritten_parents = read_bindings(rewrite_ide(rows, binding))
    assert rewritten_models == {"floor": binding["a"]}
    assert rewritten_parents == {binding[k]: binding["shared"] for k in parents}


def test_near_collision_distances_keep_far_mixed_and_noncollidable_models():
    names = ["road", "landmark", "shared", "wall", "small"]
    ide = [
        "objs",
        *(f"{i}, {n}, a, {90 if n == 'small' else 500}, 0" for i, n in enumerate(names)),
        "end",
    ]
    scene = [
        "inst",
        "0,road,1",
        "1,landmark,-1",
        "2,shared,-1",
        "0,road,2",
        "2,shared,-1",
        "4,small,-1",
        "3,wall,-1",
        "end",
    ]
    result, report = near_model_distances("\n".join(ide), ["\n".join(scene)], set(names) - {"wall"})
    assert report == {"changed": {"road": 500}, "mixedRoles": ["shared"]}
    assert "0, road, a, 150, 0" in result and "4, small, a, 90, 0" in result


def test_neutral_postfx_retains_weather_and_unrecognised_rows(tmp_path):
    source, output = tmp_path / "source.dat", tmp_path / "out.dat"
    row = list(map(str, range(51)))
    source.write_text("// Noon\n" + " ".join(row) + "\n1 2 3\n")
    report = neutral_postfx(source, output)
    changed = row.copy()
    changed[40] = changed[44] = "0"
    assert output.read_text().splitlines() == ["// Noon", " ".join(changed), "1 2 3"]
    assert source.read_text().splitlines()[1] == " ".join(row)
    assert report == {"neutralRows": 1, "unknownLayoutPreserved": 1}


def test_external_parent_in_game_dictionary_keeps_its_name():
    rows = ["txdp", "wall generic", "end"]
    assert read_bindings(rewrite_ide(rows, {"wall": "bank0"}))[1] == {"bank0": "generic"}


def test_mip_selection_preserves_the_original_samples_and_metadata():
    header = bytearray(88)
    header[:4] = pack("<I", 9)
    header[4] = 6
    header[76:86] = pack("<IHHBB", 21, 4, 2, 32, 3)
    fine, middle, coarse = bytes(range(32)), bytes(range(8)), b"RGBA"
    data = header + b"".join(pack("<I", len(level)) + level for level in (fine, middle, coarse))
    trimmed = trim_native(data, 2)
    assert trimmed[:80] == data[:80]
    assert trimmed[80:88] == pack("<HHBBBB", 2, 1, 32, 2, 0, 0)
    assert trimmed[88:] == pack("<I", 8) + middle + pack("<I", 4) + coarse
    with pytest.raises(ValueError, match="length mismatch"):
        trim_native(data[:-1], 2)
