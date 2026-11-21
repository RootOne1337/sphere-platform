"""Register an RGB landmark map to road coordinates and localize a HUD-free game frame."""

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

from scripts.pilot.world_map_lab.export_full_game_world import digest

SIZE = (640, 360)


def similarity(a, b):
    x, y = a - a.mean(0), b - b.mean(0)
    u, singular, v = np.linalg.svd(x.T @ y)
    signs = np.array([1.0, 1.0, np.linalg.det(u @ v)])
    rotation = (u * signs) @ v
    scale = (singular * signs).sum() / (x * x).sum()
    return scale, rotation, b.mean(0) - scale * a.mean(0) @ rotation


def registration(geometry, observations):
    cameras = geometry["cameras"]
    ts = np.array([c["ticks_90k"] / 90000 for c in cameras])
    centers = np.array([c["center"] for c in cameras])
    rows = [r for r in observations["rows"] if r.get("xyz") and ts[0] <= r["capture_s"] <= ts[-1]]
    a = np.array([[np.interp(r["capture_s"], ts, column) for column in centers.T] for r in rows])
    b = np.array([r["xyz"] for r in rows])
    if len(rows) < 24 or np.any(np.diff(ts) <= 0):
        raise ValueError("insufficient registered camera pairs")
    train = np.arange(len(rows)) % 3 != 0
    pool = np.flatnonzero(train)
    best = np.zeros(len(rows), bool)
    rng = np.random.default_rng(0)
    for _ in range(1500):
        ids = rng.choice(pool, 3, replace=False)
        if np.linalg.norm(np.cross(a[ids[1]] - a[ids[0]], a[ids[2]] - a[ids[0]])) < 0.005:
            continue
        scale, rot, offset = similarity(a[ids], b[ids])
        good = train & (np.linalg.norm(scale * a @ rot + offset - b, axis=1) < 1.0)
        if good.sum() > best.sum():
            best = good
    if (
        best.sum() < 0.75 * train.sum()
        or np.linalg.svd(a[best] - a[best].mean(0), compute_uv=False)[1] < 0.5
    ):
        raise ValueError("map anchors are insufficient or collinear")
    scale, rot, offset = similarity(a[best], b[best])
    error = np.linalg.norm(scale * a[~train] @ rot + offset - b[~train], axis=1)
    if np.percentile(error, 95) > 2.5:
        raise ValueError("registration disagreement on unused anchors")
    return (
        scale,
        rot,
        offset,
        dict(
            pairs=len(rows),
            heldout=len(error),
            p50=float(np.median(error)),
            p95=float(np.percentile(error, 95)),
        ),
    )


def features(gray, detector):
    keys, desc = detector.detectAndCompute(
        cv2.resize(gray, SIZE, interpolation=cv2.INTER_AREA), None
    )
    if desc is None:
        return np.empty((0, 2), np.float32), np.empty((0, 128), np.float32)
    return np.array([k.pt for k in keys], np.float32), np.sqrt(
        desc / np.maximum(desc.sum(1, keepdims=True), 1.0)
    )


def build(route_dir, geometry_path, observations_path, recording, revision, output):
    route = json.loads((route_dir / "route.json").read_bytes())
    geometry = json.loads(geometry_path.read_bytes())
    observations = json.loads(observations_path.read_bytes())
    cache = route_dir / route["cache_file"]
    if digest(cache) != route["cache_sha256"] or digest(recording) != observations["videoSha256"]:
        raise ValueError("recording or landmark cache differs from registration inputs")
    if geometry["source_manifest_sha256"] != digest(recording.with_name("manifest.json")):
        raise ValueError("recording manifest differs from camera reconstruction")
    cameras = geometry["cameras"]
    if route["reference_names"] != [c["image"] for c in cameras] or not np.allclose(
        route["camera_trace"], [c["center"] for c in cameras], atol=1e-6, rtol=0
    ):
        raise ValueError("camera geometry differs from indexed observations")
    scale, rot, offset, report = registration(geometry, observations)
    views, view_ids, tracked_pixels, tracked_world = [], [], [], []
    track_offsets = [0]
    packed = []
    points = []
    detector = cv2.SIFT_create(nfeatures=2000, contrastThreshold=0.018)
    with np.load(cache, allow_pickle=False) as data:
        grays, offsets, pixels, xyz = (data[n] for n in ("grays", "offsets", "pixels", "xyz"))
    h, w = grays.shape[1:]
    resize = np.array(SIZE) / [w, h]
    for i in range(0, len(grays), 2):
        start, end = offsets[i : i + 2]
        if end - start < 12:
            continue
        uv, desc = features(grays[i], detector)
        dist, idx = cKDTree((pixels[start:end] + 0.5) * resize - 0.5).query(uv)
        keep = dist < 1.6
        if keep.any():
            points.append((scale * xyz[start:end][idx[keep]] @ rot + offset).astype(np.float32))
            packed.append(desc[keep])
            view_ids.append(np.full(keep.sum(), len(views), dtype=np.int16))
            views.append(cv2.resize(grays[i], SIZE, interpolation=cv2.INTER_AREA))
            ref_pixels = ((pixels[start:end] + 0.5) * resize - 0.5).astype(np.float32)
            # Select distributed observations, bounding the per-candidate flow cost.
            _, sample = np.unique(np.floor(ref_pixels / 10).astype(int), axis=0, return_index=True)
            tracked_pixels.append(ref_pixels[sample])
            tracked_world.append((scale * xyz[start:end][sample] @ rot + offset).astype(np.float32))
            track_offsets.append(track_offsets[-1] + len(sample))
    desc = np.concatenate(packed)
    world = np.concatenate(points)
    intr = np.array(route["intrinsics"], float)
    intr[:2] *= resize
    intr[2:] = (intr[2:] + 0.5) * resize - 0.5
    trace = scale * np.array([camera["center"] for camera in cameras]) @ rot + offset
    meta = dict(
        visualTrace=trace.round(3).tolist(),
        coverageRadius=8.0,
        revision=revision,
        source=digest(recording),
        geometry=digest(geometry_path),
        registration=report,
        landmarks=len(world),
        trainingViews=len(grays[::2]),
        width=SIZE[0],
        height=SIZE[1],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.with_suffix(".partial").open("wb") as f:
        np.savez_compressed(
            f,
            desc=desc,
            xyz=world,
            intrinsics=intr,
            meta=json.dumps(meta),
            views=np.stack(views),
            viewIds=np.concatenate(view_ids),
            trackOffsets=track_offsets,
            trackPixels=np.concatenate(tracked_pixels),
            trackXYZ=np.concatenate(tracked_world),
        )
    output.with_suffix(".partial").replace(output)
    return meta


def distributed_surface_support(world, pixels):
    """Reject a cold fix explained by just one repeated wall or road surface."""
    rng = np.random.default_rng(42)
    a, b, c = world[rng.integers(len(world), size=(96, 3))].transpose(1, 0, 2)
    normals = np.cross(b - a, c - a)
    lengths = np.linalg.norm(normals, axis=1)
    usable = lengths > 0.01
    if not usable.any():
        return False
    normals = normals[usable] / lengths[usable, None]
    distances = np.abs(normals @ world.T - np.sum(normals * a[usable], axis=1)[:, None])
    dominant = np.argmax((distances < 0.7).sum(1))
    # Six off-plane matches can constrain another pose independently. A tiny
    # cluster at one window edge is insufficient to resolve repeated facades.
    others = pixels[distances[dominant] > 0.7]
    return len(others) >= 6 and len(np.unique((others // 64).astype(int), axis=0)) >= 3


class Locator:
    def __init__(self, path, revision):
        with np.load(path, allow_pickle=False) as bank:
            self.meta = json.loads(str(bank["meta"]))
            if self.meta["revision"] != revision:
                raise ValueError("visual and road map revisions differ")
            self.trace = np.array(self.meta["visualTrace"])
            self.world = bank["xyz"]
            self.views = bank["views"]
            self.view_ids = bank["viewIds"]
            self.track_offsets = bank["trackOffsets"]
            self.track_pixels = bank["trackPixels"]
            self.track_xyz = bank["trackXYZ"]
            fx, fy, cx, cy = bank["intrinsics"]
            self.k = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
            self.matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=48))
            self.matcher.add([bank["desc"]])
            self.matcher.train()
        self.detector = cv2.SIFT_create(nfeatures=1600, contrastThreshold=0.018)
        self.origin = self.world.mean(0, dtype=np.float64)
        self.track_xyz = np.asarray(self.track_xyz - self.origin, dtype=np.float32)
        self.relative = np.asarray(self.world - self.origin, dtype=np.float32)

    def covers(self, path):
        # Sample full segments, including long shortcuts between two mapped endpoints.
        # Use height as well as horizontal distance so stacked roads do not share coverage.
        path = np.asarray(path, float)
        for a, b in zip(path, np.vstack((path[1:], path[-1]))):
            samples = np.linspace(a, b, max(2, math.ceil(np.linalg.norm(b - a) / 2) + 1))
            delta = self.trace[None, :, :] - samples[:, None, :]
            nearby = (np.linalg.norm(delta[:, :, :2], axis=2) <= self.meta["coverageRadius"]) & (
                np.abs(delta[:, :, 2] - 1.45) <= 2.0
            )
            if not nearby.any(axis=1).all():
                return False
        return True

    def describe(self, gray):
        h, w = gray.shape
        if not h or abs(w / h - SIZE[0] / SIZE[1]) > 0.01:
            return None
        return features(gray, self.detector)

    def locate(self, gray):
        observed = self.describe(gray)
        return self.locate_features(gray, *observed) if observed is not None else None

    def locate_features(self, gray, uv, desc):
        if len(uv) < 24:
            return None
        matches = self.matcher.knnMatch(desc, k=8)
        picked = {}
        for row in matches:
            top = row[0]
            p = self.relative[top.trainIdx]
            rival = next(
                (r for r in row[1:] if np.max(np.abs(p - self.relative[r.trainIdx])) > 0.35), None
            )
            if rival is None or top.distance >= 0.77 * rival.distance:
                continue
            cell = tuple(np.rint(p * 5).astype(int))
            if cell not in picked or picked[cell].distance > top.distance:
                picked[cell] = top
        if len(picked) < 10:
            return None
        obj = np.array([self.relative[m.trainIdx] for m in picked.values()])
        px = np.array([uv[m.queryIdx] for m in picked.values()])
        if len(obj) >= 26:
            result = self.solve(obj, px)
            if result:
                return result
        votes = np.bincount(
            [self.view_ids[m.trainIdx] for m in picked.values()], minlength=len(self.views)
        )
        votes = np.convolve(votes, [1, 2, 1], mode="same")
        gray = cv2.resize(gray, SIZE, interpolation=cv2.INTER_AREA)
        for view in np.argsort(votes)[-4:][::-1]:
            if votes[view] < 6:
                break
            start, end = self.track_offsets[view : view + 2]
            ref = self.track_pixels[start:end]
            opts = dict(winSize=(21, 21), maxLevel=3)
            nxt, ok, _ = cv2.calcOpticalFlowPyrLK(self.views[view], gray, ref, None, **opts)
            back, again, _ = cv2.calcOpticalFlowPyrLK(gray, self.views[view], nxt, None, **opts)
            keep = (
                ok.ravel().astype(bool)
                & again.ravel().astype(bool)
                & (np.linalg.norm(back - ref, axis=1) < 0.7)
            )
            if keep.sum() < 36:
                continue
            # Optical flow alone can lock onto a repeated facade. Require independent
            # descriptor matches in this live image to reproject into the same pose.
            result = self.solve(self.track_xyz[start:end][keep], nxt[keep], (obj, px))
            if result:
                return result
        return None

    def configure_search_lenses(self, stream_camera, hfovs):
        """Set known capture and renderer lenses for passive source-map search."""
        cameras = [self.k]
        lenses = [stream_camera.copy()]
        for hfov in hfovs:
            if not math.isfinite(hfov) or not 0 < hfov < 180:
                raise ValueError("invalid horizontal camera field of view")
            camera = stream_camera.copy()
            camera[0, 0] = camera[1, 1] = SIZE[0] / (2 * math.tan(math.radians(hfov) / 2))
            cameras.append(camera)
        for camera in cameras:
            if not any(np.allclose(camera, current) for current in lenses):
                lenses.append(camera)
        self.search_lenses = lenses

    def solve(self, obj, px, descriptor_check=None):
        cameras = getattr(self, "search_lenses", None)
        if not cameras:
            return self.solve_with_camera(self.k, obj, px, descriptor_check)
        solutions = []
        for camera in cameras:
            pose = self.solve_with_camera(camera, obj, px, descriptor_check)
            if pose is None:
                continue
            for other in solutions:
                if (
                    math.dist(other["eye"], pose["eye"]) > 1.0
                    or math.cos(other["heading"] - pose["heading"]) < 0.9925
                ):
                    return None
            solutions.append(pose)
        return max(solutions, key=lambda p: p["supports"], default=None)

    def solve_with_camera(self, camera, obj, px, descriptor_check):
        ok, r, t, idx = cv2.solvePnPRansac(
            obj,
            px,
            camera,
            None,
            iterationsCount=450,
            reprojectionError=2.6,
            confidence=0.999,
            flags=cv2.SOLVEPNP_AP3P,
        )
        if not ok or idx is None or len(idx) < 24 or len(idx) < 0.30 * len(obj):
            return None
        obj, px = obj[idx.ravel()], px[idx.ravel()]
        if self.meta.get("source") == "source-map-grid" and not distributed_surface_support(
            obj, px
        ):
            return None
        if cv2.contourArea(cv2.convexHull(px)) < 0.05 * math.prod(SIZE):
            return None
        r, t = cv2.solvePnPRefineLM(obj, px, camera, None, r, t)
        R = cv2.Rodrigues(r)[0]
        # In the map Z is up and the image y-axis is down. An upside-down frame
        # can have excellent descriptor matches but reverses the steering convention.
        if R[1, 2] > -0.65 or abs(R[2, 2]) > 0.65:
            return None
        eye = -R.T @ t[:, 0]
        if self.meta.get("independentScenery"):
            depth = (obj - eye) @ R[2]
            # Two walls on one nearby kiosk can constrain a precise but wrong pose.
            # Verify street context beyond that object before accepting a cold fix.
            background = px[depth > max(10.0, np.percentile(depth, 15) + 4.0)]
            if len(background) < 6 or len(np.unique((background // 64).astype(int), axis=0)) < 3:
                return None
        reproj = cv2.projectPoints(obj, r, t, camera, None)[0][:, 0]
        if (
            np.median(np.linalg.norm(reproj - px, axis=1)) > 1.7
            or np.mean(obj @ R[2] + t[2, 0] > 0) < 0.98
        ):
            return None
        if descriptor_check is not None:
            verify_points, verify_px = descriptor_check
            projected = cv2.projectPoints(verify_points, r, t, camera, None)[0][:, 0]
            supported = (np.linalg.norm(projected - verify_px, axis=1) < 3.0) & (
                (verify_points @ R[2] + t[2, 0]) > 0
            )
            if supported.sum() < max(18, 0.20 * len(verify_points)) or cv2.contourArea(
                cv2.convexHull(verify_px[supported])
            ) < 0.015 * math.prod(SIZE):
                return None
            ok, vr, vt = cv2.solvePnP(
                verify_points[supported],
                verify_px[supported],
                camera,
                None,
                flags=cv2.SOLVEPNP_SQPNP,
            )
            if not ok:
                return None
            verified_rotation = cv2.Rodrigues(vr)[0]
            if (
                np.linalg.norm(-verified_rotation.T @ vt[:, 0] - eye) > 0.65
                or verified_rotation[2] @ R[2] < 0.9985
            ):
                return None
        pattern = (px[:, 0] // 64 + px[:, 1] // 48) % 2 == 0
        for mask in (pattern, ~pattern):
            if mask.sum() < 8:
                return None
            ok, rr, tt = cv2.solvePnP(obj[mask], px[mask], camera, None, flags=cv2.SOLVEPNP_SQPNP)
            if not ok:
                return None
            q = cv2.Rodrigues(rr)[0]
            if np.linalg.norm(-q.T @ tt[:, 0] - eye) > 0.72 or q[2] @ R[2] < 0.998:
                return None
        return dict(
            eye=(eye + self.origin).tolist(),
            heading=math.atan2(R[2, 1], R[2, 0]),
            supports=len(obj),
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("route_dir", "geometry_path", "observations_path", "recording", "output"):
        p.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    p.add_argument("--revision", required=True)
    cv2.setNumThreads(3)
    print(json.dumps(build(**vars(p.parse_args()))))
