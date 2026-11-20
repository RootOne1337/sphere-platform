"""Short-lived optical tracking of previously verified RGB-to-map correspondences."""

import math

import cv2
import numpy as np


class LandmarkTrack:
    def __init__(self, atlas, *, max_travel=None):
        self.atlas = atlas
        self.max_travel = max_travel
        self.points = None
        self.anchor = -math.inf

    def seed(self, rgb, putatives, eye, rotation, t):
        if putatives is None:
            return
        points, pixels = putatives
        relative = eye - self.atlas.origin
        transformed = (points - relative) @ rotation.T
        visible = transformed[:, 2] > 0.5
        projected = transformed @ self.atlas.K.T
        pred = projected[:, :2] / np.where(visible, projected[:, 2], 1)[:, None]
        take = visible & (np.linalg.norm(pred - pixels, axis=1) < 1.8)
        if take.sum() < 26:
            return
        self.points = points[take]
        self.pixels = pixels[take]
        self.gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        self.anchor = t
        self.anchor_eye = relative.copy()

    def track(self, rgb, t, lo, hi):
        if self.points is None or not 0 < t - self.anchor <= 1.0:
            return None
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        opts = dict(
            winSize=(25, 25),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 25, 0.03),
        )
        px, ok, _ = cv2.calcOpticalFlowPyrLK(self.gray, gray, self.pixels, None, **opts)
        back, valid, _ = cv2.calcOpticalFlowPyrLK(gray, self.gray, px, None, **opts)
        take = (
            ok.ravel().astype(bool)
            & valid.ravel().astype(bool)
            & (np.linalg.norm(back - self.pixels, axis=1) < 0.75)
        )
        points = self.points[take]
        screen = px[take]
        self.points = None
        if len(points) < 22:
            return None
        m = self.atlas
        ok, r, tv, idx = cv2.solvePnPRansac(
            points,
            screen,
            m.K,
            None,
            iterationsCount=240,
            reprojectionError=2.4,
            confidence=0.998,
            flags=cv2.SOLVEPNP_AP3P,
        )
        if not ok or idx is None or len(idx) < 22 or len(idx) < 0.7 * len(points):
            return None
        pts = points[idx.ravel()]
        uv = screen[idx.ravel()]
        if cv2.contourArea(cv2.convexHull(uv)) < 0.045 * m.H * m.W:
            return None
        sig = np.linalg.svd(pts - pts.mean(axis=0), compute_uv=False)
        if sig[-1] < max(0.1, 0.012 * sig[0]):
            return None
        r, tv = cv2.solvePnPRefineLM(pts, uv, m.K, None, r, tv)
        rot = cv2.Rodrigues(r)[0]
        center = -rot.T @ tv[:, 0]
        if (
            self.max_travel is not None
            and np.linalg.norm(center - self.anchor_eye) > self.max_travel
        ):
            return None
        mask = (np.floor(uv[:, 0] / 80) + np.floor(uv[:, 1] / 64)).astype(int) % 2 == 0
        for sub in (mask, ~mask):
            if sub.sum() < 8:
                return None
            ok, rotvec, tr = cv2.solvePnP(pts[sub], uv[sub], m.K, None, flags=cv2.SOLVEPNP_SQPNP)
            if not ok:
                return None
            rr = cv2.Rodrigues(rotvec)[0]
            if np.linalg.norm(-rr.T @ tr[:, 0] - center) > 0.4 or rr[2] @ rot[2] < 0.9992:
                return None
        s, cross = m.locate_progress(center)
        if not lo <= s <= hi or cross > 2.2:
            return None
        error = float(
            np.median(
                np.linalg.norm(cv2.projectPoints(pts, r, tv, m.K, None)[0][:, 0] - uv, axis=1)
            )
        )
        if error > 1.5:
            return None
        self.points = pts
        self.pixels = uv
        self.gray = gray
        return center + m.origin, rot, s, len(pts), error
