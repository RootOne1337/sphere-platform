"""Search all textured world placements from RGB alone. Results are candidate areas."""

import argparse
import gzip
import hashlib
import io
import json
import math
import sqlite3
import struct
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np


def features(gray, limit):
    keys, desc = cv2.SIFT_create(nfeatures=limit, contrastThreshold=0.012).detectAndCompute(
        gray, None
    )
    if desc is None:
        return np.empty((0, 2), np.float32), np.empty((0, 128), np.uint8)
    root = np.sqrt(desc / np.maximum(1.0, desc.sum(axis=1, keepdims=True)))
    return np.float32([k.pt for k in keys]), np.rint(root * 255).astype(np.uint8)


def material_features(item):
    key, png = item
    gray = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("invalid texture " + key)
    h, w = gray.shape
    scale = min(1.0, 640 / max(w, h))
    if scale < 1.0:
        gray = cv2.resize(
            gray, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA
        )
    uv, desc = features(gray, 300)
    return key, uv / np.asarray(gray.shape[::-1], np.float32), desc


def build(scene, output):
    cv2.setNumThreads(1)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as workspace:
        tmp = Path(workspace) / "index"
        tmp.mkdir()
        with sqlite3.connect(scene.resolve().as_uri() + "?mode=ro", uri=True) as db:
            revision = json.loads(db.execute("select * from meta").fetchone()[0])["revision"]
            keys, offsets = [], [0]
            with (
                (tmp / "points.bin").open("wb") as points,
                (tmp / "descriptors.bin").open("wb") as descs,
                ThreadPoolExecutor(max_workers=4) as workers,
            ):
                textures = db.execute("select key,png from texture order by key")
                while batch := textures.fetchmany(48):
                    for key, uv, desc in workers.map(material_features, batch):
                        keys.append(key)
                        offsets.append(offsets[-1] + len(desc))
                        points.write(uv.astype("<f4").tobytes())
                        descs.write(desc.tobytes())
            key_ids = {key: i for i, key in enumerate(keys)}
            materials = {}
            for mid, blob in db.execute("select id,glb from model order by id"):
                with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
                    header = stream.read(20)
                    gltf = json.loads(stream.read(struct.unpack_from("<I", header, 12)[0]))
                used = set()
                for mesh in gltf["meshes"]:
                    for primitive in mesh["primitives"]:
                        mat = gltf["materials"][primitive["material"]].get(
                            "pbrMetallicRoughness", {}
                        )
                        if "baseColorTexture" in mat:
                            tex = gltf["textures"][mat["baseColorTexture"]["index"]]
                            used.add(key_ids[Path(gltf["images"][tex["source"]]["uri"]).stem])
                materials[mid] = sorted(used)
            places = np.array(
                db.execute(
                    "select i.model,(r.minx+r.maxx)/2,(r.miny+r.maxy)/2,max(r.maxx-r.minx,r.maxy-r.miny) "
                    "from instance i join spatial r on r.id=i.id order by i.id"
                ).fetchall(),
                dtype="<f4",
            )
        np.save(tmp / "placements.npy", places, allow_pickle=False)
        np.save(tmp / "offsets.npy", offsets, allow_pickle=False)
        meta = dict(
            revision=revision,
            textures=keys,
            modelMaterials=materials,
            features=offsets[-1],
            models=len(materials),
            placements=len(places),
        )
        if not offsets[-1]:
            raise ValueError("no visual features in map")
        desc = np.memmap(
            tmp / "descriptors.bin", dtype=np.uint8, mode="r", shape=(offsets[-1], 128)
        ).astype(np.float32)
        cv2.setRNGSeed(574)
        index = cv2.flann_Index(desc, dict(algorithm=1, trees=3))
        index.save(str(tmp / "world.flann"))
        (tmp / "manifest.json").write_text(json.dumps(meta), encoding="utf8")
        tmp.rename(output)
    return {k: meta[k] for k in ("revision", "features", "models", "placements")} | {
        "textures": len(keys)
    }


def verify_material(uv, desc, qxy, qindex):
    if len(desc) < 9:
        return None
    idx, ds = qindex.knnSearch(desc, 2, params={"checks": 64})
    good = ds[:, 0] < 0.83**2 * ds[:, 1]
    index = np.flatnonzero(good)
    if len(index) < 7:
        return None
    # Enforce one-to-one pixels on both images before RANSAC. SIFT can emit
    # multiple orientations at an identical window corner.
    src, dst, a, b = [], [], set(), set()
    for k in index[np.argsort(ds[index, 0])]:
        p, q = uv[k], qxy[idx[k, 0]]
        i, j = tuple(np.round(p * 250).astype(int)), tuple(np.round(q / 2).astype(int))
        if i not in a and j not in b:
            a.add(i)
            b.add(j)
            src.append(p)
            dst.append(q)
    if len(src) < 7:
        return None
    src, dst = np.float32(src), np.float32(dst)
    h, mask = cv2.findHomography(src, dst, cv2.RANSAC, 2.5, maxIters=1500)
    if h is None or int(mask.sum()) < 7:
        return None
    src, dst = src[mask.ravel() > 0], dst[mask.ravel() > 0]
    hull = cv2.contourArea(cv2.convexHull(dst))
    if hull < 180 or cv2.contourArea(cv2.convexHull(src)) < 0.001:
        return None
    # A projective pole crossing the observed patch indicates a folded match.
    z = src @ h[2, :2] + h[2, 2]
    if z.min() * z.max() <= 0 or np.linalg.svd(dst - dst.mean(0), compute_uv=False)[1] < 8:
        return None
    return dict(inliers=len(dst), area=round(hull, 1))


def search(folder, files):
    cv2.setNumThreads(3)
    meta = json.loads((folder / "manifest.json").read_bytes())
    offsets = np.load(folder / "offsets.npy", allow_pickle=False)
    desc = np.memmap(
        folder / "descriptors.bin", mode="r", dtype=np.uint8, shape=(int(offsets[-1]), 128)
    ).astype(np.float32)
    uv = np.memmap(folder / "points.bin", mode="r", dtype="<f4", shape=(int(offsets[-1]), 2))
    index = cv2.flann_Index()
    if not index.load(desc, str(folder / "world.flann")):
        raise ValueError("cannot load world index")
    instances = np.load(folder / "placements.npy", allow_pickle=False)
    centers = defaultdict(list)
    for mid, x, y, w in instances:
        for key in meta["modelMaterials"][str(int(mid))]:
            centers[key].append((float(x), float(y), float(w), int(mid)))
    frames, strongest = [], {}
    for file in files:
        t = time.monotonic()
        gray = cv2.imread(str(file), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError("missing frame " + str(file))
        h, w = gray.shape
        gray = cv2.resize(
            gray, (min(w, 1280), max(1, round(h * min(w, 1280) / w))), interpolation=cv2.INTER_AREA
        )
        qxy, qd = features(gray, 3200)
        matches = {}
        if len(qd) >= 9:
            qd = qd.astype(np.float32)
            nn, dist = index.knnSearch(qd, 8, params={"checks": 96})
            owners = np.searchsorted(offsets[1:], nn, side="right")
            # Each feature gets one vote per material, even on repeated façades.
            weights = 1 / (1 + dist / 950.0)
            votes = np.zeros(len(offsets) - 1)
            for i in range(8):
                distinct = (owners[:, :i] != owners[:, i, None]).all(axis=1)
                np.add.at(votes, owners[distinct, i], weights[distinct, i])
            qindex = cv2.flann_Index(qd, dict(algorithm=1, trees=3))
            for key in votes.argsort()[-160:][::-1]:
                start, end = offsets[key : key + 2]
                result = verify_material(uv[start:end], desc[start:end], qxy, qindex)
                if result:
                    key = int(key)
                    matches[key] = result
                    strongest[key] = max(strongest.get(key, 0), result["inliers"])
        frames.append(
            dict(
                file=file.name,
                sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                ms=round(1000 * (time.monotonic() - t)),
                materials=matches,
            )
        )
    cells = defaultdict(dict)
    for key, inliers in strongest.items():
        places = centers[key]
        if not places:
            continue
        cells_for_key = set()
        for x, y, width, _ in places:
            radius = 120 + min(width / 2, 180)
            for ix in range(math.floor((x - radius) / 80), math.floor((x + radius) / 80) + 1):
                for iy in range(math.floor((y - radius) / 80), math.floor((y + radius) / 80) + 1):
                    if math.hypot(ix * 80 + 40 - x, iy * 80 + 40 - y) <= radius:
                        cells_for_key.add((ix, iy))
        weight = math.log1p(inliers - 5) / max(1.0, math.log2(1 + len(cells_for_key)))
        for cell in cells_for_key:
            cells[cell][key] = weight
    candidates = sorted(cells, key=lambda c: -sum(cells[c].values()))
    picks = []
    for cell in candidates:
        x, y = cell[0] * 80 + 40, cell[1] * 80 + 40
        if all(math.hypot(x - p["x"], y - p["y"]) > 160 for p in picks):
            picks.append(
                dict(
                    x=x, y=y, score=round(sum(cells[cell].values()), 3), materials=len(cells[cell])
                )
            )
        if len(picks) >= 10:
            break
    return dict(
        revision=meta["revision"],
        frames=frames,
        areas=picks,
        indexedTextures=len(meta["textures"]),
        indexedPlacements=meta["placements"],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("build")
    make.add_argument("scene", type=Path)
    make.add_argument("index", type=Path)
    query = sub.add_parser("search")
    query.add_argument("index", type=Path)
    query.add_argument("output", type=Path)
    query.add_argument("images", type=Path, nargs="+")
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build(args.scene, args.index)), flush=True)
    else:
        result = search(args.index, args.images)
        args.output.write_text(json.dumps(result), encoding="utf8")
        print(json.dumps(result["areas"]), flush=True)
