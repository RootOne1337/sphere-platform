"""Stream exterior collisions, water and visual road evidence as native Recast build inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.ariane_geometry import model_types
from scripts.pilot.world_map_lab.audit_ariane_surface_coverage import COL_HEADER
from scripts.pilot.world_map_lab.index_ariane_world import inventory
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter, surface_triangles
from scripts.pilot.world_map_lab.render_ariane_world import water_triangles

# The native builder reads XYZ in the original map frame.
HEADER = struct.Struct("<II4f")
COLLISION, OBSTACLE, WATER, DRIVE, PAVING, FOOT = range(6)
KINDS = {"selected_road": DRIVE, "additional_pavement": PAVING, "pedestrian_candidates": FOOT}


# Separately reviewed TXD swatches: marked lanes, paved carriageways and bridge decks.
# Mixed grass atlases, yards, parking areas and kerb blends stay out of this promotion.
REVIEWED_DRIVE = re.compile(
    r"(?:asfcrbtraskc[15](?:1suj|suj)?|perroad_01(?:_new)?|perroad_77|gso_perroad1|"
    r"wolv_roads(?:_per)?|road_2_2|roadasf[1-3]|ruscount_road1|lf_arzasf(?:1|2|6|7|11))"
)


def put(stream, kind, triangles, counts):
    if not len(triangles):
        return
    xyz = np.ascontiguousarray(triangles, dtype="<f4").reshape(-1, 3, 3)
    if not np.isfinite(xyz).all():
        raise ValueError("non-finite source triangle")
    points = xyz.reshape(-1, 3)
    stream.write(
        HEADER.pack(kind, len(xyz), *points[:, :2].min(axis=0), *points[:, :2].max(axis=0))
    )
    stream.write(memoryview(xyz).cast("B"))
    counts[kind] += len(xyz)


def collider_records(folder, geometry):
    records = {}
    for path, offset, length in geometry.index_files(
        sorted(folder.glob("br_collision_*.img"))
    ).values():
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(length)
        i = 0
        while data[i : i + 4] in (b"COLL", b"COL2", b"COL3", b"COL4"):
            _, size, name, _ = COL_HEADER.unpack_from(data, i)
            stop = i + 8 + size
            if stop < i + COL_HEADER.size or stop > len(data):
                raise ValueError("truncated source collider")
            records[name.partition(b"\0")[0].decode("ascii").lower()] = data[i:stop]
            i = stop
    return records


def volume_triangles(bounds):
    # Enclose boxes and sphere AABBs conservatively. Volume tops are never road evidence.
    lo, hi = np.asarray(bounds)
    v = np.asarray(
        [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    )
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return v[[tri for a, b, c, d in faces for tri in ((a, b, c), (a, c, d))]]


def collect(args):
    source = args.source.resolve(strict=True)
    geometry = load_local_adapter(source, args.geometry_tools)
    from gtaLib import col

    revision = inventory(source, "black-russia-ariane")["placement_revision"]
    folder = source / "models/img"
    models = geometry.index_files(
        sorted(folder.glob("br_models_*.img")) + [folder / "br_terrain_models.img"]
    )
    records = collider_records(folder, geometry)
    types = model_types(source)
    by_name = defaultdict(list)
    for item in geometry.active_exterior():
        by_name[item.name].append(item)
    args.output.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    dest = args.output / "world-geometry.bin"
    tmp = dest.with_suffix(".tmp")
    materials = Counter()
    exterior_without_collision = 0
    with tmp.open("wb") as stream:
        stream.write(b"BRGEO1\0\0")
        put(stream, WATER, list(water_triangles(source)), counts)
        for number, (filename, _) in enumerate(
            sorted(models.items(), key=lambda entry: entry[1][:2])
        ):
            name = filename.removesuffix(".dff")
            places = by_name.get(name)
            if not places:
                continue
            groups = []
            if name in records:
                parser = col.coll()
                parser.load_memory(records[name])
                (collider,) = parser.models
                if collider.mesh_faces:
                    # COL faces for the driving surface have clockwise winding viewed from above.
                    idx = np.array([(f.a, f.c, f.b) for f in collider.mesh_faces])
                    groups.append((COLLISION, np.asarray(collider.mesh_verts)[idx]))
                vols = [volume_triangles((box.min, box.max)) for box in collider.boxes]
                for sphere in collider.spheres:
                    center = np.asarray(sphere.center)
                    vols.append(volume_triangles((center - sphere.radius, center + sphere.radius)))
                if vols:
                    groups.append((OBSTACLE, np.concatenate(vols)))
            else:
                exterior_without_collision += len(places)
            for layer, triangles, names in surface_triangles(
                geometry.read_entry(models, filename), types[name]
            ):
                if layer == "additional_pavement":
                    reviewed = np.fromiter(
                        (bool(REVIEWED_DRIVE.fullmatch(n)) for n in names), dtype=bool
                    )
                    groups.extend([(DRIVE, triangles[reviewed]), (PAVING, triangles[~reviewed])])
                else:
                    groups.append((KINDS[layer], triangles))
                for material, count in Counter(names).items():
                    materials[material] += count * len(places)
            for item in places:
                rotation = geometry.ariane_rotation(item.quat)
                for category, batch in groups:
                    xyz = rotation.apply(batch.reshape(-1, 3)) + item.position
                    put(stream, category, xyz.reshape(-1, 3, 3), counts)
            if number % 2000 == 0:
                print(f"{number} model entries, {sum(counts.values()):,} placed faces", flush=True)
    tmp.replace(dest)
    with dest.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {
        "placementRevision": revision,
        "placements": sum(map(len, by_name.values())),
        "models": len(by_name),
        "unresolvedCollisionPlacements": exterior_without_collision,
        "placedTriangles": dict(counts),
        "geometrySha256": checksum,
        "surfaceMaterials": materials,
    }
    (args.output / "geometry.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print({k: v for k, v in report.items() if k != "surfaceMaterials"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "geometry-tools", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    collect(parser.parse_args())
