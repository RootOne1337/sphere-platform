"""Replay the same XYZ pairs against a new bake and verify local control sections."""

import argparse
import json
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from scripts.pilot.world_map_lab.world_navmesh import Network
from scripts.pilot.world_map_lab.world_trip import TripPlanner


def recheck(folder, baseline):
    control = json.loads(baseline.read_bytes())
    result = {}
    with ExitStack() as stack:
        nets = {k: stack.enter_context(Network(folder, k)) for k in ("drive", "walk")}
        trip = TripPlanner(nets, folder)
        for mode, net in nets.items():
            records = []
            for old in control[mode]["pairs"]:
                path = net.route(old["start"], old["end"])
                records.append(
                    {
                        "start": old["start"],
                        "end": old["end"],
                        "before": old["status"],
                        "after": path["status"],
                        "length": path["length"],
                    }
                )
            result[mode] = {
                "pairs": records,
                "transitions": dict(Counter(r["before"] + " -> " + r["after"] for r in records)),
            }
        test_sections = {
            "Уклон северо-западной дороги": ([-1302, 1906, 36.5], [-1299, 1879, 44]),
            "Точка у кромки перекрёстка Арзамаса": ([707, 633, 11], [711, 620, 11]),
            "Проезжая часть того же перекрёстка": ([702, 633, 11], [711, 620, 11]),
            "Поперечная разметка": ([696, 2415, 12], [684, 2421, 12]),
        }
        result["sections"] = {}
        for name, (a, b) in test_sections.items():
            observations = []
            for p in (a, b):
                levels = nets["drive"].levels(*p[:2])
                observations.append(levels)
                if levels:
                    p[2] = min(levels, key=lambda z: abs(z - p[2]))
            result["sections"][name] = {
                "start": a,
                "end": b,
                "levels": observations,
                **nets["drive"].route(a, b),
            }
        examples = []
        # Cross-mode tests use the original car starts and independently sampled walking goals.
        for car, foot in zip(
            control["drive"]["pairs"][:12], control["walk"]["pairs"][:12], strict=True
        ):
            a, b = car["start"], foot["end"]
            r = trip.route(a, b)
            examples.append({"start": a, "goal": b, "modes": [s["mode"] for s in r["legs"]], **r})
        result["trips"] = examples
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    args = p.parse_args()
    r = recheck(args.folder, args.baseline)
    (args.folder / "fixed-pair-recheck.json").write_text(
        json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print({k: r[k]["transitions"] for k in ("drive", "walk")})
    print({k: (s["status"], round(s["length"], 1)) for k, s in r["sections"].items()})
    print(Counter(tuple(t["modes"]) for t in r["trips"]))
