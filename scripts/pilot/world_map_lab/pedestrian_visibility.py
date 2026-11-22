"""Keep the first-person camera clear of eye-height cutout meshes along a walking step."""

import gzip
import json
import math
import sqlite3
from functools import lru_cache

import numpy as np
from scipy.spatial.transform import Rotation

from scripts.pilot.world_map_lab.destination_detail import mesh_primitives


def slice_segments(triangles, height):
    """Intersect triangles with a horizontal plane, ignoring horizontal foliage above or below it."""
    crosses = triangles[:, :, 2] > height
    faces = triangles[crosses.any(axis=1) & ~crosses.all(axis=1)]
    starts = faces
    ends = np.roll(faces, 1, axis=1)
    cut = (starts[:, :, 2] > height) != (ends[:, :, 2] > height)
    a, b = starts[cut], ends[cut]
    fraction = (height - a[:, 2]) / (b[:, 2] - a[:, 2])
    return (a[:, :2] + fraction[:, None] * (b[:, :2] - a[:, :2])).reshape(-1, 2, 2)


def foliage_exposure(segments, start, end):
    """Score newly entering and staying within 0.9 metres of an eye-level surface."""
    if not len(segments):
        return 0.0
    samples = np.linspace(start, end, 12)
    direction = segments[:, 1] - segments[:, 0]
    delta = samples[:, None, :] - segments[:, 0]
    fractions = np.clip((delta * direction).sum(2) / np.maximum((direction**2).sum(1), 1e-8), 0, 1)
    nearest = np.linalg.norm(delta - fractions[:, :, None] * direction, axis=2).min(axis=1)
    proximity = np.maximum(0.0, 0.9 - nearest)
    return float(np.mean(proximity[1:]) + proximity[-1])


class PedestrianVisibility:
    def __init__(self, path, revision):
        self.db = sqlite3.connect(
            path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True
        )
        meta = json.loads(self.db.execute("select value from meta").fetchone()[0])
        if meta["revision"] != revision:
            self.db.close()
            raise ValueError("rendered obstacles belong to another map")
        self.mesh = lru_cache(maxsize=32)(self._mesh)
        self.segments = lru_cache(maxsize=32)(self._segments)

    def _mesh(self, model):
        raw = self.db.execute("select glb from model where id=?", (model,)).fetchone()[0]
        return [v[tri] for v, _, tri, _ in mesh_primitives(gzip.decompress(raw), masked_only=True)]

    def _segments(self, cell_x, cell_y, level):
        x, y, height = cell_x * 8, cell_y * 8, level * 0.25
        rows = self.db.execute(
            """select i.model,i.x,i.y,i.z,i.qx,i.qy,i.qz,i.qw
            from spatial s join instance i on i.id=s.id
            where s.minx<=? and s.maxx>=? and s.miny<=? and s.maxy>=?
            and s.minz<=? and s.maxz>=?""",
            (x + 13, x - 5, y + 13, y - 5, height, height),
        )
        result = []
        for model, cx, cy, cz, *quat in rows:
            rotation = Rotation.from_quat(quat)
            for tris in self.mesh(model):
                world = rotation.apply(tris.reshape(-1, 3)).reshape(-1, 3, 3) + [cx, cy, cz]
                lines = slice_segments(world, height)
                local = ((lines.max(1) >= [x - 5, y - 5]) & (lines.min(1) <= [x + 13, y + 13])).all(
                    1
                )
                if local.any():
                    result.append(lines[local])
        return np.concatenate(result) if result else np.empty((0, 2, 2))

    def exposure(self, eye, end):
        lines = self.segments(math.floor(eye[0] / 8), math.floor(eye[1] / 8), round(eye[2] * 4))
        return foliage_exposure(lines, eye[:2], end[:2])

    def close(self):
        self.segments.cache_clear()
        self.mesh.cache_clear()
        self.db.close()
