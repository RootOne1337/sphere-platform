"""Cross-check lower-screen pixels against rays through exterior meshes derived from original DFFs."""

import argparse
import gzip
import json
import math
import sqlite3
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation


class ExteriorScene:
    def __init__(self, db):
        self.db = db

    @lru_cache(maxsize=96)
    def triangles(self, model):
        (packed,) = self.db.execute("select glb from model where id=?", (model,)).fetchone()
        raw = gzip.decompress(packed)
        size = struct.unpack_from("<I", raw, 12)[0]
        header = json.loads(raw[20 : 20 + size])
        body = memoryview(raw)[28 + size :]

        def read(index, columns):
            acc = header["accessors"][index]
            view = header["bufferViews"][acc["bufferView"]]
            offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            dtype = {5123: "<u2", 5125: "<u4", 5126: "<f4"}[acc["componentType"]]
            return np.frombuffer(body, dtype, count=acc["count"] * columns, offset=offset)

        meshes = []
        for prim in header["meshes"][0]["primitives"]:
            pos = read(prim["attributes"]["POSITION"], 3).reshape(-1, 3)
            meshes.append(pos[read(prim["indices"], 1)].reshape(-1, 3, 3))
        tris = np.concatenate(meshes)
        return tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]

    def first_hit(self, eye, direction, limit):
        lower = np.minimum(eye, eye + direction * limit)
        upper = np.maximum(eye, eye + direction * limit)
        rows = self.db.execute(
            "select i.model,m.name,i.x,i.y,i.z,i.qx,i.qy,i.qz,i.qw from spatial s "
            "join instance i using(id) join model m on m.id=i.model "
            "where minx<=? and maxx>=? and miny<=? and maxy>=? and minz<=? and maxz>=?",
            (upper[0], lower[0], upper[1], lower[1], upper[2], lower[2]),
        )
        result = None
        for ident, name, x, y, z, *quat in rows:
            rot = Rotation.from_quat(quat).inv()
            origin = rot.apply(eye - [x, y, z])
            ray = rot.apply(direction)
            p, a, b = self.triangles(ident)
            h = np.cross(ray, b)
            det = np.einsum("ij,ij->i", a, h)
            scale = np.divide(1.0, det, out=np.zeros_like(det), where=np.abs(det) > 1e-8)
            s = origin - p
            u = scale * np.einsum("ij,ij->i", s, h)
            q = np.cross(s, a)
            v = scale * (q @ ray)
            distance = scale * np.einsum("ij,ij->i", b, q)
            hits = distance[
                (u >= 0) & (v >= 0) & (u + v <= 1) & (distance > 0.25) & (distance < limit)
            ]
            if hits.size:
                limit = float(hits.min())
                result = {"model": name, "rangeM": round(limit, 2)}
        return result


def background_evidence(patch, baseline):
    colour_error = np.abs(patch - baseline[:, None, :]).max(axis=2)
    # The calibrated sky changes with height and is almost constant across one scanline.
    # Dark asphalt can have the same mean colour and still have visible horizontal texture.
    horizontal = np.abs(patch - np.median(patch, axis=1, keepdims=True)).max(axis=2)
    return float(np.mean(colour_error <= 6)), float(np.mean(horizontal <= 1))


def sky_gradient(patch, uniform):
    """Identify the native clear gradient when the timecycle shifts its colours."""
    if uniform < 0.90:
        return False
    rows = np.median(patch, axis=1)
    red, green, blue = np.median(rows, axis=0)
    shrink = rows[0] - rows[-1]
    return bool(
        blue > green + 8
        and green > red + 8
        and abs(shrink[0]) < 5
        and shrink[1] >= 3
        and shrink[2] >= 8
        and np.max(np.diff(rows[:, 2])) <= 3
    )


def audit(database, plan, samples, background, output):
    sites = json.loads(plan.read_bytes())["sites"]
    rows = json.loads(samples.read_bytes())
    sky = np.asarray(Image.open(background).convert("RGB"), dtype=np.int16)
    # Calibrate against a verified column of unobstructed lower-screen background.
    # Match a vertical patch including the gradient to reduce false positives on flat materials.
    baseline = sky[:, -32:-20].mean(axis=1)
    results = []
    db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        scene = ExteriorScene(db)
        for i, site in enumerate(sites):
            sample = rows.get(str(i))
            if not sample:
                continue
            eye = np.asarray(sample["nativeCamera"])
            front = np.array(
                sample.get("nativeForward", np.array(site["target"]) - site["eye"]), dtype=float
            )
            front /= np.linalg.norm(front)
            right = np.cross(front, [0, 0, 1])
            right /= np.linalg.norm(right)
            up = np.cross(right, front)
            shot = np.asarray(Image.open(samples.parent / sample["file"]).convert("RGB"))
            height, width = shot.shape[:2]
            if sky.shape != shot.shape:
                raise ValueError("background and observation dimensions differ")
            focal = width / (2 * math.tan(math.radians(sample.get("hfov", 70)) / 2))
            probes = []
            for y in (0.54, 0.59, 0.64, 0.78, 0.90):
                for x in (0.12, 0.31, 0.5, 0.69, 0.88):
                    u, v = round(x * (width - 1)), round(y * (height - 1))
                    vec = (
                        front
                        + (u - (width - 1) / 2) / focal * right
                        - (v - (height - 1) / 2) / focal * up
                    )
                    vec /= np.linalg.norm(vec)
                    hit = scene.first_hit(eye, vec, 180)
                    patch = shot[v - 18 : v + 19, u - 6 : u + 7].astype(np.int16)
                    match, uniform = background_evidence(patch, baseline[v - 18 : v + 19])
                    gradient = sky_gradient(patch, uniform)
                    probes.append(
                        dict(
                            uv=[u, v],
                            source=hit,
                            skyMatch=round(match, 3),
                            horizontalUniformity=round(uniform, 3),
                            skyGradient=gradient,
                            suspect=bool(hit and ((match > 0.93 and uniform >= 0.7) or gradient)),
                        )
                    )
            results.append(dict(cell=site["cell"], sample=i, probes=probes))
    finally:
        db.close()
    output.write_text(json.dumps(results, indent=2), encoding="utf8")
    return results


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for field in ("database", "plan", "samples", "background", "output"):
        cli.add_argument("--" + field, type=Path, required=True)
    findings = audit(**vars(cli.parse_args()))
    print(
        "frames",
        len(findings),
        "suspect frames",
        sum(any(q["suspect"] for q in s["probes"]) for s in findings),
    )
