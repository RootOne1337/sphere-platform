"""Package a local quarter in GTA's native IMG, IPL, IDE and COL formats for gameplay testing."""

import argparse
import hashlib
import json
import math
import sqlite3
import struct
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.collect_ariane_nav_geometry import collider_records
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter
from scripts.pilot.world_map_lab.render_ariane_world import texture_parents


def img(path, entries):
    sector = math.ceil((8 + 32 * len(entries)) / 2048)
    table = bytearray(struct.pack("<4sI", b"VER2", len(entries)))
    for name, blob in entries:
        sectors = math.ceil(len(blob) / 2048)
        if len(name.encode("ascii")) > 23 or not 0 < sectors < 65536:
            raise ValueError(f"unsupported GTA IMG entry {name}")
        table.extend(struct.pack("<IHH24s", sector, sectors, 0, name.encode("ascii")))
        sector += sectors
    with path.open("wb") as f:
        f.write(table)
        f.write(bytes(-len(table) % 2048))
        for _, blob in entries:
            f.write(blob)
            f.write(bytes(-len(blob) % 2048))


def collect_placements(geometry, points):
    places, lods = [], []
    near_count = 0
    # Resolve ordinals before merging. Several unrelated source IPLs are named other.ipl.
    for path in geometry.active_paths():
        scene, targets = geometry.read_scene(path)
        selected = []
        for item in scene:
            key = (item.name, *item.position)
            if item.area == 0 and item.ordinal not in targets and points[key]:
                selected.append(item)
                points[key] -= 1
        near_count += len(selected)
        local = {item.ordinal: len(places) + i for i, item in enumerate(selected)}
        for item in selected:
            if item.lod >= 0 and item.lod not in local:
                local[item.lod] = len(places) + len(selected)
                selected.append(scene[item.lod])
        lods.extend(local[item.lod] if item.lod >= 0 else -1 for item in selected)
        places.extend(selected)
    if sum(points.values()) or not places:
        raise ValueError("source IPL differs from the indexed scene")
    return places, lods, near_count


def package(source, folder, adapter, destination):
    if destination.exists():
        raise FileExistsError(destination)
    geometry = load_local_adapter(source, adapter)
    city = json.loads((folder / "journey/city-trip.json").read_bytes())
    x, y, _ = city["vehicle"]
    bounds = [x - 175, x + 175, y - 175, y + 175]
    with closing(
        sqlite3.connect(
            (folder / "detail-scene.sqlite").resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
    ) as conn:
        rows = conn.execute(
            "select m.name,i.x,i.y,i.z from spatial s join instance i on i.id=s.id join model m on m.id=i.model where s.maxx>=? and s.minx<=? and s.maxy>=? and s.miny<=?",
            bounds,
        ).fetchall()
        revision = json.loads(conn.execute("select value from meta").fetchone()[0])["revision"]
    places, lod_indices, near_count = collect_placements(geometry, Counter(rows))
    names = {p.name for p in places}
    ide = (source / "data/br_map.ide").read_text(encoding="utf-8-sig")
    models = {}
    blocks = defaultdict(list)
    required = set()
    section = ""
    for line in ide.splitlines():
        row = [p.strip() for p in line.split(",")]
        if len(row) == 1:
            section = row[0].lower()
            continue
        if section in ("objs", "tobj", "anim") and len(row) >= 4 and row[1] in names:
            models[row[1]] = int(row[0])
            required.add(row[2].lower())
            blocks[section].append(line)
    if set(models) != names:
        raise ValueError("placement has no source IDE definition")
    parents = texture_parents(source)
    queue = list(required)
    while queue:
        parent = parents.get(queue.pop())
        if parent and parent not in required:
            required.add(parent)
            queue.append(parent)
    archives = source / "models/img"
    index = geometry.index_files(
        sorted(archives.glob("br_*.img"))
        + [
            archives / "br_completion.img",
            archives / "br_terrain.img",
            archives / "br_terrain_models.img",
        ]
    )
    entries = []
    for name in sorted([n + ".dff" for n in names] + [n + ".txd" for n in required]):
        if name not in index:
            raise ValueError(f"missing native asset {name}")
        raw = geometry.read_entry(index, name)
        kind, size = struct.unpack_from("<II", raw)
        if kind != (0x10 if name.endswith(".dff") else 0x16) or size + 12 > len(raw):
            raise ValueError(f"invalid RenderWare file {name}")
        entries.append((name, raw[: size + 12]))
    colliders = collider_records(archives, geometry)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        root = Path(temp) / "quarter"
        root.mkdir()
        bundle = root / "brquarter.img"
        img(bundle, entries)
        restored = geometry.index_files([bundle])
        if len(restored) != len(entries) or any(
            geometry.read_entry(restored, k)[: len(v)] != v for k, v in entries
        ):
            raise ValueError("packed archive roundtrip failed")
        (root / "brquarter.col").write_bytes(
            b"".join(colliders[n] for n in sorted(names) if n in colliders)
        )
        block_text = [
            section + "\n" + "\n".join(lines) + "\nend" for section, lines in blocks.items()
        ]
        relations = [f"{name} {parents[name]}" for name in sorted(required) if name in parents]
        if relations:
            block_text.append("txdp\n" + "\n".join(relations) + "\nend")
        (root / "brquarter.ide").write_text("\n".join(block_text) + "\n", encoding="ascii")
        (root / "brquarter.ipl").write_text(
            "inst\n"
            + "\n".join(
                f"{models[p.name]}, {p.name}, {p.area}, "
                + ", ".join(format(v, ".15g") for v in (*p.position, *p.quat))
                + f", {lod_index}"
                for p, lod_index in zip(places, lod_indices, strict=True)
            )
            + "\nend\n",
            encoding="ascii",
        )
        check, _ = geometry.read_scene(root / "brquarter.ipl")
        if len(check) != len(places) or any(
            a.name != b.name
            or a.lod != lod_index
            or math.dist(a.position, b.position) > 1e-8
            or math.dist(a.quat, b.quat) > 1e-10
            for a, b, lod_index in zip(check, places, lod_indices, strict=True)
        ):
            raise ValueError("geometry transform roundtrip failed")
        report = dict(
            revision=revision,
            bounds=bounds,
            instances=len(places),
            models=len(models),
            textures=len(required),
            colliders=len(names & colliders.keys()),
            noSourceCollision=sorted(names - colliders.keys()),
            nearInstances=near_count,
            lodInstances=len(places) - near_count,
            verifiedLODLinks=sum(i >= 0 for i in lod_indices),
            missingLODLinks=0,
            vehicleModel=462,
            start=city["start"],
            vehicle=city["vehicle"],
            end=city["end"],
            nativeGameTested=False,
            hashes={},
        )
        for asset in sorted(root.iterdir()):
            with asset.open("rb") as f:
                report["hashes"][asset.name] = hashlib.file_digest(f, "sha256").hexdigest()
        (root / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf8")
        root.rename(destination)
    print({k: report[k] for k in ("instances", "models", "textures", "colliders")})


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "folder", "adapter", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    package(args.source, args.folder, args.adapter, args.output)
