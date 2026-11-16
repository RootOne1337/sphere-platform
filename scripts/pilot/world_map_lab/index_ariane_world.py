"""Create a revision-bound index of placement origins from active Ariane scenes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

TILE_SIZE = 128


def read_source(root):
    maps = (root / "data/maps").resolve(strict=True)
    manifest = root / "data/gta.dat"
    manifest_bytes = manifest.read_bytes()
    paths = []
    seen = set()
    for line in manifest_bytes.decode("utf-8-sig").splitlines():
        key, _, item = line.strip().partition(" ")
        if key.upper() != "IPL":
            continue
        scene = (root / item.replace("\\", "/").strip()).resolve(strict=True)
        if not scene.is_relative_to(maps) or scene.suffix.lower() != ".ipl" or scene in seen:
            raise ValueError(f"unexpected IPL entry: {item}")
        seen.add(scene)
        paths.append(scene)
    if not paths:
        raise ValueError("no active scenes")
    return hashlib.sha256(manifest_bytes).hexdigest(), paths


def read_instances(body, label):
    rows = []
    active = False
    for line_number, line in enumerate(body.decode("utf-8-sig").splitlines(), 1):
        text = line.strip()
        if text == "inst":
            active = True
        elif text == "end":
            active = False
        elif active and text and not text.startswith(("#", ";", "//")):
            fields = next(csv.reader([text], skipinitialspace=True))
            if len(fields) != 11:
                raise ValueError(f"invalid instance record: {label}:{line_number}")
            area = int(fields[2])
            point = tuple(float(coord) for coord in fields[3:6])
            lod = int(fields[10])
            if not all(map(math.isfinite, point)):
                raise ValueError(f"nonfinite placement: {label}:{line_number}")
            rows.append((area, point, lod))
    if active:
        raise ValueError(f"unterminated instance section: {label}")
    lods = {row[2] for row in rows if row[2] != -1}
    if any(not 0 <= index < len(rows) for index in lods):
        raise ValueError(f"invalid LOD reference: {label}")
    return rows, lods


def inventory(root, world_id):
    manifest_digest, paths = read_source(root)
    counts = Counter()
    tile_scenes = defaultdict(Counter)
    scenes = []
    for scene in paths:
        data = scene.read_bytes()
        label = scene.relative_to(root).as_posix()
        rows, lods = read_instances(data, label)
        exterior = 0
        for index, (area, point, _) in enumerate(rows):
            if index in lods or area != 0:
                continue
            key = tuple(math.floor(coord / TILE_SIZE) for coord in point[:2])
            counts[key] += 1
            tile_scenes[key][len(scenes)] += 1
            exterior += 1
        scenes.append(
            {
                "file": label,
                "sha256": hashlib.sha256(data).hexdigest(),
                "instances": len(rows),
                "lod_instances": len(lods),
                "exterior_instances": exterior,
            }
        )
    source = {"active_manifest_sha256": manifest_digest, "scenes": scenes}
    revision = hashlib.sha256(
        json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    tiles = [
        {"tile": [x, y], "placements": count, "scene_counts": sorted(tile_scenes[x, y].items())}
        for (x, y), count in sorted(counts.items())
    ]
    return {
        "schema": "sphere.world-placement-index.v1",
        "world_id": world_id,
        "placement_revision": revision,
        "tile_size_units": TILE_SIZE,
        "exterior_placements": counts.total(),
        "limits": "Tile membership reflects placement origins. Geometry extents and route accessibility require separate checks.",
        "source": source,
        "tiles": tiles,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--world-id", default="black-russia-ariane")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = inventory(args.root.resolve(strict=True), args.world_id)
    args.report.write_text(json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "scenes": len(report["source"]["scenes"]),
                "tiles": len(report["tiles"]),
                "exterior_placements": report["exterior_placements"],
                "placement_revision": report["placement_revision"],
            }
        )
    )


if __name__ == "__main__":
    main()
