"""Recover a map pose from verified flow against two neighboring rendered keyframes."""

import math

import cv2
import numpy as np


class PatchReferences:
    def __init__(self, path, indexed):
        self.map = indexed.atlas
        with np.load(path, allow_pickle=False) as data:
            self.grays = data["gray"]
            self.points = data["surface"]
            self.uv = data["uv"]
            self.spans = data["spans"]
        self.stations = np.array([v["s"] for v in indexed.views])
        if len(self.stations) != len(self.grays) or len(self.spans) != len(self.grays):
            raise ValueError("incomplete reference images")
        self.K = self.map.K.copy()
        self.K[:2] *= 0.5
        self.K[:2, 2] -= 0.25
        self.putatives = None

    def observe(self, rgb, lo, hi, predicted):
        self.putatives = None
        if hi < lo:
            return None
        gray = cv2.resize(
            cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY),
            (self.grays.shape[2], self.grays.shape[1]),
            interpolation=cv2.INTER_AREA,
        )
        options = dict(winSize=(19, 19), maxLevel=3, criteria=(3, 25, 0.025))
        proposals = []
        indices = np.flatnonzero((self.stations >= lo - 3) & (self.stations <= hi + 3))
        for i in sorted(indices, key=lambda j: abs(self.stations[j] - predicted))[:12]:
            start, stop = self.spans[i]
            source = self.uv[start:stop]
            if len(source) < 24:
                continue
            ref = self.grays[i]
            uv, live, err = cv2.calcOpticalFlowPyrLK(ref, gray, source, None, **options)
            back, valid, _ = cv2.calcOpticalFlowPyrLK(gray, ref, uv, None, **options)
            mask = (
                live.ravel().astype(bool)
                & valid.ravel().astype(bool)
                & (np.linalg.norm(back - source, axis=1) < 0.65)
                & (err.ravel() < 18)
            )
            if mask.sum() < 28:
                continue
            pixels = uv[mask]
            points = self.points[start:stop][mask]
            ok, r, t, idx = cv2.solvePnPRansac(
                points,
                pixels,
                self.K,
                None,
                iterationsCount=260,
                reprojectionError=1.6,
                confidence=0.998,
                flags=cv2.SOLVEPNP_AP3P,
            )
            if not ok or idx is None or len(idx) < 25 or len(idx) < 0.52 * len(points):
                continue
            pixels = pixels[idx.ravel()]
            points = points[idx.ravel()]
            if cv2.contourArea(cv2.convexHull(pixels)) < 0.045 * gray.size:
                continue
            sv = np.linalg.svd(points - points.mean(axis=0), compute_uv=False)
            if sv[-1] < max(0.10, 0.012 * sv[0]):
                continue
            r, t = cv2.solvePnPRefineLM(points, pixels, self.K, None, r, t)
            rotation = cv2.Rodrigues(r)[0]
            if np.mean((points @ rotation[2] + t[2, 0]) > 0.5) < 0.98:
                continue
            center = -rotation.T @ t[:, 0]
            station, lateral = self.map.locate_progress(center)
            err = float(
                np.median(
                    np.linalg.norm(
                        cv2.projectPoints(points, r, t, self.K, None)[0][:, 0] - pixels, axis=1
                    )
                )
            )
            if err > 0.9 or not lo <= station <= hi or lateral > 2.2:
                continue
            proposals.append(
                (
                    center + self.map.origin,
                    rotation,
                    station,
                    len(points),
                    2 * err,
                    self.stations[i],
                    points,
                    pixels * 2 + 0.5,
                )
            )
        if len(proposals) < 2:
            return None
        best = max(proposals, key=lambda p: p[3])
        agree = []
        for other in proposals:
            consistent = np.linalg.norm(best[0] - other[0]) < 0.45 and best[1][2] @ other[1][
                2
            ] > math.cos(math.radians(2))
            if consistent and abs(best[5] - other[5]) > 1.0:
                agree.append(other)
            elif not consistent and other[3] >= 0.7 * best[3]:
                return None
        if not agree:
            return None
        self.putatives = best[-2:]
        return best[:5]
