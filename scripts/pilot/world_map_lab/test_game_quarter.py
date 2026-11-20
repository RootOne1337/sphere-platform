import hashlib
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from scripts.pilot.world_map_lab.audit_game_runtime import GAME_FILES
from scripts.pilot.world_map_lab.export_game_quarter import collect_placements
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
        "col": "col",
        "img": "img",
    }.items():
        (quarter / ("brquarter." + name)).write_text(data)
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
    assert dat.index("brquarter.ipl") < dat.index("EXIT") and "old_world" not in dat
    assert "old_world" in (game / "data/gta.dat").read_text()
    assert "old_default" in (game / "data/default.dat").read_text()
    assert "old_default" not in (target / "data/default.dat").read_text()
    assert json.loads((target / "sphere-scenario.json").read_bytes())["models"] == {"shop": 1001}


def test_lods_remain_local_when_two_districts_have_the_same_ipl_name(tmp_path):
    def district(label):
        return [
            SimpleNamespace(name=label, area=0, ordinal=0, lod=1, position=(0, 0, 0)),
            SimpleNamespace(name="lod_" + label, area=0, ordinal=1, lod=-1, position=(1, 1, 1)),
        ]

    sources = {
        tmp_path / "west" / "other.ipl": district("house"),
        tmp_path / "east" / "other.ipl": district("shop"),
    }
    reader = SimpleNamespace(
        active_paths=sources.keys, read_scene=lambda path: (sources[path], {1})
    )
    items, links, near = collect_placements(
        reader, Counter({("house", 0, 0, 0): 1, ("shop", 0, 0, 0): 1})
    )
    assert near == 2
    assert [item.name for item in items] == ["house", "lod_house", "shop", "lod_shop"]
    assert links == [1, -1, 3, -1]
