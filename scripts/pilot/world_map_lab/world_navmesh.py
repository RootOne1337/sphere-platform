"""Build and query tiled, layered exterior navmeshes from the source geometry."""

from __future__ import annotations

import argparse
import ctypes as ct
import hashlib
import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from scripts.pilot.world_map_lab.collect_ariane_nav_geometry import HEADER

TILE = 128
BORDER = 3.0
FLOATS = ct.POINTER(ct.c_float)
FACE = np.dtype([("xyz", "<f4", (6, 3)), ("vertices", "<u4"), ("group", "<u4")])
CODES = {
    0: "endpoint_unavailable",
    1: "complete",
    2: "disconnected",
    3: "search_limit",
    4: "surface_unconfirmed",
}


class Chunk(ct.Structure):
    _fields_ = [("xyz", ct.c_void_p), ("count", ct.c_uint32), ("kind", ct.c_uint32)]


def library(path):
    dll = ct.CDLL(str(path.resolve(strict=True)))
    void, integer, real = ct.c_void_p, ct.c_int, ct.c_float
    signatures = {
        "build_tile": (
            integer,
            [
                ct.POINTER(Chunk),
                integer,
                real,
                real,
                integer,
                integer,
                real,
                real,
                integer,
                integer,
                ct.POINTER(void),
                ct.POINTER(integer),
            ],
        ),
        "free_tile": (None, [void]),
        "create_nav": (void, [real, real, integer]),
        "free_nav": (None, [void]),
        "add_tile": (integer, [void, void, integer]),
        "collect_faces": (integer, [void, void, integer]),
        "query_levels": (integer, [void, real, real, FLOATS, integer]),
        "query_path": (integer, [void, FLOATS, FLOATS, FLOATS, integer, ct.POINTER(integer)]),
    }
    if hasattr(dll, "move_body"):
        signatures["move_body"] = (integer, [void, FLOATS, FLOATS, FLOATS])
    if hasattr(dll, "walk_material_version"):
        signatures["walk_material_version"] = (integer, [])
    if hasattr(dll, "bake_cell_size"):
        signatures["bake_cell_size"] = (real, [integer])
    if hasattr(dll, "collect_labels"):
        signatures["collect_labels"] = (integer, [void, void, integer])
        signatures["endpoint_index"] = (integer, [void, FLOATS])
    if hasattr(dll, "index_clusters"):
        signatures["index_clusters"] = (void, [void])
        signatures["free_clusters"] = (None, [void])
        signatures["query_cluster_path"] = (
            integer,
            [void, void, FLOATS, FLOATS, FLOATS, integer, ct.POINTER(integer)],
        )
    for name, (result, args) in signatures.items():
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = args, result
    return dll


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def spatial_index(data, bounds):
    west, east, south, north = bounds
    nx, ny = math.ceil((east - west) / TILE), math.ceil((north - south) / TILE)
    if bytes(data[:8]) != b"BRGEO1\0\0":
        raise ValueError("geometry format mismatch")
    index = defaultdict(list)
    chunks = []
    cursor = 8
    while cursor < data.size:
        kind, count, x0, y0, x1, y1 = HEADER.unpack_from(data, cursor)
        cursor += HEADER.size
        if kind > 5 or not count or cursor + count * 36 > data.size:
            raise ValueError("invalid geometry batch")
        xyz = np.ndarray((count, 3, 3), "<f4", data, cursor)
        # Water.dat contains distant surfaces at distinct elevations in one batch.
        # Bin each water triangle to its actual XY bounds and vertical layer.
        sections = range(count) if kind == 2 else (None,)
        for sub in sections:
            points = xyz if sub is None else xyz[sub : sub + 1]
            pos = cursor if sub is None else cursor + sub * 36
            if sub is not None:
                x0, y0 = points[:, :, :2].min(axis=(0, 1))
                x1, y1 = points[:, :, :2].max(axis=(0, 1))
            idx = len(chunks)
            chunks.append(
                (pos, len(points), kind, float(points[:, :, 2].min()), float(points[:, :, 2].max()))
            )
            xs = range(
                max(0, math.floor((x0 - west - BORDER) / TILE)),
                min(nx, 1 + math.floor((x1 - west + BORDER) / TILE)),
            )
            ys = range(
                max(0, math.floor((north - y1 - BORDER) / TILE)),
                min(ny, 1 + math.floor((north - y0 + BORDER) / TILE)),
            )
            for ty in ys:
                for tx in xs:
                    index[(tx, ty)].append(idx)
        cursor += count * 36
    return index, chunks


def build(args):
    folder = args.folder
    geo = json.loads((folder / "geometry.json").read_bytes())
    source = folder / "world-geometry.bin"
    if checksum(source) != geo["geometrySha256"]:
        raise ValueError("source geometry hash mismatch")
    roads = json.loads(args.road_report.read_bytes())
    if roads["placementRevision"] != geo["placementRevision"] or roads.get("area"):
        raise ValueError("whole-world manifest does not match source geometry")
    box = roads["bounds"]
    bounds = [box[k] for k in ("left", "right", "bottom", "top")]
    data = np.memmap(source, dtype="u1", mode="r")
    index, chunks = spatial_index(data, bounds)
    dll = library(folder / "ariane-nav.dll")
    refined = set()
    refinements = getattr(args, "preserve_walk_refinements", None)
    if refinements:
        with ZipFile(refinements) as earlier:
            previous = json.loads(earlier.read("manifest.json"))
        if (
            previous["mode"] != "walk"
            or previous["geometrySha256"] != geo["geometrySha256"]
            or previous["bounds"] != bounds
            or previous["tileWidth"] != TILE
            or previous.get("fineCell") != 0.125
            or args.walk_cell != 0.25
        ):
            raise ValueError("walk refinement grid differs from the source")
        refined = {tuple(x) for x in previous["refinedTiles"]}
    if "walk" in args.modes and (
        not hasattr(dll, "walk_material_version") or dll.walk_material_version() != 1
    ):
        raise ValueError("rebuild the native adapter for pedestrian surface costs")
    for mode in args.modes:
        fine = mode == "walk" and getattr(args, "walk_cell", 0.25) == 0.125
        if not hasattr(dll, "bake_cell_size") or dll.bake_cell_size(
            2 if fine else int(mode == "drive")
        ) != (0.125 if fine else 0.25):
            raise ValueError("rebuild the native adapter for this voxel profile")
        jobs = []
        for (tx, ty), ids in sorted(index.items()):
            selected = [
                chunks[i]
                for i in ids
                if chunks[i][2] in ((0, 1, 2, 3) if mode == "drive" else (0, 1, 2, 3, 4, 5))
            ]
            bands = []
            for _, _, _, low, high in sorted(
                (s for s in selected if s[2] in (0, 1)), key=lambda s: s[3]
            ):
                if not bands or low > bands[-1][1] + 100:
                    bands.append([low, high])
                else:
                    bands[-1][1] = max(bands[-1][1], high)
            for layer, (low, high) in enumerate(bands):
                batch = [
                    s
                    for s in selected
                    if s[4] >= low - 1 and s[3] <= high + (100 if s[2] == 2 else 1)
                ]
                jobs.append(((tx, ty, layer), batch))

        def tile(job):
            key, selected = job
            tx, ty, layer = key
            kinds = {s[2] for s in selected}
            if 0 not in kinds or (mode == "drive" and 3 not in kinds):
                return key, 0, None
            lo = math.floor(min(s[3] for s in selected) * 8) / 8 - 1
            hi = math.ceil(max(s[4] for s in selected) * 8) / 8 + 2
            array = (Chunk * len(selected))(
                *(Chunk(data.ctypes.data + off, count, kind) for off, count, kind, _, _ in selected)
            )
            pointer = ct.c_void_p()
            size = ct.c_int()
            polys = dll.build_tile(
                array,
                len(array),
                bounds[0],
                bounds[3],
                tx,
                ty,
                lo,
                hi,
                layer,
                2 if fine or (mode == "walk" and (tx, ty) in refined) else int(mode == "drive"),
                ct.byref(pointer),
                ct.byref(size),
            )
            if polys < 0:
                raise RuntimeError(
                    f"{mode} tile {key} failed at native stage {polys}, height {lo}..{hi}"
                )
            try:
                return key, polys, ct.string_at(pointer, size.value) if polys else None
            finally:
                dll.free_tile(pointer)

        dest = folder / f"{mode}.nav.zip"
        temp = dest.with_suffix(".tmp")
        tiles = 0
        polygons = 0
        with (
            ZipFile(temp, "w", compression=ZIP_DEFLATED, compresslevel=2) as archive,
            ThreadPoolExecutor(args.workers) as pool,
        ):
            for number, ((tx, ty, layer), polys, blob) in enumerate(pool.map(tile, jobs)):
                if blob:
                    archive.writestr(f"tiles/{tx}_{ty}_{layer}.bin", blob)
                    tiles += 1
                    polygons += polys
                if number and number % 400 == 0:
                    print(
                        mode,
                        number,
                        "/",
                        len(index),
                        "tiles scanned",
                        polygons,
                        "polygons",
                        flush=True,
                    )
            meta = {
                "format": "sphere.exterior-navmesh.v1",
                "mode": mode,
                "bounds": bounds,
                "tileWidth": TILE,
                "cell": 0.125 if fine else 0.25,
                "heightStep": 0.125,
                "radius": 1.5 if mode == "drive" else 0.5,
                "height": 2.0 if mode == "drive" else 1.875,
                "maxClimb": 0.25 if mode == "drive" else 0.375,
                "geometrySha256": geo["geometrySha256"],
                "placementRevision": geo["placementRevision"],
                "tiles": tiles,
                "polygons": polygons,
            }
            if mode == "walk":
                meta["walkMaterialVersion"] = 1
                if refined:
                    meta.update(fineCell=0.125, refinedTiles=sorted(refined))
            archive.writestr("manifest.json", json.dumps(meta))
        temp.replace(dest)
        with Network(folder, mode) as network:
            f = network.faces()
            assert len(f) == polygons
            np.savez_compressed(
                folder / f"{mode}-faces.npz",
                faces=f,
                geometry=geo["geometrySha256"],
                mesh=checksum(dest),
            )
        print(meta, flush=True)
    if set(args.modes) == {"walk", "drive"}:
        from scripts.pilot.world_map_lab.build_taxi_transfers import build as build_transfers

        build_transfers(folder, folder / "ariane-nav.dll")


class Network:
    def __init__(self, folder, mode, *, adapter=None):
        if mode not in ("drive", "walk"):
            raise ValueError("unknown transport mode")
        self.dll = library(adapter or folder / "ariane-nav.dll")
        self.labels = None
        self.graph = None
        self.handle = None
        with ZipFile(folder / f"{mode}.nav.zip") as archive:
            self.meta = json.loads(archive.read("manifest.json"))
            if self.meta["format"] != "sphere.exterior-navmesh.v1" or self.meta["mode"] != mode:
                raise ValueError("unexpected mesh manifest")
            if self.meta.get("walkMaterialVersion") and (
                not hasattr(self.dll, "walk_material_version")
                or self.dll.walk_material_version() != self.meta["walkMaterialVersion"]
            ):
                raise ValueError("native adapter does not implement this pedestrian surface policy")
            b = self.meta["bounds"]
            self.handle = self.dll.create_nav(b[0], b[3], max(1, self.meta["tiles"]))
            if not self.handle:
                raise MemoryError("cannot initialize Detour world")
            try:
                for name in archive.namelist():
                    if name.startswith("tiles/"):
                        blob = archive.read(name)
                        if not self.dll.add_tile(self.handle, blob, len(blob)):
                            raise ValueError("invalid navigation tile " + name)
                if hasattr(self.dll, "collect_labels"):
                    self.labels = np.empty(self.meta["polygons"], dtype=np.uint32)
                    if self.dll.collect_labels(
                        self.handle, self.labels.ctypes.data, len(self.labels)
                    ) != len(self.labels):
                        raise ValueError("unexpected component index size")
                if hasattr(self.dll, "index_clusters"):
                    self.graph = self.dll.index_clusters(self.handle)
                    if not self.graph:
                        raise MemoryError("could not index tile portals")
            except BaseException:
                self.close()
                raise

    def close(self):
        if self.graph:
            self.dll.free_clusters(self.graph)
            self.graph = None
        if self.handle:
            self.dll.free_nav(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def faces(self):
        count = self.dll.collect_faces(self.handle, None, 0)
        f = np.zeros(count, FACE)
        if self.dll.collect_faces(self.handle, f.ctypes.data, count) != count:
            raise ValueError("polygon count changed")
        return f

    def levels(self, x, y):
        if not np.isfinite([x, y]).all():
            raise ValueError("invalid map coordinates")
        out = np.empty(64, np.float32)
        count = self.dll.query_levels(self.handle, x, y, out.ctypes.data_as(FLOATS), len(out))
        if count < 0:
            raise RuntimeError("level lookup failed")
        return out[:count].tolist()

    def component(self, point):
        if self.labels is None:
            raise ValueError("component lookup requires an indexed adapter")
        xyz = np.ascontiguousarray(point, dtype=np.float32)
        if xyz.shape != (3,) or not np.isfinite(xyz).all():
            raise ValueError("expected finite XYZ")
        i = self.dll.endpoint_index(self.handle, xyz.ctypes.data_as(FLOATS))
        if i == -1:
            return None
        if not 0 <= i < len(self.labels):
            raise RuntimeError("endpoint lookup failed")
        return int(self.labels[i])

    def route(self, start, end):
        ends = [np.ascontiguousarray(p, dtype=np.float32) for p in (start, end)]
        if any(p.shape != (3,) or not np.isfinite(p).all() for p in ends):
            raise ValueError("expected finite XYZ for both endpoints")
        if self.labels is not None:
            a, b = map(self.component, ends)
            if a is None or b is None or a != b:
                return {
                    "status": "endpoint_unavailable" if a is None or b is None else "disconnected",
                    "length": 0.0,
                    "path": [],
                }
        out = np.empty((16384, 3), np.float32)
        count = ct.c_int()
        fn = self.dll.query_cluster_path if self.graph else self.dll.query_path
        handles = (self.handle, self.graph) if self.graph else (self.handle,)
        status = fn(
            *handles,
            *(p.ctypes.data_as(FLOATS) for p in ends),
            out.ctypes.data_as(FLOATS),
            len(out),
            ct.byref(count),
        )
        if status not in CODES:
            raise RuntimeError(f"Detour query failed at stage {status}")
        path = out[: count.value] if status == 1 else out[:0]
        return {
            "status": CODES[status],
            "length": float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum()),
            "path": path.tolist(),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    b = sub.add_parser("build")
    b.add_argument("--folder", required=True, type=Path)
    b.add_argument("--road-report", required=True, type=Path)
    b.add_argument("--workers", type=int, default=2, choices=range(1, 9))
    b.add_argument("--modes", nargs="+", choices=["drive", "walk"], default=["drive", "walk"])
    b.add_argument(
        "--preserve-walk-refinements",
        type=Path,
        help="reuse the fine tile grid from a matching walk archive",
    )
    b.add_argument("--walk-cell", type=float, choices=(0.125, 0.25), default=0.25)
    q = sub.add_parser("route")
    q.add_argument("--folder", required=True, type=Path)
    q.add_argument("--mode", required=True, choices=["drive", "walk"])
    q.add_argument("--start", nargs=3, type=float, required=True)
    q.add_argument("--end", nargs=3, type=float, required=True)
    args = parser.parse_args()
    if args.action == "build":
        build(args)
    else:
        with Network(args.folder, args.mode) as nav:
            print(json.dumps(nav.route(args.start, args.end)))


if __name__ == "__main__":
    main()
