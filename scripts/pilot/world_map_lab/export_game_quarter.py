"""Package a local quarter in GTA's native IMG, IPL, IDE and COL formats for gameplay testing."""

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import struct
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.collect_ariane_nav_geometry import collider_records
from scripts.pilot.world_map_lab.native_route import native_route
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter
from scripts.pilot.world_map_lab.render_ariane_world import texture_parents


def img(path, names, index, geometry):
    # Reserve the directory, then stream one original RenderWare chunk at a time.
    # Several texture archives together can exceed the available Windows commit.
    table = bytearray(struct.pack("<4sI", b"VER2", len(names)))
    digests = {}
    with path.open("w+b") as f:
        f.seek(2048 * math.ceil((8 + 32 * len(names)) / 2048))
        for name in names:
            if name not in index:
                raise ValueError(f"missing native asset {name}")
            raw = memoryview(geometry.read_entry(index, name))
            kind, size = struct.unpack_from("<II", raw)
            if kind != (0x10 if name.endswith(".dff") else 0x16) or size + 12 > len(raw):
                raise ValueError(f"invalid RenderWare file {name}")
            blob = raw[: size + 12]
            sectors = math.ceil(len(blob) / 2048)
            if len(name.encode("ascii")) > 23 or not 0 < sectors < 65536:
                raise ValueError(f"unsupported GTA IMG entry {name}")
            table.extend(struct.pack("<IHH24s", f.tell() // 2048, sectors, 0, name.encode("ascii")))
            digests[name] = (len(blob), hashlib.sha256(blob).digest())
            f.write(blob)
            f.write(bytes(-len(blob) % 2048))
        f.seek(0)
        f.write(table)
    restored = geometry.index_files([path])
    if set(restored) != set(names):
        raise ValueError("unexpected packed archive directory")
    for name, (size, digest) in digests.items():
        blob = memoryview(geometry.read_entry(restored, name))
        if hashlib.sha256(blob[:size]).digest() != digest:
            raise ValueError(f"packed archive roundtrip failed for {name}")


def scene_windows(paths, padding=175):
    # Limit each spatial query to its part of the route, including sparse long segments.
    windows = set()
    for path in paths:
        for a, b in zip(path, path[1:]):
            pieces = max(1, math.ceil(math.dist(a[:2], b[:2]) / 64))
            for j in range(pieces + 1):
                cell = tuple(
                    math.floor((u + (v - u) * j / pieces) / 64) for u, v in zip(a[:2], b[:2])
                )
                windows.add(cell)
    return [
        (x * 64 - padding, (x + 1) * 64 + padding, y * 64 - padding, (y + 1) * 64 + padding)
        for x, y in sorted(windows)
    ]


def collect_placements(geometry, points):
    places, lods = [], []
    near_count = 0
    origins = {key[:4] for key in points}
    # Resolve ordinals before merging. Several unrelated source IPLs are named other.ipl.
    for path in geometry.active_paths():
        scene, targets = geometry.read_scene(path)
        selected = []
        for item in scene:
            origin = (item.name, *item.position)
            if item.area != 0 or item.ordinal in targets or origin not in origins:
                continue
            rotation = geometry.ariane_rotation(item.quat).as_quat()
            key = (*origin, *rotation)
            if points[key]:
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


def package(source, folder, adapter, destination, route=None):
    if destination.exists():
        raise FileExistsError(destination)
    geometry = load_local_adapter(source, adapter)
    route_hash = None
    if route is None:
        city = json.loads((folder / "journey/city-trip.json").read_bytes())
        x, y, _ = city["vehicle"]
        windows = [[x - 175, x + 175, y - 175, y + 175]]
    else:
        paths, city, route_hash = native_route(route)
        windows = scene_windows(paths)
    bounds = [fn(w[i] for w in windows) for i, fn in enumerate((min, max, min, max))]
    with closing(
        sqlite3.connect(
            (folder / "detail-scene.sqlite").resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
    ) as conn:
        rows = {}
        for window in windows:
            for ident, *instance in conn.execute(
                "select i.id,m.name,i.x,i.y,i.z,i.qx,i.qy,i.qz,i.qw from spatial s join instance i on i.id=s.id "
                "join model m on m.id=i.model where s.maxx>=? and s.minx<=? and s.maxy>=? and s.miny<=?",
                window,
            ):
                rows[ident] = tuple(instance)
        revision = json.loads(conn.execute("select value from meta").fetchone()[0])["revision"]
    places, lod_indices, near_count = collect_placements(geometry, Counter(rows.values()))
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
    names_to_pack = sorted([n + ".dff" for n in names] + [n + ".txd" for n in required])
    colliders = collider_records(archives, geometry)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        root = Path(temp) / "quarter"
        root.mkdir()
        bundle = root / "brquarter.img"
        img(bundle, names_to_pack, index, geometry)
        for filename in ("water.dat", "timecyc.dat"):
            shutil.copyfile(source / "data" / filename, root / filename)
        if route:
            shutil.copyfile(route, root / "route.json")
            if hashlib.sha256((root / "route.json").read_bytes()).hexdigest() != route_hash:
                raise ValueError("native itinerary changed during export")
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
            routeSha256=route_hash,
            selectionWindows=len(windows),
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
    cli.add_argument(
        "--route", type=Path, help="full walk, drive and walk itinerary in world coordinates"
    )
    args = cli.parse_args()
    package(args.source, args.folder, args.adapter, args.output, args.route)
