"""Localize native game pixels along an arbitrary baked walk–Faggio–walk route."""

import argparse
import hashlib
import json
import math
import time
import zlib
from collections import deque
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from scripts.pilot.world_map_lab.check_journey_rgb import H, Lane, W, angle, correct
from scripts.pilot.world_map_lab.classic_lens import stationary_focal
from scripts.pilot.world_map_lab.classic_transfers import MixedJourney
from scripts.pilot.world_map_lab.classic_window import drive_window
from scripts.pilot.world_map_lab.export_full_game_world import digest
from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks
from scripts.pilot.world_map_lab.native_route import native_route
from scripts.pilot.world_map_lab.neighborhood_search import NeighborhoodSearch


class RootDescriptors:
    """Decode only descriptors requested for a local index or coarse retrieval."""

    def __init__(self, path, count):
        self.raw = np.memmap(path, mode="r", dtype=np.uint8, shape=(count, 128))

    def __getitem__(self, selection):
        a = self.raw[selection].astype(np.float32)
        return np.sqrt(a / np.maximum(1, a.sum(axis=-1, keepdims=True)))


class WorldCoursePilot:
    def __init__(self, route, bank, hfov=None):
        paths, _, self.route_hash = native_route(route)
        config = json.loads(route.read_bytes())
        meta = json.loads((bank / "index.json").read_bytes())
        if meta["routeSha256"] != self.route_hash or meta["worldRevision"] != config["revision"]:
            raise ValueError("world reference views differ from the chosen route")
        for name in ("xyz.f32", "sift.u8"):
            if digest(bank / name) != meta["files"][name]:
                raise ValueError("landmark payload checksum mismatch")
        self.size = w, h = tuple(meta["size"])
        if hfov is not None and not 40 <= hfov <= 150:
            raise ValueError("invalid horizontal field of view")
        self.hfov = hfov
        f = w / (2 * math.tan(math.radians(hfov) / 2)) if hfov else meta["focal"]
        self.K = np.array([[f, 0, (w - 1) / 2], [0, f, (h - 1) / 2], [0, 0, 1]], float)
        self.image_views = [[] for _ in paths]
        for view in meta.get("imageViews", []):
            self.image_views[view["phase"]].append(view)
        self.packed = None
        if any(self.image_views):
            if digest(bank / "images.z") != meta["files"]["images.z"]:
                raise ValueError("RGB-D reference checksum mismatch")
            self.packed = np.memmap(bank / "images.z", mode="r", dtype=np.uint8)
        yy, xx = np.indices((H, W))
        self.validation_cells = (xx // 40 + yy // 32) % 2 == 0
        self.map_focal = meta["focal"] * W / w
        origin = np.array(meta["origin"])
        xyz = np.memmap(bank / "xyz.f32", dtype="<f4", mode="r", shape=(meta["count"], 3))
        descriptors = RootDescriptors(bank / "sift.u8", meta["count"])
        self.lanes = [Lane(leg) for leg in config["legs"]]
        self.journey = MixedJourney(paths)
        self.indices = []
        self.retrieval = []
        for i, lane in enumerate(self.lanes):

            def project(camera, lane=lane):
                ground = camera + origin - [0, 0, 1.5]
                u = np.clip(
                    np.einsum("ij,ij->i", ground - lane.path[:-1], lane.vectors) / lane.ds**2, 0, 1
                )
                errors = np.linalg.norm(lane.path[:-1] + lane.vectors * u[:, None] - ground, axis=1)
                j = int(np.argmin(errors))
                return float(lane.arc[j] + u[j] * lane.ds[j]), float(errors[j])

            view = [v for v in meta["views"] if v["phase"] == i]
            if not view:
                raise ValueError("journey leg has no reference views")
            index = IndexedLandmarks(
                SimpleNamespace(
                    W=w,
                    H=h,
                    K=self.K,
                    xyz=xyz,
                    desc=descriptors,
                    origin=origin,
                    views=view,
                    locate_progress=project,
                ),
                cache_tiles=5,
            )
            self.indices.append(index)
            self.retrieval.append(NeighborhoodSearch([(index, 32)]))
        self.stations, self.caps = self.lanes[1].curve_limits()
        self.confirmed = None
        self.phase_index = None
        self.samples = deque()
        self.misses = 0

    @lru_cache(maxsize=24)
    def reference_image(self, start, size):
        raw = zlib.decompress(self.packed[start : start + size])
        if len(raw) != 3 * W * H:
            raise ValueError("invalid RGB-D keyframe")
        return (
            np.frombuffer(raw[: W * H], np.uint8).reshape(H, W),
            np.frombuffer(raw[W * H :], "<u2").reshape(H, W),
        )

    def dense_fit(self, rgb, phase, prior, previous):
        if self.packed is None or self.hfov is None:
            return None
        lane = self.lanes[phase]
        tangent = lane.at(prior + 1) - lane.at(prior - 1)
        yaw = math.atan2(tangent[1], tangent[0])
        if previous and previous[1][1] is not None:
            head = previous[1][1][2]
            yaw = math.atan2(head[1], head[0])
        candidates = [
            v
            for v in self.image_views[phase]
            if abs(v["s"] - prior) <= 10 and abs(angle(v["pose"][3] - yaw)) < 0.80
        ]
        candidates.sort(key=lambda v: abs(v["s"] - prior) + 7 * abs(angle(v["pose"][3] - yaw)))
        live = cv2.resize(
            cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (W, H), interpolation=cv2.INTER_AREA
        )
        # Resample the incoming pixels into the map camera's intrinsic frame.
        scale = self.map_focal / (self.K[0, 0] * W / self.size[0])
        if abs(scale - 1) > 0.001:
            live = cv2.warpAffine(
                live,
                np.array(
                    [[scale, 0, (W - 1) / 2 * (1 - scale)], [0, scale, (H - 1) / 2 * (1 - scale)]]
                ),
                (W, H),
            )
        if live.std() < 3:
            return None
        estimates = []
        single_views = []
        project = self.indices[phase].atlas.locate_progress
        origin = self.indices[phase].atlas.origin
        for v in candidates[:6]:
            ref, depth = self.reference_image(*v["bytes"])
            result = correct(v["pose"], (ref, depth, live), self.map_focal, sparse_scene=True)
            if result is None:
                continue
            eye, heading, count = result
            station, cross = project(eye - origin)
            if cross > 2.2 or abs(station - prior) > 8:
                continue
            for old_eye, old_heading, other, old_s in estimates:
                if abs(v["s"] - old_s) < 0.75:
                    continue
                if (
                    np.linalg.norm(eye - old_eye) < 0.45
                    and abs(angle(heading - old_heading)) < 0.035
                ):
                    head = np.array([math.cos(heading), math.sin(heading), 0])
                    rotation = np.array([[head[1], -head[0], 0], [0, 0, -1], head])
                    return eye, rotation, station, min(count, other), None
            estimates.append((eye, heading, count, v["s"]))
            if count >= 18:
                single_views.append((count, v, ref, depth, eye, heading, station))
        # The second nearest reference can be across a corner or occlusion. In that
        # case demand two independent pose solves in complementary regions of one image.
        for count, v, ref, depth, eye, heading, station in sorted(
            single_views, key=lambda item: -item[0]
        )[:2]:
            for mask in (self.validation_cells, ~self.validation_cells):
                independent = correct(
                    v["pose"],
                    (ref, np.where(mask, depth, 0), live),
                    self.map_focal,
                    sparse_scene=True,
                )
                if independent is None:
                    break
                pos, yaw, n = independent
                if n < 12 or np.linalg.norm(pos - eye) > 0.24 or abs(angle(yaw - heading)) > 0.018:
                    break
            else:
                head = np.array([math.cos(heading), math.sin(heading), 0])
                rotation = np.array([[head[1], -head[0], 0], [0, 0, -1], head])
                return eye, rotation, station, count, None
        return None

    def locate(self, raw, t, phase):
        index = self.indices[phase]
        lane = self.lanes[phase]
        w, h = self.size
        if abs(raw.shape[1] / raw.shape[0] - w / h) > 0.004:
            raise ValueError("game viewport aspect differs from the reference")
        rgb = cv2.resize(raw, (w, h), interpolation=cv2.INTER_AREA)
        previous = self.confirmed
        prior = previous[1][2] if previous else 0.0
        if previous:
            fit = self.dense_fit(rgb, phase, prior, previous)
            dt = t - previous[0]
            if (
                fit is not None
                and 0 < dt
                and np.linalg.norm(fit[0] - previous[1][0])
                <= 1.1 + (24 if phase == 1 else 5) * min(dt, 2.0)
            ):
                self.method = "rgbd-verified"
                return fit
        feat = index.features(rgb)
        if feat is None:
            return None
        tiles = [int(prior // 12)]
        # Local neighbors first. Use visual retrieval when the expected cell has gone missing.
        if previous:
            tiles.append(tiles[0] + (1 if self.misses % 2 == 0 else -1))
        if self.misses or previous is None:
            tiles.extend(int(s // 12) for s in self.retrieval[phase].suggest(feat, limit=2))
        for tile in dict.fromkeys(tiles):
            if tile < 0 or tile > lane.arc[-1] // 12:
                continue
            lo = tile * 12
            hi = min(lane.arc[-1] + 0.01, lo + 12)
            # Use the centre of the complete tile for index selection, including at the far end.
            fit = index.match(feat, lo, hi, require_corridor=True)
            learned = None
            if self.hfov is None:
                if index.putatives is None:
                    continue
                learned = stationary_focal(*index.putatives, w, h)
                if learned is None:
                    continue
                old_focal = self.K[0, 0]
                self.K[0, 0] = self.K[1, 1] = w / (2 * math.tan(math.radians(learned) / 2))
                fit = index.match(feat, lo, hi, require_corridor=True)
                self.K[0, 0] = self.K[1, 1] = old_focal
            if fit is None:
                continue
            if previous:
                dt = t - previous[0]
                max_speed = 24 if phase == 1 else 5
                if dt <= 0 or np.linalg.norm(fit[0] - previous[1][0]) > 1.1 + max_speed * min(
                    dt, 2.0
                ):
                    continue
            elif fit[2] > 6.0:
                # This scenario starts on foot and observes both transfers at their true ends.
                continue
            if learned is not None:
                self.hfov = learned
                self.K[0, 0] = self.K[1, 1] = w / (2 * math.tan(math.radians(learned) / 2))
            self.method = "rootsift-pnp"
            return fit
        return None

    def frame(self, raw, t, capture_started):
        stage = self.journey.stage
        phase = 0 if stage in ("approach", "boarding") else (1 if stage == "drive" else 2)
        if phase != self.phase_index:
            self.phase_index = phase
            self.confirmed = None
            self.samples.clear()
            self.misses = 0
        fit = self.locate(raw, t, phase)
        latency = (time.monotonic() - capture_started) * 1000
        row = dict(
            capture_s=t,
            latency_ms=latency,
            vision="matched" if fit else "lost",
            supports=fit[3] if fit else 0,
            station=fit[2] if fit else None,
            measured_xyz=fit[0].tolist() if fit else None,
            pedal="coast",
            steering=0.0,
            terminal_brake=False,
            phase="waiting",
            visual_pace=None,
            hfov=self.hfov,
            method=self.method if fit is not None else None,
            drive_enabled=False,
        )
        row["source_rgb_sha256"] = hashlib.sha256(np.ascontiguousarray(raw)).hexdigest()
        row["latency_ms"] = latency = (time.monotonic() - capture_started) * 1000
        if fit is None or latency >= 250:
            self.misses += 1
            self.samples.clear()
            self.journey.step(row, None, lambda: None)
            return row
        self.confirmed = (t, fit)
        self.misses = 0
        if self.samples and t - self.samples[-1][0] > 0.50:
            self.samples.clear()
        self.samples.append((t, fit[0]))
        while self.samples and t - self.samples[0][0] > 0.75:
            self.samples.popleft()
        if phase == 1 and len(self.samples) >= 3 and t - self.samples[0][0] >= 0.25:
            times = np.array([tt for tt, _ in self.samples])
            times -= times.mean()
            centers = np.stack([pos for _, pos in self.samples])
            speed = float(np.linalg.norm(times @ (centers - centers[-1]) / (times @ times)))
            lane = self.lanes[1]
            s = fit[2]
            gap = lane.arc[-1] - s
            look = min(8.0, 2.5 + speed * 0.4)
            delta = lane.at(s + look) - fit[0]
            head = fit[1][2]
            yaw = angle(math.atan2(delta[1], delta[0]) - math.atan2(head[1], head[0]))
            target = min(
                13.0,
                float(np.interp(s + 0.35, self.stations, self.caps)),
                3 / max(0.08, abs(yaw)),
                math.sqrt(8 * max(0, gap - 0.35)),
            )
            row.update(
                visual_pace=speed,
                target_pace=target,
                phase="following",
                pedal="throttle"
                if speed < target - 0.55
                else ("brake" if speed > target + 0.65 else "coast"),
                steering=float(np.clip(-yaw * 0.65, -0.35, 0.35)),
            )
            if gap < 1.3:
                row.update(
                    terminal_brake=True,
                    pedal="brake",
                    steering=0.0,
                    phase="arrived" if speed < 0.45 else "following",
                )
        self.journey.step(row, fit, self.samples.clear)
        row["drive_enabled"] = stage == "drive" and self.journey.stage == "drive"
        return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "bank", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--hfov", type=float)
    parser.add_argument("--actuate", action="store_true")
    args = parser.parse_args()
    pilot = WorldCoursePilot(args.game / "sphere-route.json", args.bank, args.hfov)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "inputs.json").write_text(
        json.dumps(
            dict(
                mode="native",
                routeSha256=pilot.route_hash,
                worldReceiptSha256=digest(args.game / "sphere-full-world.json"),
                atlasSha256=digest(args.bank / "index.json"),
                actuation=args.actuate,
                policySha256=digest(Path(__file__)),
                camera="game-client-window",
            ),
            indent=2,
        ),
        encoding="utf8",
    )
    with (args.output / "decisions.jsonl").open("x", encoding="utf8") as log:
        for row in drive_window(
            pilot,
            args.game,
            args.actuate,
            args.output / "first-person.mp4",
            keys_file=args.output / "keys.jsonl",
        ):
            print(json.dumps(row, allow_nan=False), file=log, flush=True)
