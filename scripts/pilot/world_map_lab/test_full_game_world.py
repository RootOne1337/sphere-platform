import hashlib
import json
import struct

import pytest

from scripts.pilot.world_map_lab.audit_game_runtime import GAME_FILES
from scripts.pilot.world_map_lab.export_full_game_world import build, check_scene, img_directory
from scripts.pilot.world_map_lab.native_collisions import COL, ENTRY, SECTOR
from scripts.pilot.world_map_lab.open_classic_stand import prepare_full
from scripts.pilot.world_map_lab.stage_full_game_world import stage


def archive(path, records):
    with path.open("wb") as f:
        f.write(struct.pack("<4sI", b"VER2", len(records)))
        for i, (name, _) in enumerate(records):
            f.write(ENTRY.pack(i + 1, 1, 0, name.encode()))
        f.seek(SECTOR)
        for _, payload in records:
            f.write(payload.ljust(SECTOR, b"\0"))


def chunk(kind, content):
    return struct.pack("<III", kind, len(content), 0) + content


def test_full_map_preserves_overrides_independent_scenes_and_gameplay(tmp_path):
    source = tmp_path / "source"
    data = source / "data"
    models = source / "models"
    models.mkdir(parents=True)
    data.mkdir()
    mesh = chunk(0x2B, b"uv") + chunk(0x10, b"new")
    archive(
        models / "a.img",
        [
            ("shop.dff", chunk(0x10, b"old")),
            ("shop.txd", chunk(0x16, b"texture")),
            ("models.col", COL.pack(b"COL3", COL.size - 8, b"shop", 42)),
        ],
    )
    archive(models / "b.img", [("shop.dff", mesh)])
    (data / "default.dat").write_text("IMG models/a.img\nIDE data/m.ide\nIMG models/b.img\n")
    (data / "gta.dat").write_text("IPL data/a/same.ipl\nIPL data/b/same.ipl\n")
    (data / "m.ide").write_text("objs\n1000, shop, shop, 100, 0\nend\n")
    for i, area in enumerate(("a", "b")):
        (data / area).mkdir()
        (data / area / "same.ipl").write_text(
            f"inst\n1000,shop,{i},1,2,3,0,0,0,1,1\n1000,shop,{i},1,2,3,0,0,0,1,-1\nend\n"
        )
    for name in ("water.dat", "timecyc.dat"):
        (data / name).write_text("processed\n" if name == "water.dat" else "world settings")
    scenario = tmp_path / "scenario"
    scenario.mkdir()
    route = tmp_path / "route.json"
    route.write_bytes(b"route")
    hashes = {}
    for name in ("main.scm", "script.img"):
        payload = name.encode()
        (scenario / name).write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    (scenario / "classic-scenario.json").write_text(
        json.dumps({"files": hashes, "routeSha256": hashlib.sha256(route.read_bytes()).hexdigest()})
    )
    world = tmp_path / "world"
    info = build(source, world, limit=SECTOR * 3, scenario=scenario, route=route)
    assert (info["instances"], info["lodLinks"], info["reboundCollisionIds"]) == (4, 2, 1)
    assert len(info["archives"]) == 2
    assert len({s["packaged"] for s in info["scenes"]}) == 2
    restored = {}
    for a in info["archives"]:
        restored.update(img_directory(world / "data/maps/brworld" / a["name"]))
    for name, expected in (
        ("shop.dff", mesh),
        ("models.col", COL.pack(b"COL3", 24, b"shop", 1000)),
    ):
        bank, offset, _ = restored[name]
        with bank.open("rb") as f:
            f.seek(offset)
            assert f.read(len(expected)) == expected
    game = tmp_path / "game"
    for name in (*GAME_FILES, "gta_sa.exe", "models/player.img"):
        target = game / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    for name in ("gta.dat", "default.dat"):
        (game / "data" / name).write_text("IPL old.ipl\nEXIT\n")
    (game / "data/default.dat").write_text("IDE data/stock.ide\nEXIT\n")
    (game / "data/stock.ide").write_text("objs\n1000,stock,tex,100,0\nend\n")
    dest = tmp_path / "merged"
    stage(game, world, dest, scenario)
    dat = (dest / "data/gta.dat").read_text()
    assert dat.count("IMG ") == 2 and dat.count("IPL ") == 2 and "old.ipl" not in dat
    assert (game / "data/gta.dat").read_text() == "IPL old.ipl\nEXIT\n"
    assert (dest / "data/script/main.scm").read_bytes() == b"main.scm"
    final_map = dest / "data/maps/brworld"
    assert "1001, shop," in (final_map / "brworld.ide").read_text()
    assert all("1001,shop," in f.read_text() for f in final_map.glob("*.ipl"))
    index = {}
    for a in info["archives"]:
        index.update(img_directory(final_map / a["name"]))
    archive_file, off, _ = index["models.col"]
    with archive_file.open("rb") as f:
        f.seek(off)
        assert COL.unpack(f.read(COL.size))[-1] == 1001
    details = json.loads((dest / "sphere-full-world.json").read_text())
    assert details["binding"]["remappedInstances"] == 4
    assert details["binding"]["remappedCollisions"] == 1
    assert not details["gameplayVerified"]
    assert prepare_full(game, world, scenario, dest) == dest / "gta_sa.exe"
    (dest / "data/gta.dat").write_text("EXIT\n")
    with pytest.raises(ValueError, match="стенда"):
        prepare_full(game, world, scenario, dest)
    damaged = world / "data/maps/brworld/brw00.img"
    damaged.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="checksum mismatch"):
        stage(game, world, tmp_path / "corrupt", scenario)
    assert not (tmp_path / "corrupt").exists()


@pytest.mark.parametrize("target", [0, 3, -2])
def test_invalid_or_cyclic_lod_cannot_be_published(tmp_path, target):
    path = tmp_path / "bad.ipl"
    path.write_text(f"inst\n1000,shop,0,0,0,0,0,0,0,1,{target}\nend")
    with pytest.raises(ValueError, match="LOD"):
        check_scene(path, {"shop": 1000})
