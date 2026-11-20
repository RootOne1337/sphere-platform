"""Replay an explicit walk, vehicle pickup, drive and final walk on the real map."""

import argparse
import json
import math
from pathlib import Path

from scripts.pilot.world_map_lab.world_navmesh import Network, checksum
from scripts.pilot.world_map_lab.world_trip import TripPlanner


def verify(folder):
    cases = json.loads((folder / "fixed-pair-recheck.json").read_bytes())
    with Network(folder, "walk") as walk, Network(folder, "drive") as drive:
        trip = TripPlanner({"drive": drive, "walk": walk}, folder)
        for rec in cases["trips"]:
            if rec["modes"] != ["drive", "walk"]:
                continue
            v, goal = rec["start"], rec["goal"]
            for radius in (15, 25, 50, 80):
                for i in range(16):
                    x = v[0] + radius * math.cos(i * math.pi / 8)
                    y = v[1] + radius * math.sin(i * math.pi / 8)
                    for h in walk.levels(x, y):
                        if abs(h - v[2]) > 3 or any(abs(z - h) < 0.5 for z in drive.levels(x, y)):
                            continue
                        start = [x, y, h]
                        res = trip.route(start, goal, v)
                        if [r["mode"] for r in res["legs"]] != ["walk", "drive", "walk"]:
                            continue
                        joins = [
                            math.dist(a["path"][-1], b["path"][0])
                            for a, b in zip(res["legs"], res["legs"][1:])
                        ]
                        if max(joins) > 0.3751:
                            raise ValueError("unjoined legs")
                        report = {
                            "start": start,
                            "vehicle": v,
                            "end": goal,
                            "length": res["length"],
                            "legs": [[r["mode"], r["length"]] for r in res["legs"]],
                            "joinErrors": joins,
                            "meshes": {
                                m: checksum(folder / f"{m}.nav.zip") for m in ("walk", "drive")
                            },
                        }
                        (folder / "mixed-validation.json").write_text(
                            json.dumps(report, indent=2), encoding="utf-8"
                        )
                        print(report)
                        return
    raise ValueError("no real three-leg case found")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", type=Path, required=True)
    verify(p.parse_args().folder)
