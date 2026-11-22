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


class WalkingYawHint:
    """Predict the next reference angle from RGB without publishing a map pose."""

    def __init__(self, focal):
        width, height = 192, 80
        extent = min(0.82, math.atan(313 / focal))
        slope = np.tan(np.linspace(-extent, extent, width, dtype=np.float32))
        vertical = min(0.32, 171 / (focal * math.sqrt(1 + float(slope[-1]) ** 2)))
        rows = np.linspace(-vertical, vertical, height, dtype=np.float32)
        self.x = np.broadcast_to(319.5 + focal * slope, (height, width)).copy()
        self.y = (179.5 + focal * rows[:, None] * np.sqrt(1 + slope[None, :] ** 2)).astype(
            np.float32
        )
        self.window = cv2.createHanningWindow((width, height), cv2.CV_32F)
        self.step = 2 * extent / (width - 1)
        self.reset()

    def reset(self):
        self.previous = self.heading = None
        self.timestamp = self.confirmed_at = -math.inf

    def confirm(self, heading, now):
        self.heading, self.confirmed_at = heading, now

    def observe(self, gray, now, verified_heading=None):
        strip = cv2.remap(gray, self.x, self.y, cv2.INTER_LINEAR).astype(np.float32)
        if verified_heading is not None:
            self.confirm(verified_heading, now)
        elif (
            self.heading is not None
            and self.previous is not None
            and 0 < now - self.timestamp <= 0.45
            and now - self.confirmed_at <= 2.5
        ):
            (dx, dy), score = cv2.phaseCorrelate(self.previous, strip, self.window)
            yaw = dx * self.step
            self.heading = (
                math.remainder(self.heading + yaw, math.tau)
                if score >= 0.32 and abs(dy) <= 5 and abs(yaw) <= 0.48
                else None
            )
        else:
            self.heading = None
        self.previous, self.timestamp = strip, now


def projected_turn(pixels, camera, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return cv2.perspectiveTransform(
        pixels.reshape(-1, 1, 2), camera @ rotation @ np.linalg.inv(camera)
    ).reshape(-1, 2)


class WalkingMeshTracker:
    def __init__(self, config, planner):
        self.cfg, self.planner = config, planner
        focal = float(config["focalAt640"])
        self.camera = np.float64([[focal, 0, 319.5], [0, focal, 179.5], [0, 0, 1]])
        self.yaw_hint = WalkingYawHint(focal)
        self.lock = threading.Condition()
        self.pending = self.refresh = self.track = None
        self.closed = False
        self.failed = None
        self.attempts = 0
        self.observation = None
        self.ready = threading.Event()
        self.last_submit = -math.inf
        self.invalid_before = -math.inf
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

    def invalidate(self):
        """Drop tracks and any outstanding match belonging to the previous scene."""
        with self.lock:
            self.invalid_before = time.monotonic()
            self.track = self.refresh = self.pending = None
            self.yaw_hint.reset()

    def _solve(self, points, pixels, origin, *, verified_tracks=False):
        if len(points) < 24:
            return None
        solver = Locator.__new__(Locator)
        solver.meta = (
            {} if verified_tracks else dict(source="source-map-grid", independentScenery=True)
        )
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
                        page,
                        [*initial["eye"], initial["heading"], initial.get("pitch", -0.015)],
                        fr,
                    )
                    if not obs:
                        with self.lock:
                            self.attempts += 1
                            self.observation = {"supports": 0, "yaw": initial["heading"]}
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
                    with self.lock:
                        self.attempts += 1
                        self.observation = {
                            "supports": 0 if not solved else solved[0]["supports"],
                            "yaw": initial["heading"],
                            "matches": len(idx),
                            "ms": round(1000 * (time.monotonic() - stamp)),
                        }
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
                        if stamp > self.invalid_before:
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
        self.yaw_hint.observe(gray, now)
        heading = self.yaw_hint.heading
        with self.lock:
            fresh = self.refresh
            self.refresh = None
        for sample in (fresh, self.track):
            if sample is None:
                continue
            old, xyz, uv, prior, stamp, baked = sample
            if now - stamp > 2 or now - baked > 5:
                continue
            turn = (
                math.remainder(heading - prior["heading"], math.tau) if heading is not None else 0
            )
            compensate = 0.035 <= abs(turn) <= 0.60
            flags = cv2.OPTFLOW_USE_INITIAL_FLOW if compensate else 0
            guess = projected_turn(uv, self.camera, turn) if compensate else None
            moved, valid, _ = cv2.calcOpticalFlowPyrLK(
                old, gray, uv, guess, winSize=(21, 21), maxLevel=3, flags=flags
            )
            if moved is None:
                continue
            guess = projected_turn(moved, self.camera, -turn) if compensate else None
            back, again, _ = cv2.calcOpticalFlowPyrLK(
                gray, old, moved, guess, winSize=(21, 21), maxLevel=3, flags=flags
            )
            if back is None or again is None:
                continue
            keep = (
                valid.ravel().astype(bool)
                & again.ravel().astype(bool)
                & (np.linalg.norm(back - uv, axis=1) < 0.85)
            )
            solved = self._solve(xyz[keep], moved[keep], prior["eye"])
            # A freshly verified multi-surface view can temporarily reduce to its
            # tracked facade. These are the same world points tracked both ways.
            # Bound this exception to a short interval from the original refresh.
            if not solved and now - baked < 1.25 and np.count_nonzero(keep) >= 60:
                solved = self._solve(xyz[keep], moved[keep], prior["eye"], verified_tracks=True)
                if solved and (
                    solved[0]["supports"] < 45
                    or math.dist(solved[0]["eye"], prior["eye"]) > 0.60
                    or min(
                        abs(math.remainder(solved[0]["heading"] - prior["heading"], math.tau)),
                        abs(math.remainder(solved[0]["heading"] - heading, math.tau))
                        if compensate and abs(turn) <= 0.30
                        else math.inf,
                    )
                    > 0.072
                ):
                    solved = None
            if not solved:
                continue
            pose, xyz, uv = solved
            if math.dist(pose["eye"], prior["eye"]) > 0.9 + 8 * (now - stamp):
                continue
            self.track = (gray, xyz, uv, pose, now, baked)
            self.yaw_hint.confirm(pose["heading"], now)
            return pose
        return None

    def heading_suggestion(self):
        return self.yaw_hint.heading

    def close(self):
        with self.lock:
            self.closed = True
            self.lock.notify_all()
        self.thread.join(timeout=5)
