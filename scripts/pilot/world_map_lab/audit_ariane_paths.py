"""Compare Ariane's archived path nodes with the known SA graph and source geometry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from struct import Struct

import numpy as np

# Hash of the inspected GTA San Andreas browser lab reference at /game/world/roads.bin.
ROAD_GRAPH_SHA256 = "3e5bee197f05a4c2335889c1d065c9a5a9123b0b95d9224174da29471cdf7839"
REFERENCE_HEADER = Struct("<4s4I")
IMG_HEADER = Struct("<4sI")
IMG_ENTRY = Struct("<IHH24s")
PATH_HEADER = Struct("<5I")
PATH_NODE = Struct("<8x3h2xh2HBxI")
SECTOR_BYTES = 2048
MAP_AREAS = 64
MAX_DIRECTORY_ENTRIES = 200_000
MAX_PATH_BYTES = 8 * 1024**2
PATH_NAME = re.compile(rb"nodes(0|[1-9][0-9]*)\.dat", re.IGNORECASE)


def read_areas(archive: Path):
    """Read only the exterior path entries from the supplied VER2 IMG."""
    size = archive.stat().st_size
    with archive.open("rb") as stream:
        raw_header = stream.read(IMG_HEADER.size)
        if len(raw_header) != IMG_HEADER.size:
            raise ValueError("short IMG header")
        magic, count = IMG_HEADER.unpack(raw_header)
        directory_bytes = count * IMG_ENTRY.size
        if (
            magic != b"VER2"
            or count > MAX_DIRECTORY_ENTRIES
            or directory_bytes > size - IMG_HEADER.size
        ):
            raise ValueError("invalid VER2 directory")
        directory = stream.read(directory_bytes)
        if len(directory) != directory_bytes:
            raise ValueError("short IMG directory")
        data_start = IMG_HEADER.size + directory_bytes
        areas = {}
        for sector, streaming_size, archive_size, raw_name in IMG_ENTRY.iter_unpack(directory):
            match = PATH_NAME.fullmatch(raw_name.split(b"\0", 1)[0])
            if match is None:
                continue
            area = int(match[1])
            if not 0 <= area < MAP_AREAS or area in areas:
                raise ValueError("unexpected or duplicate path area")
            offset = sector * SECTOR_BYTES
            length = (archive_size or streaming_size) * SECTOR_BYTES
            if offset < data_start or not 0 < length <= MAX_PATH_BYTES or offset + length > size:
                raise ValueError(f"path extent outside IMG: {area}")
            areas[area] = (offset, length)
        if len(areas) != MAP_AREAS:
            raise ValueError("missing exterior path areas")
        previous_end = data_start
        for offset, length in sorted(areas.values()):
            if offset < previous_end:
                raise ValueError("overlapping path entries")
            previous_end = offset + length
        for area, (offset, length) in sorted(areas.items()):
            stream.seek(offset)
            raw = stream.read(length)
            if len(raw) != length:
                raise ValueError(f"short path read: {area}")
            yield area, raw


def read_positions(area, raw):
    """Decode fixed-point positions and classify them by the original node ranges."""
    if len(raw) < PATH_HEADER.size:
        raise ValueError(f"short path header: {area}")
    total, vehicles, pedestrians, car_links, addresses = PATH_HEADER.unpack_from(raw)
    end = PATH_HEADER.size + total * PATH_NODE.size
    directory_end = end + car_links * 14 + addresses * 4
    if total != vehicles + pedestrians or directory_end > len(raw):
        raise ValueError(f"invalid path area layout: {area}")
    result = {"drive": [], "walk": [], "water": []}
    for index in range(total):
        x, y, z, base, node_area, node_index, _, flags = PATH_NODE.unpack_from(
            raw, PATH_HEADER.size + index * PATH_NODE.size
        )
        if (node_area, node_index) != (area, index):
            raise ValueError(f"path node identity mismatch: {area}:{index}")
        links = flags & 0x0F
        if links and not 0 <= base <= addresses - links:
            raise ValueError(f"path node link range invalid: {area}:{index}")
        mode = "water" if flags & 0x80 else "drive" if index < vehicles else "walk"
        result[mode].append((x, y, z))
    return result


def compare_tile(points, tile, road, height, tolerance=1.5):
    """Count coverage using both XY and the local source collision Z."""
    width, rows = tile["width"], tile["height"]
    left, top, step = tile["left"], tile["top"], tile["step"]
    summary = Counter(in_xy_bounds=0, on_road_xy=0, on_road_xyz=0)
    for px, py, pz in points:
        x, y, z = px / 8.0, py / 8.0, pz / 8.0
        col, row = math.floor((x - left) / step), math.floor((top - y) / step)
        if not (0 <= col < width and 0 <= row < rows):
            continue
        summary["in_xy_bounds"] += 1
        if road[row, col]:
            summary["on_road_xy"] += 1
            if np.isfinite(height[row, col]) and abs(z - height[row, col]) <= tolerance:
                summary["on_road_xyz"] += 1
    return dict(summary)


def read_reference_positions(path):
    if not 32 <= path.stat().st_size <= MAX_PATH_BYTES:
        raise ValueError("unexpected comparison graph size")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ROAD_GRAPH_SHA256:
        raise ValueError("comparison graph differs from the inspected GTA SA reference")
    magic, version, count, _, _ = REFERENCE_HEADER.unpack_from(raw)
    if magic != b"SDRD" or version != 1 or 32 + count * 6 > len(raw):
        raise ValueError("invalid comparison graph")
    return {
        tuple(point)
        for point in np.frombuffer(raw, dtype="<i2", count=count * 3, offset=32)
        .reshape(-1, 3)
        .tolist()
    }


def audit(archive, reference, geometry, grid_manifest):
    reference_vehicle = read_reference_positions(reference)
    source_positions = {"drive": [], "walk": [], "water": []}
    area_digests = {}
    for area, raw in read_areas(archive):
        area_digests[str(area)] = hashlib.sha256(raw).hexdigest()
        for mode, points in read_positions(area, raw).items():
            source_positions[mode].extend(points)

    source_vehicle = set(source_positions["drive"])
    exact = len(reference_vehicle & source_vehicle)
    tile = json.loads(grid_manifest.read_text(encoding="utf-8"))["grid"]
    with np.load(geometry, allow_pickle=False) as surface:
        road = surface["support"]
        height = surface["height"]
    if road.shape != (tile["height"], tile["width"]) or road.shape != height.shape:
        raise ValueError("source collision grid shape mismatch")

    return {
        "kind": "ariane_native_path_audit_v1",
        "path_areas": len(area_digests),
        "nodes": {mode: len(points) for mode, points in source_positions.items()},
        "gta_sa_reference_graph": {
            "sha256": ROAD_GRAPH_SHA256,
            "unique_xyz": len(reference_vehicle),
            "unique_archive_drive_xyz": len(source_vehicle),
            "exact_xyz_matches_in_archive": exact,
            "match_fraction": exact / len(reference_vehicle),
        },
        "ari_road_tile": {
            "grid": tile,
            "source_collision_sha256": hashlib.sha256(geometry.read_bytes()).hexdigest(),
            "z_tolerance_world_units": 1.5,
            "nodes": {
                mode: compare_tile(points, tile, road, height)
                for mode, points in source_positions.items()
            },
        },
        "area_sha256": area_digests,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sa-reference", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--grid-manifest", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    data = audit(args.archive, args.sa_reference, args.geometry, args.grid_manifest)
    args.report.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in data.items() if key != "area_sha256"}, indent=2))


if __name__ == "__main__":
    main()
