"""Experimental route-local visual pose from indexed RootSIFT landmarks and disjoint support."""

import math
from collections import OrderedDict

import cv2
import numpy as np


class IndexedLandmarks:
    """One shared descriptor index per neighborhood. No access to simulator state."""

    def __init__(self, atlas):
        self.atlas = atlas
        self.views = tuple(atlas.views)
        self.cache = OrderedDict()
        self.detector = cv2.SIFT_create(nfeatures=1400, contrastThreshold=0.022)
        self.last_reason = "no_frame"

    def bank(self, tile):
        if tile not in self.cache:
            station = 12 * tile
            views = [v for v in self.views if station - 10 <= v["s"] <= station + 22]
            if not views:
                return None
            ids = np.concatenate([np.arange(*v["range"], dtype=np.int32) for v in views])
            locations = np.concatenate(
                [np.full(v["range"][1] - v["range"][0], v["s"], np.float32) for v in views]
            )
            if len(ids) < 8:
                return None
            desc = np.ascontiguousarray(self.atlas.desc[ids], dtype=np.float32)
            matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=72))
            matcher.add([desc])
            matcher.train()
            self.cache[tile] = matcher, ids, locations
            if len(self.cache) > 2:
                self.cache.popitem(last=False)
        self.cache.move_to_end(tile)
        return self.cache[tile]

    def features(self, rgb):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        keys, desc = self.detector.detectAndCompute(gray, None)
        if desc is None:
            return None
        return np.float32([k.pt for k in keys]), np.sqrt(
            desc / (desc.sum(axis=1, keepdims=True) + 1e-8)
        )

    def __call__(self, rgb, lo, hi):
        return self.match(self.features(rgb), lo, hi)

    def match(self, features, lo, hi, *, require_corridor=True):
        self.putatives = None
        self.evidence = {"distinct": 0, "inliers": 0}
        self.last_reason = "insufficient_correspondences"
        if features is None:
            return None
        uv, desc = features
        m = self.atlas
        bank = self.bank(math.floor((lo + hi) / 24))
        if bank is None:
            return None
        matcher, ids, stations = bank
        matches = matcher.knnMatch(desc, k=8)
        chosen = {}
        for row in matches:
            if len(row) < 2:
                continue
            best = row[0]
            xyz = m.xyz[ids[best.trainIdx]]
            competing = next(
                (a for a in row[1:] if np.max(abs(m.xyz[ids[a.trainIdx]] - xyz)) > 0.30), None
            )
            if competing is None or best.distance >= 0.77 * competing.distance:
                continue
            key = tuple(np.rint(xyz / 0.20).astype(int))
            if key not in chosen or best.distance < chosen[key][0]:
                chosen[key] = (best.distance, xyz, uv[best.queryIdx], stations[best.trainIdx])
        self.evidence["distinct"] = len(chosen)
        if len(chosen) < 30:
            return None
        vals = list(chosen.values())
        points = np.float32([v[1] for v in vals])
        pixels = np.float32([v[2] for v in vals])
        views = np.asarray([v[3] for v in vals])
        self.putatives = points, pixels
        ok, r, t, idx = cv2.solvePnPRansac(
            points,
            pixels,
            m.K,
            None,
            iterationsCount=500,
            reprojectionError=2.8,
            confidence=0.998,
            flags=cv2.SOLVEPNP_AP3P,
        )
        self.last_reason = "insufficient_geometric_support"
        self.evidence["inliers"] = len(idx) if ok and idx is not None else 0
        if not ok or idx is None or len(idx) < 30 or len(idx) < 0.28 * len(vals):
            return None
        use = idx.ravel()
        coords, screen = points[use], pixels[use]
        self.last_reason = "single_view_or_narrow_image_support"
        if np.ptp(views[use]) < 1 or cv2.contourArea(cv2.convexHull(screen)) < 0.05 * m.W * m.H:
            return None
        sig = np.linalg.svd(coords - coords.mean(axis=0), compute_uv=False)
        self.last_reason = "insufficient_3d_spread"
        if sig[-1] < max(0.11, 0.013 * sig[0]):
            return None
        r, t = cv2.solvePnPRefineLM(coords, screen, m.K, None, r, t)
        rot = cv2.Rodrigues(r)[0]
        center = -rot.T @ t[:, 0]
        residuals = np.linalg.norm(
            cv2.projectPoints(coords, r, t, m.K, None)[0][:, 0] - screen, axis=1
        )
        med = float(np.median(residuals))
        s, cross = m.locate_progress(center)
        self.last_reason = (
            "outside_corridor"
            if not lo <= s <= hi or (require_corridor and cross > 2.2)
            else "reprojection_or_cheirality"
        )
        if (
            not lo <= s <= hi
            or (require_corridor and cross > 2.2)
            or med > 1.7
            or np.mean((coords @ rot[2] + t[2, 0]) > 0) < 0.98
        ):
            return None
        # Fit interleaved image cells independently, without initializing either pose from the other.
        mask = (np.floor(screen[:, 0] / 80) + np.floor(screen[:, 1] / 64)).astype(int) % 2 == 0
        self.last_reason = "disjoint_pose_disagreement"
        for sub in (mask, ~mask):
            if sub.sum() < 10:
                return None
            subok, sr, st = cv2.solvePnP(
                coords[sub], screen[sub], m.K, None, flags=cv2.SOLVEPNP_SQPNP
            )
            if not subok:
                return None
            rr = cv2.Rodrigues(sr)[0]
            if np.linalg.norm(-rr.T @ st[:, 0] - center) > 0.45 or rr[2] @ rot[2] < math.cos(
                math.radians(2.2)
            ):
                return None
        self.last_reason = "accepted"
        return center + m.origin, rot, float(s), len(use), med
