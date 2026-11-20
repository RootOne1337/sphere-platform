"""Evaluate the map's visual driving policy on source pixels with real decision age."""

import argparse
import json
import math
import sys
import time
import uuid
from collections import Counter, deque
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import av
import cv2
import numpy as np

from scripts.pilot.world_map_lab.bake_browser_landmarks import fingerprint, load_bank
from scripts.pilot.world_map_lab.classic_lens import focal_from_map, stationary_focal
from scripts.pilot.world_map_lab.classic_transfers import MixedJourney
from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks
from scripts.pilot.world_map_lab.native_route import native_route
from scripts.pilot.world_map_lab.neighborhood_search import NeighborhoodSearch
from scripts.pilot.world_map_lab.replay_game_map import select_agreement
from scripts.pilot.world_map_lab.track_landmarks import LandmarkTrack


class CameraPilot:
    def __init__(self, args):
        # These are the same route, atlas and steering implementation used by the browser comparison.
        # The fixture supplies reference geometry only. Its kinematic step is never invoked.
        sys.path.insert(0, str(args.lab.resolve()))
        argv = sys.argv
        try:
            sys.argv = [argv[0], str(args.source.resolve())]
            import scooter5_visual_live_candidates_fast as scene

            sys.argv = [argv[0], str(args.controller.resolve())]
            import scooter5_control_fixture as reference
        finally:
            sys.argv = argv
        paths, _, self.route_hash = native_route(args.route)
        if not np.array_equal(
            np.asarray(paths[1]), np.asarray(reference.route_data["trace"])[:, :3]
        ):
            raise ValueError("controller circuit and native scenario differ")
        if args.hfov is not None and not 40 <= args.hfov <= 150:
            raise ValueError("horizontal camera field of view must be measured in degrees")
        controller_file = Path(
            sys.modules[reference.VisualPaceFollower.__module__].__file__
        ).resolve(strict=True)
        if not controller_file.is_relative_to(args.controller.resolve()):
            raise ValueError("loaded steering policy came from a different checkout")
        self.controller_sha = fingerprint(controller_file)
        self.journey = MixedJourney(paths) if args.start == "on-foot" else None
        self.ref = reference
        self.index = load_bank(args.bank, args.lab, scene)
        self.atlas = self.index.atlas
        w, h = self.atlas.W, self.atlas.H
        self.hfov = args.hfov
        self.lens_votes = deque(maxlen=3)
        f = w / (2 * math.tan(math.radians(args.hfov or 100.0) / 2))
        self.atlas.K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
        self.native = IndexedLandmarks(
            SimpleNamespace(
                xyz=scene.xyz,
                desc=scene.desc,
                views=scene.views,
                origin=scene.origin,
                W=w,
                H=h,
                K=self.atlas.K,
                locate_progress=scene.locate_progress,
            )
        )
        self.foot = None
        if self.journey and args.transfer_bank:
            self.foot = load_bank(args.transfer_bank, args.lab, scene)
            with np.load(args.transfer_bank, allow_pickle=False) as inputs:
                meta = json.loads(str(inputs["meta"]))
            if meta["route"] != self.route_hash or meta["mesh"] != fingerprint(
                args.lab / "ariane-scooter4-mesh.npz"
            ):
                raise ValueError(
                    "walking landmarks belong to a different native route or source mesh"
                )
            self.foot.atlas.K = self.atlas.K
            self.foot.bank(0)
            self.foot.bank(int((scene.dist[-1] - 6) // 12))
        self.search = NeighborhoodSearch([(self.index, 4), (self.native, 8)])
        # Build immutable search trees once, before the first live capture. Frame age must
        # include the actual matching work, but does not include loading the map at startup.
        slots = 1 + math.ceil(scene.dist[-1] / 12)
        for index in (self.native, self.index):
            index.cache_tiles = slots
            for tile in range(slots):
                index.bank(tile)
        self.tracker = LandmarkTrack(self.atlas, max_travel=3)
        self.last = None
        self.route_length = float(scene.dist[-1])
        self.now = 0.0
        scale = reference.proto.profile.width / w
        self.proto = replace(
            reference.proto, intrinsics=tuple(v * scale for v in (f, f, w / 2, h / 2))
        )
        self.recovery = deque(maxlen=5)
        self.last_control = None
        self.restarts = 0
        self.epoch = str(uuid.uuid4())
        self.seq = 0
        self.reset_driver()

    def reset_driver(self):
        reference = self.ref
        self.last_control = None
        self.recovery.clear()
        self.pace = reference.VisualPace(self.proto)
        self.driver = reference.VisualPaceFollower(
            self.proto,
            self.pace,
            clock=lambda: self.now,
            start_mode="recognized_route",
            reference_rotations=tuple(map(reference.rotation, reference.angles)),
            max_seconds=1800,
            pace_cap=25,
            pursuit_lookahead_seconds=0.35,
            terminal_approach=True,
        )

    def measure_lens(self, rgb, t, digest):
        if any(v[2] == digest for v in self.lens_votes):
            return
        features = self.native.features(rgb)
        if self.foot and self.journey.stage != "drive":
            bank = self.foot
            starts = [self.foot_window()[0]]
        else:
            bank = self.native
            starts = self.search.suggest(features)[:2]
        single_frame = None
        for start in starts:
            bank.match(features, start, min(start + 12, self.route_length), require_corridor=False)
            if bank.putatives is None:
                continue
            angle = focal_from_map(*bank.putatives, self.atlas.W, self.atlas.H)
            if angle is None:
                continue
            heldout = stationary_focal(*bank.putatives, self.atlas.W, self.atlas.H)
            if heldout is not None and abs(heldout - angle) < 1.25:
                single_frame = (angle + heldout) / 2
            self.lens_votes.append((angle, t, digest))
            break
        if single_frame is None:
            if len(self.lens_votes) != 3:
                return
            angles = [v[0] for v in self.lens_votes]
            if max(angles) - min(angles) > 2 or self.lens_votes[-1][1] - self.lens_votes[0][1] > 4:
                return
            single_frame = float(np.median(angles))
        self.hfov = single_frame
        focal = self.atlas.W / (2 * math.tan(math.radians(self.hfov) / 2))
        self.atlas.K[0, 0] = self.atlas.K[1, 1] = focal
        ratio = self.proto.profile.width / self.atlas.W
        self.proto = replace(
            self.proto, intrinsics=(focal * ratio, focal * ratio, *self.proto.intrinsics[2:])
        )
        self.reset_driver()

    def foot_window(self):
        return (
            (0.0, 12.0)
            if self.journey.stage in ("approach", "boarding")
            else (self.route_length - 12, self.route_length)
        )

    def locate(self, rgb, t):
        if self.foot and self.journey.stage != "drive":
            low, high = self.foot_window()
            foot = self.foot.match(self.foot.features(rgb), low, high, require_corridor=False)
            if foot is None:
                return None, "lost"
            self.last = t, foot[2]
            return foot, "matched"
        recent = self.last is not None and 0 < t - self.last[0] <= 1.0
        radius = 3 + 15 * (t - self.last[0]) if recent else self.route_length
        station = self.last[1] if recent else 0.0
        low, high = max(0.0, station - radius), min(self.route_length, station + radius)
        fit = self.tracker.track(rgb, t, low, high) if recent else None
        if fit is not None:
            self.last = t, fit[2]
            return fit, "tracked"
        feat = self.index.features(rgb)
        if recent:
            windows = [(low, high)]
        else:
            ranks = self.search.suggest(feat)
            # Keep the best visual neighborhood and rotate the second probe across alternatives.
            chosen = ranks[:1]
            if len(ranks) > 1:
                chosen.append(ranks[1 + self.seq % (len(ranks) - 1)])
            windows = [(s, min(self.route_length, s + 12)) for s in chosen]
        candidates = []
        supports = []
        for a, b in windows:
            for bank in (self.native, self.index):
                fit = bank.match(feat, a, b, require_corridor=False)
                if fit is not None:
                    candidates.append(fit)
                    supports.append(bank.putatives)
        win = select_agreement(candidates)
        if win is None:
            return None, "lost"
        matches = next(p for fit, p in zip(candidates, supports, strict=True) if fit is win)
        self.tracker.seed(rgb, matches, win[0], win[1], t)
        self.last = t, win[2]
        return win, "matched"

    def confirm_recovery(self, t, digest, fit, method, geom):
        if (
            fit is None
            or self.now - t > 0.25
            or geom["cross_track_units"] > 2.2
            or self.last_control is None
        ):
            self.recovery.clear()
            return False
        eye, rot, station, _, _ = fit
        old_t, old_station = self.last_control
        if (
            abs(station - old_station) > 1.5 + 16 * (t - old_t)
            or np.dot(
                rot[2, :2], self.ref.delta[geom["segment"], :2] / self.ref.length[geom["segment"]]
            )
            < 0.6
        ):
            self.recovery.clear()
            return False
        if self.recovery:
            stamp, previous, s, _, previous_digest = self.recovery[-1]
            dt = t - stamp
            if (
                not 0 < dt <= 0.5
                or previous_digest == digest
                or np.linalg.norm(eye - previous) > 0.65 + 16 * dt
                or not -0.75 <= station - s <= 0.75 + 16 * dt
            ):
                self.recovery.clear()
        self.recovery.append((t, eye, station, method, digest))
        return len(self.recovery) >= 3 and sum(p[3] == "matched" for p in self.recovery) >= 2

    def frame(self, raw, t, capture_started):
        h, w = raw.shape[:2]
        if abs(w / h - self.atlas.W / self.atlas.H) > 0.004:
            raise ValueError(
                "client viewport differs from the mapped aspect; calibrate the viewport"
            )
        digest = sha256(raw.tobytes()).hexdigest()
        rgb = cv2.resize(raw, (self.atlas.W, self.atlas.H), interpolation=cv2.INTER_AREA)
        if self.hfov is None:
            self.measure_lens(rgb, t, digest)
            fit, method = None, "calibrating"
        else:
            fit, method = self.locate(rgb, t)
        self.seq += 1
        geom = {}
        if fit is not None:
            eye, rot, station, count, error = fit
            pos = eye - self.ref.base
            coeff = np.clip(
                np.sum((pos - self.ref.trace[:-1]) * self.ref.delta, axis=1) / self.ref.length**2,
                0,
                1,
            )
            d = np.linalg.norm(self.ref.trace[:-1] + coeff[:, None] * self.ref.delta - pos, axis=1)
            i = int(np.argmin(d))
            geom = dict(
                center=tuple(pos),
                rotation=tuple(rot.ravel()),
                segment=i,
                progress_units=float(self.ref.arc[i] + coeff[i] * self.ref.length[i]),
                cross_track_units=float(d[i]),
                inliers=count,
                median_error_px=error * self.proto.profile.width / self.atlas.W,
            )
        self.now = t + time.monotonic() - capture_started
        recoverable = self.driver.terminal and self.driver.terminal[0] in (
            "vehicle_progress_discontinuity",
            "vehicle_relocalization_timeout",
            "vehicle_pose_discontinuity",
        )
        if recoverable and self.confirm_recovery(t, digest, fit, method, geom):
            self.reset_driver()
            self.recovery.clear()
            self.restarts += 1
        pose = self.ref.RoutePose(
            "localized" if geom else "unknown",
            "native_rgb" if geom else "route_pose_not_verified",
            self.proto.id,
            self.proto.world_revision,
            self.epoch,
            self.seq,
            t,
            self.now,
            digest,
            (self.proto.profile.width, self.proto.profile.height),
            **geom,
        )
        speed = self.pace.observe(pose, self.now)
        reading = dict(
            status="accepted",
            visual_pace=speed,
            epoch=self.epoch,
            sequence=self.seq,
            received_at=t,
            source_rgb_sha256=digest,
        )
        plan = self.driver.observe(
            pose, reading, motion_active=bool(speed is not None and speed > 0.4)
        )
        if plan["phase"] == "following" and fit is not None:
            self.last_control = t, fit[2]
        row = dict(
            frame=self.seq,
            capture_s=t,
            latency_ms=round(1000 * (self.now - t), 2),
            source_sha256=digest,
            hfov=self.hfov,
            restarts=self.restarts,
            cross_track=geom.get("cross_track_units"),
            vision=method,
            station=fit[2] if fit else None,
            supports=geom.get("inliers", 0),
            measured_xyz=fit[0].tolist() if fit else None,
            view_forward=fit[1][2].tolist() if fit else None,
            visual_pace=plan.get("observedVisualPace"),
            target_pace=plan.get("targetVisualPace"),
            phase=plan["phase"],
            reason=plan["reason"],
            pedal=plan["pedal"],
            steering=plan["steering"],
            terminal_brake=bool(plan.get("terminalBrake")),
        )
        if self.journey is not None:
            drive_phase = self.journey.stage == "drive"
            self.journey.step(row, fit, self.reset_driver)
            row["drive_enabled"] = drive_phase and self.journey.stage == "drive"
        return row


def source_times(path):
    times = []
    with (path.parent / "frames.jsonl").open(encoding="utf-8") as rows, path.open("rb") as raw:
        for n, line in enumerate(rows):
            r = json.loads(line)
            if (
                not isinstance(r.get("bytes"), int)
                or r["bytes"] <= 0
                or r["index"] != n
                or raw.tell() != r["offset"]
                or sha256(raw.read(r["bytes"])).hexdigest() != r["sha256"]
            ):
                raise ValueError("frame clock is from another recording")
            t = r["relative_ticks_90k"] / 90000
            if not math.isfinite(t) or (times and t <= times[-1]):
                raise ValueError("invalid source frame time")
            times.append(t)
        if not times or raw.read(1):
            raise ValueError("incomplete source frame clock")
    return times


def replay(pilot, path):
    next_t = 0.0
    times = source_times(path) if path.suffix.lower() == ".h264" else None
    decoded = 0
    with av.open(str(path)) as movie:
        for i, frame in enumerate(movie.decode(video=0)):
            decoded += 1
            if times is None and frame.pts is None:
                raise ValueError("capture timestamp missing")
            t = times[i] if times is not None else float(frame.pts * frame.time_base)
            if t + 0.00001 < next_t:
                continue
            start = time.monotonic()
            row = pilot.frame(frame.to_ndarray(format="rgb24"), t, start)
            # A single worker cannot consume source frames captured while it was busy.
            next_t = max(t + 0.2, pilot.now)
            yield row
    if times is not None and len(times) != decoded:
        raise ValueError("decoded frame count differs from the capture clock")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "controller", "lab", "bank", "route", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--video", type=Path)
    mode.add_argument("--classic", type=Path, help="staged offline game folder")
    p.add_argument(
        "--start",
        choices=("mounted", "on-foot"),
        help="default: on foot in the native game, mounted in a recorded drive",
    )
    p.add_argument(
        "--transfer-bank", type=Path, help="first-person landmarks for both walking legs"
    )
    p.add_argument("--actuate", action="store_true", help="enable normal game keys")
    p.add_argument("--movie", type=Path, help="record a native first-person MP4 targeting 30 fps")
    p.add_argument(
        "--hfov",
        type=float,
        help="known horizontal field of view; otherwise estimate from map evidence before sending commands",
    )
    args = p.parse_args()
    if args.actuate and not args.classic:
        p.error("only a staged native game can receive controls")
    if args.movie and (
        not args.classic or args.movie.exists() or args.movie.suffix.lower() != ".mp4"
    ):
        p.error("choose a new MP4 for the native game")
    if args.output.exists():
        p.error("choose a new telemetry file")
    args.start = args.start or ("on-foot" if args.classic else "mounted")
    inputs = args.output.with_suffix(".inputs.json")
    keys_file = args.output.with_suffix(".keys.jsonl")
    if inputs.exists() or (args.actuate and keys_file.exists()):
        p.error("choose a new attempt for telemetry and command events")
    started = time.monotonic()
    pilot = CameraPilot(args)
    metadata = dict(
        routeSha256=pilot.route_hash,
        controllerSha256=pilot.controller_sha,
        landmarkSha256=fingerprint(args.bank),
        walkingBankSha256=fingerprint(args.transfer_bank) if args.transfer_bank else None,
        mode="native" if args.classic else "archive",
        sourceSha256=fingerprint(args.video) if args.video else None,
        captureEpoch=pilot.epoch,
        actuation=bool(args.actuate),
        start=args.start,
        loadSeconds=round(time.monotonic() - started, 3),
    )
    with inputs.open("x", encoding="utf8") as sink:
        json.dump(metadata, sink, indent=2)
    if args.classic:
        from scripts.pilot.world_map_lab.classic_window import drive_window

        rows = drive_window(pilot, args.classic, args.actuate, args.movie, keys_file=keys_file)
    else:
        rows = replay(pilot, args.video)
    counts = Counter()
    with args.output.open("x", encoding="utf8") as log:
        for row in rows:
            counts[row["pedal"]] += 1
            print(json.dumps(row), file=log, flush=True)
    print(dict(counts))


if __name__ == "__main__":
    main()
