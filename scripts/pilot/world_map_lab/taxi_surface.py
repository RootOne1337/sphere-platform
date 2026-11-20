"""Rasterize the pedestrian components accessible from one taxi origin, including a single ride."""

from functools import lru_cache
from io import BytesIO
from threading import Lock

import cv2
import numpy as np
from PIL import Image


class TaxiSurface:
    def __init__(self, trip, size=3072):
        self.trip = trip
        self.size = size
        self.foot_groups = {}
        for foot, roads in trip.transfers.items():
            for road in roads:
                self.foot_groups.setdefault(road, set()).add(foot)
        self.ranges = None
        self.lock = Lock()
        self.cached = lru_cache(maxsize=12)(self._paint)

    def png(self, start):
        walk = self.trip.walk
        if np.shape(start) != (3,) or not np.isfinite(start).all():
            raise ValueError("expected origin XYZ")
        if not any(abs(z - start[2]) <= 0.5 for z in walk.levels(*start[:2])):
            raise ValueError("no walking surface at this elevation")
        component = walk.component(start)
        if component is None:
            raise ValueError("unknown origin component")
        groups = {component}
        for road in self.trip.transfers.get(component, {}):
            groups.update(self.foot_groups[road])
        with self.lock:
            return self.cached(tuple(sorted(groups)))

    def _index(self):
        faces = self.trip.walk.faces()
        order = np.argsort(faces["group"], kind="stable")
        groups, starts, counts = np.unique(
            faces["group"][order], return_index=True, return_counts=True
        )
        left, right, bottom, top = self.trip.walk.meta["bounds"]
        coords = np.empty((len(faces), 6, 2), dtype=np.int16)
        # Batch conversion bounds the temporary memory used by a full world.
        for i in range(0, len(order), 32768):
            region = order[i : i + 32768]
            polys = faces["xyz"][region]
            coords[i : i + len(region), :, 0] = np.rint(
                (polys[:, :, 0] - left) / (right - left) * (self.size - 1)
            )
            coords[i : i + len(region), :, 1] = np.rint(
                (top - polys[:, :, 1]) / (top - bottom) * (self.size - 1)
            )
        self.coords, self.lengths = coords, faces["vertices"][order].astype(np.uint8)
        self.ranges = dict(zip(map(int, groups), zip(starts, counts), strict=True))

    def _paint(self, groups):
        if self.ranges is None:
            self._index()
        mask = np.zeros((self.size, self.size), np.uint8)
        for group in groups:
            start, count = self.ranges[group]
            for i in range(start, start + count, 32768):
                stop = min(i + 32768, start + count)
                coords = self.coords[i:stop].astype(np.int32)
                for face, n in zip(coords, self.lengths[i:stop], strict=True):
                    cv2.fillConvexPoly(mask, face[:n], 1)
        img = Image.fromarray(mask)
        img.putpalette([0, 0, 0, 128, 246, 183])
        out = BytesIO()
        img.save(out, format="PNG", bits=1, transparency=bytes([0, 108]))
        return out.getvalue()
