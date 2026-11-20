import hashlib
import json
import struct
from collections import Counter
from types import SimpleNamespace

import pytest

from scripts.pilot.world_map_lab.audit_game_runtime import GAME_FILES
from scripts.pilot.world_map_lab.export_game_quarter import collect_placements
from scripts.pilot.world_map_lab.native_collisions import bind_collisions, write_game_img
from scripts.pilot.world_map_lab.native_route import course_gates, native_route
from scripts.pilot.world_map_lab.open_classic_stand import prepare
from scripts.pilot.world_map_lab.stage_game_quarter import remap, stage


def test_game_slots_and_native_placements_stay_bound():
    defs, places, slots = remap(
        "objs\n18, shop, city, 80, 0\nend",
        "inst\n18, shop, 0, 2, 3, 4, 0, 0, 0, 1, -1\nend",
        {1000},
    )
    assert slots == {"shop": 1001}
    assert "1001, shop" in defs and "1001, shop" in places
    with pytest.raises(ValueError, match="unbound"):
        remap("objs\nend", "inst\n17, unknown, 0, 1, 2, 3", set())


def test_stage_checks_assets_and_keeps_stock_world_intact(tmp_path):
    game, quarter, target = (tmp_path / s for s in ("base", "quarter", "output"))
    quarter.mkdir()
    game.mkdir()
    with pytest.raises(ValueError, match="missing gameplay"):
        stage(game, quarter, target)
    assert not target.exists()
    for name in GAME_FILES:
        p = game / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"test fixture")
    (game / "data/default.dat").write_text("IDE data/cars.ide\nIPL old_default.ipl\nEXIT\n")
    (game / "data/cars.ide").write_text("cars\n1000, preserved, car, 10, 0\nend\n")
    (game / "data/gta.dat").write_text("IPL old_world.ipl\nEXIT\n")
    for name, data in {
        "ide": "objs\n18, shop, town, 80, 0\nend",
        "ipl": "inst\n18, shop, 0, 2, 3, 4, 0, 0, 0, 1, -1\nend",
    }.items():
        (quarter / ("brquarter." + name)).write_text(data)
    (quarter / "brquarter.col").write_bytes(struct.pack("<4sI22sH", b"COL3", 24, b"shop", 12868))
    (quarter / "brquarter.img").write_bytes(
        struct.pack("<4sIIHH24s", b"VER2", 1, 1, 1, 0, b"shop.dff").ljust(2048, b"\0")
        + b"dff".ljust(2048, b"\0")
    )
    for name in ("water.dat", "timecyc.dat"):
        (quarter / name).write_bytes(b"BR environment")
        (game / "data" / name).write_bytes(b"stock environment")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in quarter.iterdir()}
    (quarter / "manifest.json").write_text(
        json.dumps(
            {
                "hashes": hashes,
                "revision": "test",
                "start": [0, 0, 0],
                "vehicle": [1, 1, 0],
                "end": [2, 2, 0],
            }
        )
    )
    stage(game, quarter, target)
    dat = (target / "data/gta.dat").read_text()
    assert dat.index("BRQUARTER.IPL") < dat.index("EXIT") and "old_world" not in dat
    assert "COLFILE" not in dat
    for name in ("water.dat", "timecyc.dat"):
        assert (target / "data" / name).read_bytes() == b"BR environment"
        assert (game / "data" / name).read_bytes() == b"stock environment"
    img = (target / "data/maps/sphere_native/brquarter.img").read_bytes()
    col_at = struct.unpack_from("<I", img, 40)[0] * 2048
    assert struct.unpack_from("<4sI22sH", img, col_at)[-1] == 1001
    assert "old_world" in (game / "data/gta.dat").read_text()
    assert "old_default" in (game / "data/default.dat").read_text()
    assert "old_default" not in (target / "data/default.dat").read_text()
    assert json.loads((target / "sphere-scenario.json").read_bytes())["models"] == {"shop": 1001}
    # Exercise the desktop entry point with a file fixture. Never execute a test binary.
    raw = b'{"legs":[]}'
    (quarter / "route.json").write_bytes(raw)
    proof = json.loads((quarter / "manifest.json").read_bytes())
    proof["routeSha256"] = proof["hashes"]["route.json"] = hashlib.sha256(raw).hexdigest()
    (quarter / "manifest.json").write_text(json.dumps(proof))
    classic = tmp_path / "scenario"
    classic.mkdir()
    files = {}
    for name in ("main.scm", "script.img"):
        (classic / name).write_bytes(b"authored script")
        files[name] = hashlib.sha256(b"authored script").hexdigest()
    (classic / "classic-scenario.json").write_text(
        json.dumps(dict(routeSha256=proof["routeSha256"], files=files))
    )
    (game / "gta_sa.exe").write_bytes(b"fixture only")
    (game / "models/player.img").write_bytes(b"fixture only")
    output = tmp_path / "desktop"
    assert prepare(game, quarter, classic, output) == output / "gta_sa.exe"
    assert prepare(game, quarter, classic, output) == output / "gta_sa.exe"
    assert (game / "data/script/main.scm").read_bytes() == b"test fixture"
    (output / "data/script/main.scm").write_bytes(b"stale")
    with pytest.raises(ValueError, match="другой сборке"):
        prepare(game, quarter, classic, output)


def test_lods_remain_local_when_two_districts_have_the_same_ipl_name(tmp_path):
    q = (0, 0, 0, 1)

    def district(label):
        return [
            SimpleNamespace(name=label, area=0, ordinal=0, lod=1, position=(0, 0, 0), quat=q),
            SimpleNamespace(name="lod_" + label, area=0, ordinal=1, lod=-1, position=(1, 1, 1)),
        ]

    sources = {
        tmp_path / "west" / "other.ipl": district("house"),
        tmp_path / "east" / "other.ipl": district("shop"),
    }
    reader = SimpleNamespace(
        active_paths=sources.keys,
        ariane_rotation=lambda quat: SimpleNamespace(as_quat=lambda: quat),
        read_scene=lambda path: (sources[path], {1}),
    )
    items, links, near = collect_placements(
        reader, Counter({("house", 0, 0, 0, *q): 1, ("shop", 0, 0, 0, *q): 1})
    )
    assert near == 2
    assert [item.name for item in items] == ["house", "lod_house", "shop", "lod_shop"]
    assert links == [1, -1, 3, -1]


def test_streamed_collision_crosses_img_directory_boundary(tmp_path):
    # 63 entries fit in one directory sector. The 64th starts sector two.
    header = struct.pack("<4sI", b"VER2", 63)
    for i in range(63):
        header += struct.pack("<IHH24s", i + 1, 1, 0, f"{i}.dff".encode())
    a, b = tmp_path / "old.img", tmp_path / "new.img"
    a.write_bytes(header.ljust(2048, bytes(1)) + b"".join(bytes([i]) * 2048 for i in range(63)))
    collider = struct.pack("<4sI22sH", b"COL3", 24, b"shop", 12868)
    data = bind_collisions(collider, {"shop": 1005})
    write_game_img(a, b, data)
    packed = b.read_bytes()
    assert struct.unpack_from("<I", packed, 8)[0] == 2
    assert packed[2 * 2048 : 65 * 2048] == a.read_bytes()[2048:]
    assert packed[65 * 2048 : 65 * 2048 + len(data)] == data
    assert struct.unpack_from("<H", data, 30)[0] == 1005
    with pytest.raises(ValueError, match="unbound"):
        bind_collisions(collider, {"tree": 1002})


def test_native_route_uses_all_three_legs(tmp_path):
    legs = [
        {"mode": m, "path": [[x, 0, 0], [x + 3, 0, 0]]}
        for x, m in ((0, "walk"), (3, "drive"), (6, "walk"))
    ]
    p = tmp_path / "route.json"
    p.write_text(json.dumps({"legs": legs}))
    _, trip, digest = native_route(p)
    assert trip == dict(start=[0, 0, 0], vehicle=[3, 0, 0], end=[9, 0, 0])
    assert digest == hashlib.sha256(p.read_bytes()).hexdigest()
    assert course_gates([[0, 0, 0], [10, 0, 0], [10, 10, 0]]) == [
        [0, 0, 0],
        [6, 0, 0],
        [10, 2, 0],
        [10, 8, 0],
        [10, 10, 0],
    ]
    legs[1]["path"][0][2] = 4
    p.write_text(json.dumps({"legs": legs}))
    with pytest.raises(ValueError, match="gap"):
        native_route(p)
