"""Cross-renderer camera pose from two independent, depth-backed reference views."""

import math
from functools import lru_cache

import cv2
import numpy as np

from scripts.pilot.world_map_lab.check_journey_rgb import H, W, angle
from scripts.pilot.world_map_lab.classic_transfers import pose_corridor


def search_station(station, speed, elapsed, misses):
    """Choose a retrieval window while a rolling vehicle may still be moving after a lost pose."""
    if misses < 1 or speed < 1.0:
        return station
    reach = min(48.0, elapsed * min(24.0, speed + 3))
    # Unobserved deceleration is unknown. Revisit the last fix and intermediate stops.
    fraction = (1.0, 0.5, 0.0, 0.75, 0.25)[(misses // 2) % 5]
    return station + fraction * reach


class KeyframePose:
    def __init__(self, pilot):
        self.pilot = pilot
        self.sift = cv2.SIFT_create(0, 3, 0.012)
        self.clahe = cv2.createCLAHE(2, (6, 6))
        self.matcher = cv2.BFMatcher()
        self.tracks = None
        self.tracked = False

    def features(self, gray):
        points, desc = self.sift.detectAndCompute(self.clahe.apply(gray), None)
        if desc is None:
            return None
        return np.float32([p.pt for p in points]), np.sqrt(
            desc / np.maximum(desc.sum(axis=1, keepdims=True), 1e-8)
        )

    @lru_cache(maxsize=48)
    def reference(self, start, length, focal):
        ref, raw = self.pilot.reference_image(start, length)
        features = self.features(ref)
        if features is None:
            return None
        xy, descriptors = features
        depth = raw.astype(np.float32) / 128.0
        ix, iy = np.rint(xy).astype(int).T
        z = depth[iy, ix]
        spread = (cv2.dilate(depth, None) - cv2.erode(depth, None))[iy, ix]
        keep = (z > 1.3) & (z < 130) & (spread < np.maximum(1.4, z * 0.065))
        xyz = np.column_stack(
            [
                (xy[:, 0] - (W - 1) / 2) * z / focal,
                (xy[:, 1] - (H - 1) / 2) * z / focal,
                z,
            ]
        )
        return xyz[keep], descriptors[keep]

    def solve(self, view, live, intrinsics):
        src = self.reference(*view["bytes"], view.get("focalAt320", self.pilot.map_focal))
        if src is None or len(src[0]) < 14 or len(live[0]) < 2:
            return None
        xyz, descriptors = src
        matches = self.matcher.knnMatch(descriptors, live[1], k=2)
        pairs = sorted(
            (a for a, b in matches if a.distance < 0.85 * b.distance), key=lambda a: a.distance
        )
        points, pixels, occupied = [], [], set()
        for m in pairs:
            pixel = live[0][m.trainIdx]
            key = tuple(np.rint(pixel).astype(int))
            if key not in occupied:
                occupied.add(key)
                points.append(xyz[m.queryIdx])
                pixels.append(pixel)
        if len(points) < 14:
            return None
        pts, uv = np.float64(points), np.float64(pixels)
        ok, r, t, ids = cv2.solvePnPRansac(
            pts,
            uv,
            intrinsics,
            None,
            iterationsCount=360,
            reprojectionError=2.0,
            confidence=0.997,
            flags=cv2.SOLVEPNP_AP3P,
        )
        if not ok or ids is None or len(ids) < 14:
            return None
        ids = ids.ravel()
        if np.any(np.ptp(uv[ids], axis=0) < [0.23 * W, 0.17 * H]) or np.ptp(pts[ids, 2]) < 1.25:
            return None
        r, t = cv2.solvePnPRefineLM(pts[ids], uv[ids], intrinsics, None, r, t)
        rot = cv2.Rodrigues(r)[0]
        if (pts[ids] @ rot[2] + t[2, 0]).min() < 0.1:
            return None
        yaw, pitch = view["pose"][3:]
        c, s = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        axes = np.array([[s, -c, 0], [sp * c, sp * s, -cp], [cp * c, cp * s, sp]])
        origin = np.asarray(view["pose"][:3])
        return (
            origin - (rot.T @ t).ravel() @ axes,
            rot @ axes,
            len(ids),
            (origin + pts[ids] @ axes, uv[ids]),
        )

    @staticmethod
    def independent_views(first, second, intrinsics):
        """Solve using disjoint live image regions and validate each pose on the other set."""
        subsets = []
        for parity, (world, pixels) in enumerate((first, second)):
            cell = np.floor(pixels / [W / 6, H / 4]).astype(int)
            select = (cell.sum(axis=1) % 2) == parity
            pts, uv = world[select], pixels[select]
            if len(pts) < 7 or np.any(np.ptp(uv, axis=0) < [0.17 * W, 0.13 * H]):
                return False
            subsets.append((pts, uv))
        # Adjacent regions may still share one physical corner on the boundary.
        distances = np.linalg.norm(subsets[0][1][:, None] - subsets[1][1], axis=2)
        unique = distances.min(axis=0) > 2.5
        subsets[1] = tuple(a[unique] for a in subsets[1])
        if len(subsets[1][0]) < 7:
            return False
        origin = subsets[0][0].mean(axis=0)
        eyes, heads = [], []
        for i, (pts, uv) in enumerate(subsets):
            local = pts - origin
            ok, r, t = cv2.solvePnP(local, uv, intrinsics, None, flags=cv2.SOLVEPNP_EPNP)
            if not ok:
                return False
            r, t = cv2.solvePnPRefineLM(local, uv, intrinsics, None, r, t)
            rot = cv2.Rodrigues(r)[0]
            test, obs = subsets[1 - i]
            test = test - origin
            proj = cv2.projectPoints(test, r, t, intrinsics, None)[0][:, 0]
            residual = np.linalg.norm(proj - obs, axis=1)
            if (test @ rot[2] + t[2, 0]).min() < 0.1 or np.quantile(residual, 0.8) > 2.25:
                return False
            eyes.append(-(rot.T @ t).ravel())
            heads.append(rot[2])
        return np.linalg.norm(eyes[0] - eyes[1]) < 0.34 and heads[0] @ heads[1] > 0.9993

    @lru_cache(maxsize=12)
    def depth_grid(self, start, size, focal):
        gray, depth = self.pilot.reference_image(start, size)
        z = depth.astype("f4") / 128
        y, x = np.indices((H, W), dtype="f4")
        points = np.dstack(
            (
                (x - (W - 1) / 2) * z / focal,
                (y - (H - 1) / 2) * z / focal,
                z,
            )
        )
        return gray, points

    def confirm_projection(self, view, eye, rotation, evidence, gray, k):
        """Check corners withheld from PnP by reprojecting the source depth into the live frame."""
        ref, xyz = self.depth_grid(*view["bytes"], view.get("focalAt320", self.pilot.map_focal))
        yaw, pitch = view["pose"][3:]
        c, s, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
        axes = np.float32([[s, -c, 0], [sp * c, sp * s, -cp], [cp * c, cp * s, sp]])
        offset = np.float32(view["pose"][:3] - eye) @ rotation.T
        camera = xyz @ (axes @ rotation.T).astype("f4") + offset.astype("f4")
        uv = (
            camera[:, :, :2] / np.maximum(0.01, camera[:, :, 2:]) * [k[0, 0], k[1, 1]] + k[:2, 2]
        ).astype("f4")
        valid = (
            (xyz[:, :, 2] > 1.3)
            & (xyz[:, :, 2] < 130)
            & (camera[:, :, 2] > 0.5)
            & (uv[:, :, 0] >= 2)
            & (uv[:, :, 0] < W - 2)
            & (uv[:, :, 1] >= 2)
            & (uv[:, :, 1] < H - 2)
        )
        used = np.zeros((H, W), np.uint8)
        for u, v in np.rint(evidence[1]).astype(int):
            cv2.circle(used, (u, v), 9, 255, -1)
        visible = cv2.remap(used, uv, None, cv2.INTER_NEAREST) == 0
        mask = cv2.erode((valid & visible).astype("u1"), np.ones((13, 13), "u1"))
        corners = cv2.goodFeaturesToTrack(ref, 120, 0.012, 8, mask=mask)
        if corners is None:
            return False
        sample = cv2.remap(gray, uv, None, cv2.INTER_LINEAR)
        good = []
        for x, y in np.rint(corners[:, 0]).astype(int):
            if x < 9 or y < 9 or x >= W - 9 or y >= H - 9:
                continue
            template = ref[y - 5 : y + 6, x - 5 : x + 6]
            if template.std() < 7:
                continue
            score = cv2.matchTemplate(
                sample[y - 8 : y + 9, x - 8 : x + 9], template, cv2.TM_CCOEFF_NORMED
            )
            _, peak, _, (u, v) = cv2.minMaxLoc(score)
            if peak < 0.72 or (u - 3) ** 2 + (v - 3) ** 2 > 2:
                continue
            alt = score.copy()
            alt[max(0, v - 1) : v + 2, max(0, u - 1) : u + 2] = -1
            if peak - alt.max() > 0.055:
                good.append((x, y))
        return (
            len(good) >= 8
            and np.all(np.ptp(good, axis=0) > [0.24 * W, 0.16 * H])
            and len(set((x // 64, y // 45) for x, y in good)) >= 4
        )

    def track(self, gray, phase, t, k, station, previous):
        if self.tracks is None or previous is None:
            return None
        born, last, old_phase, old, world, pixels = self.tracks
        if phase != old_phase or not 0 < t - last < 0.5 or t - born > 1.25:
            self.tracks = None
            return None
        opts = dict(winSize=(21, 21), maxLevel=3)
        now, good, _ = cv2.calcOpticalFlowPyrLK(old, gray, pixels, None, **opts)
        back, valid, _ = cv2.calcOpticalFlowPyrLK(gray, old, now, None, **opts)
        mask = (good[:, 0] & valid[:, 0]).astype(bool)
        mask &= np.linalg.norm(back - pixels, axis=1) < 0.75
        mask &= np.all((now >= [1, 1]) & (now < [W - 1, H - 1]), axis=1)
        world, uv = world[mask], now[mask]
        if len(world) < 14:
            return None
        origin = world.mean(axis=0)
        local = world - origin
        ok, r, tvec, ids = cv2.solvePnPRansac(
            local, uv, k, None, iterationsCount=120, reprojectionError=1.75, flags=cv2.SOLVEPNP_AP3P
        )
        if not ok or ids is None or len(ids) < 14:
            return None
        good = ids[:, 0]
        pts = (world[good], uv[good])
        if not self.independent_views(pts, pts, k):
            return None
        r, tvec = cv2.solvePnPRefineLM(local[good], uv[good], k, None, r, tvec)
        rot = cv2.Rodrigues(r)[0]
        eye = origin - (rot.T @ tvec).ravel()
        index = self.pilot.indices[phase].atlas
        s, cross = index.locate_progress(eye - index.origin)
        limit = 1.1 + (24 if phase == 1 else 5) * (t - previous[0])
        if (
            cross > pose_corridor(phase)
            or abs(s - station) > 8
            or np.linalg.norm(eye - previous[1][0]) > limit
        ):
            return None
        self.tracks = born, t, phase, gray, pts[0], pts[1]
        self.tracked = True
        return eye, rot, s, len(good), None

    def locate(self, rgb, phase, station, heading, previous, t):
        p = self.pilot
        gray = cv2.resize(
            cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (W, H), interpolation=cv2.INTER_AREA
        )
        self.tracked = False
        k = p.K.copy()
        k[:2] *= W / p.size[0]
        k[0, 2], k[1, 2] = (W - 1) / 2, (H - 1) / 2
        if self.tracks and t - self.tracks[0] < 0.5:
            tracked = self.track(gray, phase, t, k, station, previous)
            if tracked is not None:
                return tracked
        live = self.features(gray)
        if live is None:
            return None
        if p.misses >= 6:
            heading = angle(heading + (0, 1.1, -1.1, math.pi)[(p.misses // 6) % 4])
        search = (
            search_station(station, p.station_speed, max(0, t - previous[0]), p.misses)
            if previous and phase == 1
            else station
        )
        views = [
            v
            for v in p.image_views[phase]
            if abs(v["s"] - search) < 10 and abs(angle(v["pose"][3] - heading)) < 1.5
        ]
        # Probe further along the route after coasting out of the last reference.
        # Rotate the search centre, retaining a strict two-view agreement gate.
        offsets = (0, 3, -3, 6, -6)
        center = search + offsets[(p.misses // 2) % len(offsets)]
        views.sort(key=lambda v: abs(v["s"] - center) + 3 * abs(angle(v["pose"][3] - heading)))
        # Keep native observations in the shortlist when both renderers cover a corner.
        native = [v for v in views if "focalAt320" in v][:5]
        selected = {tuple(v["bytes"]) for v in native}
        views = native + [v for v in views if tuple(v["bytes"]) not in selected]
        fits = []
        project = p.indices[phase].atlas.locate_progress
        for v in views[:8]:
            fit = self.solve(v, live, k)
            if fit is None:
                continue
            eye, rotation, n, evidence = fit
            s, cross = project(eye - p.indices[phase].atlas.origin)
            if cross > pose_corridor(phase) or abs(s - search) > 8:
                continue
            if previous:
                dt = t - previous[0]
                if dt <= 0 or np.linalg.norm(eye - previous[1][0]) > 1.1 + min(dt, 2) * (
                    24 if phase == 1 else 5
                ):
                    continue
            for old, other, head, m, old_evidence in fits:
                if np.linalg.norm(eye - other) < 0.34 and head @ rotation[2] > 0.9993:
                    translated = abs(old["s"] - v["s"]) >= 0.75
                    rotated = abs(angle(old["pose"][3] - v["pose"][3])) >= 0.5
                    pair = (old_evidence, evidence) if m >= n else (evidence, old_evidence)
                    if translated or (rotated and self.independent_views(*pair, k)):
                        world, uv = (np.concatenate(a) for a in zip(old_evidence, evidence))
                        _, unique = np.unique(np.rint(uv).astype(int), return_index=True, axis=0)
                        self.tracks = t, t, phase, gray, world[unique], uv[unique].astype("f4")
                        return eye, rotation, s, min(n, m), None
            if (
                previous
                and abs(s - station) <= 8
                and self.confirm_projection(v, eye, rotation, evidence, gray, k)
            ):
                world, uv = evidence
                self.tracks = t, t, phase, gray, world, uv.astype("f4")
                return eye, rotation, s, n, None
            fits.append((v, eye, rotation[2], n, evidence))
        return self.track(gray, phase, t, k, station, previous)
