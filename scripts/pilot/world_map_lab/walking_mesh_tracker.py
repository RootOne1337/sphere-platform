"""Track a walking camera with short optical tracks refreshed from original mesh depth."""

import math
import threading
import time

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from scripts.pilot.route_roma_runtime import RomaProcess, Runtime
from scripts.pilot.world_map_lab.bake_world_course import renderer
from scripts.pilot.world_map_lab.live_destination_atlas import SIZE, Locator
from scripts.pilot.world_map_lab.verify_world_scene_candidates import source_observation


class WalkingMeshTracker:
    def __init__(self, config, planner):
        self.cfg, self.planner = config, planner
        focal = float(config["focalAt640"])
        self.camera = np.float64([[focal, 0, 319.5], [0, focal, 179.5], [0, 0, 1]])
        self.lock = threading.Condition()
        self.pending = self.refresh = self.track = None
        self.closed = False
        self.failed = None
        self.ready = threading.Event()
        self.last_submit = -math.inf
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def submit(self, bgr, pose):
        now = time.monotonic()
        with self.lock:
            if self.closed or self.failed or now - self.last_submit < 0.40:
                return
            self.pending = (bgr, pose, now)
            self.last_submit = now
            self.lock.notify()

    def _solve(self, points, pixels, origin):
        if len(points) < 24:
            return None
        solver = Locator.__new__(Locator)
        solver.meta = dict(source="source-map-grid", independentScenery=True)
        solver.origin = np.asarray(origin, dtype=np.float64)
        inliers = {}
        pose = solver.solve_with_camera(
            self.camera,
            (points - solver.origin).astype(np.float32),
            pixels.astype(np.float32),
            None,
            inliers=inliers,
        )
        return (pose, inliers["world"], inliers["pixels"]) if pose is not None else None

    def _worker(self):
        matcher = None
        try:
            matcher = RomaProcess(Runtime(self.cfg["gpu"], self.cfg["matcher"]))
            while matcher.status == "warming" and not self.closed:
                matcher.poll()
                time.sleep(0.02)
            if not matcher.available:
                raise RuntimeError("mesh matcher unavailable")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True, args=["--enable-gpu", "--use-angle=d3d11"]
                )
                page, fr = renderer(
                    browser, self.planner, self.cfg["folder"] / "journey/route.json", SIZE
                )
                self.ready.set()
                zoom = fr / self.camera[0, 0]
                shift = np.float32([[zoom, 0, (1 - zoom) * 479.5], [0, zoom, (1 - zoom) * 269.5]])
                while True:
                    with self.lock:
                        self.lock.wait_for(lambda: self.closed or self.pending is not None)
                        if self.closed:
                            break
                        bgr, initial, stamp = self.pending
                        self.pending = None
                    obs = source_observation(
                        page, [*initial["eye"], initial["heading"], -0.015], fr
                    )
                    if not obs:
                        continue
                    rgb, source_px, world = obs
                    query = cv2.warpAffine(
                        cv2.cvtColor(cv2.resize(bgr, (960, 540)), cv2.COLOR_BGR2RGB),
                        shift,
                        (960, 540),
                    )
                    if not matcher.submit(query, [(0, rgb, source_px)]):
                        raise RuntimeError("lost mesh matcher")
                    result = None
                    while matcher.status == "matching":
                        result = matcher.poll()
                        if result is None:
                            time.sleep(0.003)
                    if result is None:
                        raise RuntimeError("lost mesh correspondence reply")
                    ids, xy = result[0]
                    ids = np.asarray(ids)
                    xy = np.asarray(xy)
                    valid = (ids >= 0) & (ids < len(world)) & np.isfinite(xy).all(axis=1)
                    ids, xy = ids[valid], xy[valid]
                    _, unique = np.unique(ids, return_index=True)
                    ids, xy = ids[unique], xy[unique]
                    xy = ((xy - [479.5, 269.5]) / zoom + [479.5, 269.5] + 0.5) / 1.5 - 0.5
                    _, idx = np.unique(np.floor(xy / 6).astype(int), axis=0, return_index=True)
                    solved = self._solve(world[ids[idx]], xy[idx], initial["eye"])
                    if not solved:
                        continue
                    pose, xyz, uv = solved
                    if (
                        math.dist(pose["eye"], initial["eye"]) > 8
                        or math.cos(pose["heading"] - initial["heading"]) < 0.7
                    ):
                        continue
                    gray = cv2.cvtColor(
                        cv2.resize(bgr, SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY
                    )
                    with self.lock:
                        self.refresh = (gray, xyz, uv, pose, stamp, stamp)
                browser.close()
        except Exception as error:
            self.failed = repr(error)
        finally:
            if matcher:
                matcher.close()
            self.ready.set()

    def locate(self, bgr):
        gray = cv2.cvtColor(cv2.resize(bgr, SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        now = time.monotonic()
        with self.lock:
            fresh = self.refresh
            self.refresh = None
        for sample in (fresh, self.track):
            if sample is None:
                continue
            old, xyz, uv, prior, stamp, baked = sample
            if now - stamp > 2 or now - baked > 5:
                continue
            moved, valid, _ = cv2.calcOpticalFlowPyrLK(
                old, gray, uv, None, winSize=(21, 21), maxLevel=3
            )
            if moved is None:
                continue
            back, again, _ = cv2.calcOpticalFlowPyrLK(
                gray, old, moved, None, winSize=(21, 21), maxLevel=3
            )
            if back is None or again is None:
                continue
            keep = (
                valid.ravel().astype(bool)
                & again.ravel().astype(bool)
                & (np.linalg.norm(back - uv, axis=1) < 0.85)
            )
            solved = self._solve(xyz[keep], moved[keep], prior["eye"])
            if not solved:
                continue
            pose, xyz, uv = solved
            if math.dist(pose["eye"], prior["eye"]) > 0.9 + 8 * (now - stamp):
                continue
            self.track = (gray, xyz, uv, pose, now, baked)
            return pose
        return None

    def close(self):
        with self.lock:
            self.closed = True
            self.lock.notify_all()
        self.thread.join(timeout=5)
