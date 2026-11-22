"""Orthographic street tiles from the indexed Ariane meshes and their original UVs."""

import gzip
import hashlib
import json
import math
import sqlite3
import struct
from contextlib import closing
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from threading import Lock

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

from scripts.pilot.world_map_lab.render_ariane_world import (
    SKY,
    WATER,
    render,
    shaded,
    water_triangles,
)


def mesh_primitives(raw, *, masked_only=False):
    n = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20 : 20 + n])
    body = memoryview(raw)[28 + n :]

    def read(index):
        a = doc["accessors"][index]
        v = doc["bufferViews"][a["bufferView"]]
        dtype = {5126: "<f4", 5123: "<u2", 5125: "<u4"}[a["componentType"]]
        dims = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
        return np.frombuffer(
            body,
            dtype,
            count=a["count"] * dims,
            offset=v.get("byteOffset", 0) + a.get("byteOffset", 0),
        ).reshape(-1, dims)

    primitives = []
    for part in doc["meshes"][0]["primitives"]:
        if masked_only and doc["materials"][part["material"]].get("alphaMode") != "MASK":
            continue
        attrs = part["attributes"]
        tri = read(part["indices"]).reshape(-1, 3)
        mat = doc["materials"][part["material"]]["pbrMetallicRoughness"]["baseColorTexture"][
            "index"
        ]
        key = Path(doc["images"][doc["textures"][mat]["source"]]["uri"]).stem
        primitives.append((read(attrs["POSITION"]), read(attrs["TEXCOORD_0"]), tri, key))
    return primitives


class StreetTiles:
    pixels = 512
    spans = (256, 64)

    def __init__(self, folder, water_file, bounds, revision):
        from numba import njit

        db = folder / "detail-scene.sqlite"
        self.uri = db.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(self.uri, uri=True)) as con:
            meta = json.loads(con.execute("select value from meta").fetchone()[0])
        if meta["revision"] != revision or water_file.name != "water.dat":
            raise ValueError("street geometry or water source does not match the map")
        self.texture_limit = meta.get("textureLimit")
        self.layered_materials = meta.get("layeredMaterials", 0)
        self.bounds = bounds
        with db.open("rb") as f:
            signature = hashlib.file_digest(f, "sha256").hexdigest()
        self.version = hashlib.sha256(
            (
                revision
                + signature
                + hashlib.sha256(water_file.read_bytes()).hexdigest()
                + "street-v1"
            ).encode()
        ).hexdigest()
        self.water = np.asarray(list(water_triangles(water_file.parent.parent)))
        self.wmin = self.water.min(1)
        self.wmax = self.water.max(1)
        self.raster = njit(cache=True, nogil=True)(render)
        self.lock = Lock()
        self.cached = lru_cache(maxsize=128)(self._make)
        self.meshes = lru_cache(maxsize=32)(self._mesh)
        self.textures = lru_cache(maxsize=96)(self._texture)

    def manifest(self):
        return dict(
            revision=self.version,
            spans=self.spans,
            pixels=self.pixels,
            textureLimit=self.texture_limit,
            layeredMaterials=self.layered_materials,
        )

    def _texture(self, key):
        row = self.db.execute("select png from texture where key=?", (key,)).fetchone()
        with Image.open(BytesIO(row[0])) as im:
            return np.array(im.convert("RGBA"))

    def _mesh(self, model):
        raw = gzip.decompress(
            self.db.execute("select glb from model where id=?", (model,)).fetchone()[0]
        )
        return mesh_primitives(raw)

    def tile(self, span, col, row):
        left, right, bottom, top = self.bounds
        if span not in self.spans or not (
            0 <= col < math.ceil((right - left) / span)
            and 0 <= row < math.ceil((top - bottom) / span)
        ):
            raise KeyError("tile outside map")
        with self.lock:
            return self.cached(span, col, row)

    def _make(self, span, col, row):
        with closing(sqlite3.connect(self.uri, uri=True)) as db:
            self.db = db  # Only used under the renderer lock, including cache misses.
            return self._render(db, span, col, row)

    def _render(self, db, span, col, row):
        left = self.bounds[0] + col * span
        top = self.bounds[3] - row * span
        ppm = self.pixels / span
        frame = np.empty((self.pixels, self.pixels, 3), np.uint8)
        frame[:] = SKY
        depth = np.full((self.pixels, self.pixels), np.inf, np.float32)

        def paint(world, uv, rgba, light):
            screen = world.copy()
            screen[:, :, 0] = (world[:, :, 0] - left) * ppm
            screen[:, :, 1] = (top - world[:, :, 1]) * ppm
            screen[:, :, 2] = -world[:, :, 2]
            self.raster(
                np.asarray(screen, np.float32),
                np.asarray(uv, np.float32),
                np.asarray(light, np.float32),
                np.zeros(len(screen), np.int32),
                rgba.reshape(-1, 4),
                np.array([0], np.int64),
                np.array([[rgba.shape[1], rgba.shape[0]]], np.int64),
                frame,
                depth,
            )

        wet = self.water[
            (self.wmin[:, 0] < left + span)
            & (self.wmax[:, 0] > left)
            & (self.wmin[:, 1] < top)
            & (self.wmax[:, 1] > top - span)
        ]
        if len(wet):
            paint(
                wet,
                np.zeros((len(wet), 3, 2)),
                np.array([[(*WATER, 255)]], np.uint8),
                np.ones(len(wet)),
            )
        rows = db.execute(
            """select i.model,i.x,i.y,i.z,i.qx,i.qy,i.qz,i.qw from spatial s
             join instance i on i.id=s.id where s.minx<? and s.maxx>? and s.miny<? and s.maxy>?
             order by i.model,i.id""",
            (left + span, left, top, top - span),
        )
        for model, x, y, z, *quat in rows:
            rot = Rotation.from_quat(quat)
            pos = np.array([x, y, z])
            for verts, uv, tri, key in self.meshes(model):
                world = (rot.apply(verts) + pos)[tri]
                valid = (
                    (world[:, :, 0].min(1) < left + span)
                    & (world[:, :, 0].max(1) > left)
                    & (world[:, :, 1].min(1) < top)
                    & (world[:, :, 1].max(1) > top - span)
                )
                if np.any(valid):
                    subset = world[valid]
                    paint(subset, uv[tri[valid]], self.textures(key), shaded(subset))
        output = BytesIO()
        Image.fromarray(frame).save(output, format="WEBP", quality=92, method=3)
        return output.getvalue()
