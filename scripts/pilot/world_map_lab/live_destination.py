"""Loopback goal navigation for the real-game RGB stream. The web client owns device input."""

import argparse
import hashlib
import json
import math
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

import cv2
import numpy as np
from PIL import Image

from scripts.pilot.world_map_lab.destination_detail import StreetTiles
from scripts.pilot.world_map_lab.destination_itinerary import plan
from scripts.pilot.world_map_lab.destination_tiles import DestinationTiles
from scripts.pilot.world_map_lab.live_destination_atlas import SIZE, Locator
from scripts.pilot.world_map_lab.start_live_destination import code_digest


class RoadMap:
    def __init__(self, base):
        if urlsplit(base).hostname != "127.0.0.1":
            raise ValueError("expected local road planner")
        self.base = base.rstrip("/")
        self.meta = self.query("world")["drive"]

    def query(self, name, **params):
        with urlopen(
            self.base + "/api/" + name + "?" + urlencode(params),
            timeout=45 if params.get("mode") == "taxi" else 4,
        ) as response:
            return json.load(response)

    def levels(self, x, y, mode="drive"):
        return self.query("levels", mode=mode, x=x, y=y)["levels"]

    def route(self, start, goal):
        def fmt(p):
            return ",".join(format(x, ".6f") for x in p)

        return self.query("path", mode="drive", start=fmt(start), end=fmt(goal))


class Trip:
    def __init__(self, road, goal, covers):
        self.road = road
        self.goal = np.asarray(goal, dtype=float)
        if self.goal.shape != (3,) or not np.isfinite(self.goal).all():
            raise ValueError("invalid_goal")
        levels = road.levels(*self.goal[:2])
        if not any(abs(z - self.goal[2]) < 0.4 for z in levels):
            raise ValueError("unreachable_goal")
        self.covers = covers
        if not covers([self.goal]):
            raise ValueError("outside_visual_coverage")
        self.next_stops = []
        self.stop_index = 0
        self.previous = None
        self.path = None
        self.last_media_time = None
        self.motion_origin = None
        self.last_sequence = -1
        self.last_use = time.monotonic()
        self.steering = 0.0
        self.arrived = False
        self.arrival_time = None

    def decide(self, pose, now):
        neutral = dict(
            pedal="coast", steering=0.0, reason="position_unknown", pose=pose, remaining=None
        )
        if self.arrived:
            if not self.next_stops:
                return dict(neutral, reason="arrived")
            self.goal = np.asarray(self.next_stops.pop(0), dtype=float)
            self.stop_index += 1
            self.previous = self.path = self.motion_origin = self.arrival_time = None
            self.arrived = False
            self.steering = 0.0
        if pose is None:
            self.previous = None
            self.steering = 0.0
            self.motion_origin = None
            self.arrival_time = None
            return neutral
        eye = np.asarray(pose["eye"])
        previous = self.previous
        self.previous = (now, eye, pose["heading"])
        if previous is None:
            self.motion_origin = None
            return dict(neutral, reason="confirming_position")
        dt = now - previous[0]
        change = math.dist(eye, previous[1])
        turn = math.remainder(pose["heading"] - previous[2], 2 * math.pi)
        if not 0 < dt <= 1.2 or change > 0.8 + 16 * dt or abs(turn) > 0.35 + dt:
            self.motion_origin = None
            self.arrival_time = None
            return dict(neutral, reason="confirming_position")
        speed = change / dt
        if self.path is None or self.distance_from_path(eye)[0] > 3.0:
            self.path = None
            levels = self.road.levels(*eye[:2])
            options = [z for z in levels if 0.1 < eye[2] - z < 3.5]
            if len(options) > 1 or (levels and not options):
                self.path = None
                return dict(neutral, reason="road_level_unknown")
            # A camera can sit centimetres outside a raster cell at the curb.
            # Query the mesh, then verify the actual polygon landing and elevation.
            ground = [*eye[:2], options[0] if options else eye[2] - 1.45]
            result = self.road.route(ground, self.goal)
            if result["status"] != "complete":
                self.path = None
                return dict(neutral, reason="no_road_path" if options else "road_level_unknown")
            path = np.asarray(result["path"], float)
            if (
                len(path) == 0
                or math.dist(path[0], ground) > 2.5
                or math.dist(path[-1], self.goal) > 2.5
            ):
                return dict(neutral, reason="endpoint_off_road")
            if not options and (
                math.dist(path[0, :2], eye[:2]) > 0.4 or not 0.6 < eye[2] - path[0, 2] < 2.6
            ):
                return dict(neutral, reason="road_level_unknown")
            if not self.covers(path):
                return dict(neutral, reason="outside_visual_coverage")
            self.path = path[
                np.r_[True, np.linalg.norm(np.diff(path[:, :2], axis=0), axis=1) > 1e-4]
            ]
            if len(self.path) > 1:
                self.ds = np.linalg.norm(np.diff(self.path[:, :2], axis=0), axis=1)
                self.arc = np.r_[0, np.cumsum(self.ds)]
        if (
            (len(self.path) == 1 or self.arc[-1] - self.distance_from_path(eye)[1] < 3.5)
            and abs(eye[2] - self.goal[2] - 1.45) < 2
            and np.linalg.norm(eye[:2] - self.goal[:2]) <= 2.7
        ):
            if speed > 1.2:
                self.arrival_time = None
            elif self.arrival_time is None:
                self.arrival_time = now
            self.arrived = self.arrival_time is not None and now - self.arrival_time > 0.7
            return dict(
                neutral,
                pedal="coast" if self.arrived or speed < 0.8 else "brake",
                reason="waypoint_reached"
                if self.arrived and self.next_stops
                else "arrived"
                if self.arrived
                else "stopping",
                remaining=0.0,
            )
        self.arrival_time = None
        if len(self.path) < 2:
            return dict(neutral, reason="endpoint_off_road")
        cross, station, seg = self.distance_from_path(eye)
        if cross > 3.0:
            return dict(neutral, reason="outside_path")
        remaining = float(self.arc[-1] - station)
        # Stop the lookahead at sharp bends instead of cutting across the inside corner.
        ahead = min(self.arc[-1], station + max(2.5, min(7.0, 2.5 + speed * 0.5)))
        for i in range(seg, min(len(self.ds) - 1, np.searchsorted(self.arc, ahead))):
            before, after = np.diff(self.path[i : i + 3, :2], axis=0)
            if (
                before @ after < 0.8 * self.ds[i] * self.ds[i + 1]
                and self.arc[i + 1] - station > 1.5
            ):
                ahead = min(ahead, self.arc[i + 1])
                break
        aim = np.array([np.interp(ahead, self.arc, col) for col in self.path[:, :2].T]) - eye[:2]
        error = math.remainder(math.atan2(aim[1], aim[0]) - pose["heading"], 2 * math.pi)
        if abs(error) > 1.45:
            return dict(neutral, reason="turnaround_required", remaining=remaining)
        steer = float(np.clip(-error * 0.75, -0.35, 0.35))
        steer = self.steering + float(np.clip(steer - self.steering, -1.3 * dt, 1.3 * dt))
        self.steering = steer
        target = min(10.0, max(1.0, remaining * 0.55)) / (1 + 2 * abs(error))
        pedal = "brake" if speed > target + 1.2 else "throttle" if speed < target - 0.3 else "coast"
        if pedal == "throttle":
            if self.motion_origin is None or math.dist(self.motion_origin[1], eye[:2]) >= 0.8:
                self.motion_origin = (now, eye[:2].copy())
            elif now - self.motion_origin[0] >= 3.5:
                return dict(neutral, reason="no_motion", remaining=remaining)
        else:
            self.motion_origin = None
        return dict(neutral, pedal=pedal, steering=steer, reason="following", remaining=remaining)

    def distance_from_path(self, eye):
        if len(self.path) < 2:
            return math.dist(self.path[0, :2], eye[:2]), 0.0, 0
        seg = np.diff(self.path[:, :2], axis=0)
        u = np.clip(np.sum((eye[:2] - self.path[:-1, :2]) * seg, axis=1) / self.ds**2, 0, 1)
        xy = self.path[:-1, :2] + u[:, None] * seg
        ground = self.path[:-1, 2] + u * np.diff(self.path[:, 2])
        delta = np.linalg.norm(xy - eye[:2], axis=1)
        i = int(np.argmin(delta + np.maximum(0, np.abs(ground + 1.45 - eye[2]) - 1.4) * 3))
        if abs(ground[i] + 1.45 - eye[2]) > 2.0:
            return math.inf, 0.0, i
        return float(delta[i]), float(self.arc[i] + u[i] * self.ds[i]), i


def serve(args):
    code_revision = code_digest()
    road = RoadMap(args.planner)
    with args.atlas.open("rb") as f:
        atlas_digest = hashlib.file_digest(f, "sha256").hexdigest()
    locator = Locator(args.atlas, road.meta["placementRevision"])
    district_locators = {}
    district_digests = {}
    for label, file in getattr(args, "search_atlas", []):
        if not label.strip() or label in district_locators:
            raise ValueError("duplicate or empty district name")
        district = Locator(file, road.meta["placementRevision"])
        if district.meta.get("source") != "source-map-grid":
            raise ValueError("expected reference views rendered from the source map")
        district.configure_search_lenses(locator.k, args.search_hfov)
        district_locators[label] = district
        with open(file, "rb") as src:
            district_digests[label] = hashlib.file_digest(src, "sha256").hexdigest()
    tiles = DestinationTiles(road.base)
    detail = (
        StreetTiles(
            args.detail_folder, args.water, road.meta["bounds"], road.meta["placementRevision"]
        )
        if args.detail_folder and args.water
        else None
    )
    cv2.setNumThreads(3)
    lock = threading.Lock()
    sessions = {}
    log_dir = args.logs.resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body):
            raw = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            if self.headers.get("Origin") == args.origin:
                self.send_header("Access-Control-Allow-Origin", args.origin)
                self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def permitted(self):
            return (
                self.headers.get("Host") == f"127.0.0.1:{args.port}"
                and self.headers.get("Origin") == args.origin
            )

        def do_OPTIONS(self):
            if not self.permitted():
                return self.reply(403, dict(error="origin_denied"))
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", args.origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-World-Session, X-Frame-Sequence, X-Frame-Media-Time",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def webp(self, data):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", args.origin)
            self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "private,max-age=31536000,immutable")
            self.send_header("Content-Type", "image/webp")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            if self.permitted() and self.path.startswith(f"/tiles/{tiles.revision}/"):
                data = tiles.files.get(self.path.split("/", 3)[3])
                if data is None:
                    return self.reply(404, dict(error="unknown_tile"))
                return self.webp(data)
            if self.permitted() and detail and self.path.startswith(f"/street/{detail.version}/"):
                try:
                    _, _, _, span, leaf = self.path.split("/")
                    if not leaf.endswith(".webp"):
                        raise ValueError("format")
                    col, row = leaf[:-5].split("-")
                    data = detail.tile(int(span), int(col), int(row))
                except (KeyError, ValueError):
                    return self.reply(404, dict(error="unknown_tile"))
                return self.webp(data)
            if self.path != "/world" or not self.permitted():
                return self.reply(403, dict(error="origin_denied"))
            self.reply(
                200,
                dict(
                    tiles=tiles.manifest(),
                    streetTiles=detail.manifest() if detail else None,
                    searchAtlases=district_digests,
                    searchCameraHfovs=args.search_hfov,
                    searchRegions=[
                        dict(
                            name=name,
                            points=bank.meta["visualTrace"],
                            radius=bank.meta["coverageRadius"],
                        )
                        for name, bank in district_locators.items()
                    ],
                    bounds=road.meta["bounds"],
                    mapRevision=road.meta["placementRevision"],
                    atlas=locator.meta,
                    atlasDigest=atlas_digest,
                    codeDigest=code_revision,
                ),
            )

        def do_POST(self):
            if not self.permitted():
                return self.reply(403, dict(error="origin_denied"))
            try:
                size = int(self.headers.get("Content-Length", "0"))
                frame = self.path in ("/frame", "/probe")
                if not 0 <= size <= (384 * 1024 if frame else 4096):
                    return self.reply(413, dict(error="payload_size"))
                typ = self.headers.get_content_type()
                if typ != ("image/jpeg" if frame else "application/json"):
                    return self.reply(415, dict(error="content_type"))
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("invalid_frame")
                if self.path == "/levels":
                    return self.road_levels(raw)
                if self.path == "/itinerary":
                    payload = json.loads(raw)
                    if payload.get("revision") != road.meta["placementRevision"]:
                        raise ValueError("invalid_goal")
                    return self.reply(
                        200, plan(road, payload["stops"], payload["mode"], locator.covers)
                    )
                if self.path == "/preview":
                    payload = json.loads(raw)
                    if payload["revision"] != road.meta["placementRevision"]:
                        raise ValueError("invalid_goal")
                    start, goal = (payload[k] for k in ("start", "goal"))
                    for point in (start, goal):
                        if (
                            len(point) != 3
                            or not all(type(v) in (int, float) and math.isfinite(v) for v in point)
                            or not any(abs(z - point[2]) < 0.4 for z in road.levels(*point[:2]))
                        ):
                            raise ValueError("unreachable_goal")
                    result = road.route(start, goal)
                    path = result.get("path", [])
                    if (
                        result.get("status") != "complete"
                        or not path
                        or math.dist(start, path[0]) > 2.5
                        or math.dist(goal, path[-1]) > 2.5
                    ):
                        return self.reply(200, dict(path=[], distance=0, covered=False))
                    return self.reply(
                        200,
                        dict(
                            path=path,
                            distance=sum(math.dist(a, b) for a, b in zip(path, path[1:])),
                            covered=bool(locator.covers(path)),
                        ),
                    )
                with lock:
                    self.process(frame, raw)
            except (ValueError, KeyError, TypeError, OSError, cv2.error) as e:
                message = (
                    str(e)
                    if str(e)
                    in (
                        "unreachable_goal",
                        "invalid_goal",
                        "invalid_frame",
                        "outside_visual_coverage",
                    )
                    else "invalid_request"
                )
                self.reply(400, dict(error=message))

        def road_levels(self, raw):
            payload = json.loads(raw)
            x, y = payload["point"]
            mode = payload.get("mode", "drive")
            if mode not in ("walk", "drive", "taxi"):
                raise ValueError("invalid_goal")
            surface = "drive" if mode == "drive" else "walk"
            if not all(math.isfinite(v) for v in (x, y)):
                raise ValueError("invalid_goal")
            drive = road.levels(x, y)
            walk = road.levels(x, y, mode="walk")
            levels = drive if surface == "drive" else walk
            suggestion = None
            if not levels:
                for radius in (0.75, 1.5, 3.0):
                    for direction in range(8):
                        angle = math.pi * direction / 4
                        sx, sy = x + radius * math.cos(angle), y + radius * math.sin(angle)
                        nearby = road.levels(sx, sy, mode=surface)
                        if nearby:
                            suggestion = dict(point=[sx, sy], distance=radius)
                            break
                    if suggestion:
                        break
            return self.reply(
                200,
                dict(
                    levels=levels,
                    walkLevels=walk,
                    driveLevels=drive,
                    suggestion=suggestion,
                    coveredLevels=[z for z in levels if locator.covers([[x, y, z]])],
                ),
            )

        @staticmethod
        def decode_frame(raw):
            with Image.open(BytesIO(raw)) as pic:
                if pic.format != "JPEG" or pic.size != SIZE:
                    raise ValueError("invalid_frame")
                return np.asarray(pic.convert("L"))

        def process(self, frame, raw):
            now = time.monotonic()
            for key, trip in list(sessions.items()):
                if now - trip.last_use > 45:
                    del sessions[key]
            if self.path == "/probe":
                if sessions:
                    return self.reply(409, dict(error="session_active"))
                gray = self.decode_frame(raw)
                found = []
                for name, bank in [(None, locator), *district_locators.items()]:
                    pose = bank.locate(gray)
                    if pose is None:
                        continue
                    x, y, z = pose["eye"]
                    if bank.covers([[x, y, z - 1.45]]):
                        found.append(dict(pose=pose, district=name))
                # Even strong independent solutions in two districts are ambiguous.
                result = found[0] if len(found) == 1 else dict(pose=None, district=None)
                return self.reply(200, dict(**result, ambiguous=len(found) > 1))
            if self.path == "/start":
                if sessions:
                    return self.reply(409, dict(error="session_active"))
                payload = json.loads(raw)
                if payload["revision"] != road.meta["placementRevision"]:
                    raise ValueError("invalid_goal")
                stops = payload.get("stops")
                if stops is not None:
                    selection = plan(road, stops, "drive", locator.covers)
                    if selection.get("status") != "complete" or not selection["covered"]:
                        raise ValueError("outside_visual_coverage")
                trip = Trip(road, stops[0] if stops else payload["goal"], locator.covers)
                if stops:
                    trip.next_stops = stops[1:]
                key = secrets.token_hex(24)
                trip.log = log_dir / (secrets.token_hex(12) + ".jsonl")
                sessions[key] = trip
                return self.reply(201, dict(session=key))
            key = self.headers.get("X-World-Session")
            if key not in sessions:
                return self.reply(409, dict(error="session_closed"))
            trip = sessions[key]
            trip.last_use = now
            if self.path == "/stop":
                receipts = json.loads(raw)
                counts = {name: receipts.get(name, 0) for name in ("applied", "rejected")}
                if not all(type(v) is int and 0 <= v < 2**32 for v in counts.values()):
                    raise ValueError("invalid_receipts")
                with trip.log.open("a", encoding="utf8") as f:
                    print(json.dumps(dict(event="stop", t=now, deviceReceipts=counts)), file=f)
                del sessions[key]
                return self.reply(200, dict(stopped=True))
            if not frame:
                return self.reply(404, dict(error="unknown_endpoint"))
            seq = int(self.headers.get("X-Frame-Sequence", "-1"))
            if not trip.last_sequence < seq < 2**53:
                return self.reply(409, dict(error="frame_sequence"))
            gray = self.decode_frame(raw)
            stamp = self.headers.get("X-Frame-Media-Time")
            clock = float(stamp) if stamp is not None else now
            if (
                not math.isfinite(clock)
                or clock < 0
                or (trip.last_media_time is not None and clock <= trip.last_media_time)
            ):
                return self.reply(409, dict(error="frame_sequence"))
            # A resumed or re-buffered video must confirm its pose again.
            if (
                trip.last_media_time is not None
                and abs((clock - trip.last_media_time) - (now - trip.frame_received)) > 0.6
            ):
                trip.previous = None
                trip.motion_origin = None
            trip.frame_received = now
            trip.last_media_time = clock
            trip.last_sequence = seq
            pose = locator.locate(gray)
            response = trip.decide(pose, clock)
            response["stopIndex"] = trip.stop_index
            if pose and trip.path is not None:
                response["path"] = trip.path.tolist()
            response.update(sequence=seq, computeMs=round((time.monotonic() - now) * 1000, 1))
            with trip.log.open("a", encoding="utf8") as f:
                print(
                    json.dumps(dict(t=now, goal=trip.goal.tolist(), **response), allow_nan=False),
                    file=f,
                )
            self.reply(200, response)

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--atlas", type=Path, required=True)
    p.add_argument("--logs", type=Path, required=True)
    p.add_argument("--planner", default="http://127.0.0.1:8817")
    p.add_argument("--origin", default="http://127.0.0.1:3015")
    p.add_argument(
        "--search-atlas", action="append", nargs=2, default=[], metavar=("DISTRICT", "NPZ")
    )
    p.add_argument("--search-hfov", action="append", type=float, default=[])
    p.add_argument("--detail-folder", type=Path)
    p.add_argument("--water", type=Path)
    p.add_argument("--port", type=int, default=8849)
    serve(p.parse_args())
