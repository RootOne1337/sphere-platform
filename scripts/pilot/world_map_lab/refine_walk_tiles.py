"""Replace tiles at point contacts using an independently baked, finer copy of the same scene."""

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from scripts.pilot.world_map_lab.world_navmesh import Network, checksum


def contact_tiles(faces, bounds, width):
    sizes = np.bincount(faces["group"])
    part = faces[sizes[faces["group"]] >= 8]
    valid = np.arange(6) < part["vertices"][:, None]
    xyz = np.rint(part["xyz"][valid] * 8).astype(np.int32)
    groups = np.repeat(part["group"], part["vertices"].astype(np.intp))
    if np.max(abs(xyz)) >= 524288:
        raise ValueError("vertex outside contact index")
    code = xyz[:, 0].astype(np.int64) + 524288
    for k in (1, 2):
        code = (code << 20) + (xyz[:, k].astype(np.int64) + 524288)
    order = np.argsort(code, kind="stable")
    same = (np.diff(code[order]) == 0) & (groups[order[1:]] != groups[order[:-1]])
    pts = np.unique(xyz[order[1:][same], :2], axis=0) / 8
    tiles = set()
    for dx in (-1.0, 1.0):
        for dy in (-1.0, 1.0):
            xx = np.floor((pts[:, 0] + dx - bounds[0]) / width).astype(int)
            yy = np.floor((bounds[3] - pts[:, 1] - dy) / width).astype(int)
            tiles.update(zip(xx.tolist(), yy.tolist(), strict=True))
    return tiles


def bake(base, fine, out):
    import struct

    a = base / "walk.nav.zip"
    b = fine / "walk.nav.zip"
    target = out / "walk.nav.zip"
    if target.resolve() in (a.resolve(), b.resolve()):
        raise ValueError("preserve both independent source bakes")
    with ZipFile(a) as coarse, ZipFile(b) as detail:
        m = json.loads(coarse.read("manifest.json"))
        fm = json.loads(detail.read("manifest.json"))
        for k in (
            "geometrySha256",
            "bounds",
            "tileWidth",
            "heightStep",
            "maxClimb",
            "radius",
            "height",
            "mode",
            "placementRevision",
            "format",
        ):
            if m[k] != fm[k]:
                raise ValueError(f"incompatible meshes: {k}")
        if m["cell"] != 0.25 or fm["cell"] != 0.125:
            raise ValueError("unexpected cell size")
        with np.load(base / "walk-faces.npz", allow_pickle=False) as z:
            if str(z["geometry"]) != m["geometrySha256"]:
                raise ValueError("different source")
            tiles = contact_tiles(z["faces"], m["bounds"], m["tileWidth"])
        total = 0
        count = 0
        temp = target.with_suffix(".tmp")
        with ZipFile(temp, "w", compression=ZIP_DEFLATED, compresslevel=2) as dst:
            for name in sorted(set(coarse.namelist()) | set(detail.namelist())):
                if not name.startswith("tiles/"):
                    continue
                x, y, _ = map(int, Path(name).stem.split("_"))
                archive = detail if (x, y) in tiles else coarse
                if name not in archive.NameToInfo:
                    continue
                blob = archive.read(name)
                # dtMeshHeader: magic,version,x,y,layer,userId,polyCount.
                magic, _, tx, ty, _, _, n = struct.unpack_from("<7i", blob)
                if magic != 0x444E4156 or (tx, ty) != (x, y) or n <= 0:
                    raise ValueError("invalid Detour header")
                total += n
                count += 1
                dst.writestr(name, blob)
            m.update(refinedTiles=sorted(tiles), fineCell=0.125, polygons=total, tiles=count)
            dst.writestr("manifest.json", json.dumps(m))
        temp.replace(target)
    with Network(out, "walk") as nav:
        fs = nav.faces()
        np.savez_compressed(
            out / "walk-faces.npz", faces=fs, geometry=m["geometrySha256"], mesh=checksum(target)
        )
    print("refined", len(tiles), "tiles;", total, "polygons", flush=True)


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    for k in ("base", "fine", "out"):
        a.add_argument("--" + k, type=Path, required=True)
    q = a.parse_args()
    bake(q.base, q.fine, q.out)
