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
from scripts.pilot.world_map_lab.live_destination_atlas import SIZE, Locator, MenuBackdrop
from scripts.pilot.world_map_lab.pedestrian_surface import FootSurface
from scripts.pilot.world_map_lab.scooter_road_access import RoadAccess
from scripts.pilot.world_map_lab.start_live_destination import code_digest
from scripts.pilot.world_map_lab.world_scene_acquisition import WorldAcquisition
from scripts.pilot.world_map_lab.world_walk_trip import WalkTrip


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

    def levels(self, x, y, mode="drive", *, surface=None):
        params = {"surface": surface} if surface else {}
        return self.query("levels", mode=mode, x=x, y=y, **params)["levels"]

    def route(self, start, goal):
        def fmt(p):
            return ",".join(format(x, ".6f") for x in p)

        return self.query("path", mode="drive", start=fmt(start), end=fmt(goal))


class Trip:
    def __init__(self, road, goal, covers, *, access=None, local_covers=None):
        self.road = road
        self.goal = np.asarray(goal, dtype=float)
        if self.goal.shape != (3,) or not np.isfinite(self.goal).all():
            raise ValueError("invalid_goal")
        levels = road.levels(*self.goal[:2])
        if not any(abs(z - self.goal[2]) < 0.4 for z in levels):
            raise ValueError("unreachable_goal")
        self.covers = covers
        self.access = access
        self.local_covers = local_covers
        self.pending_access = None
        self.access_origin = None
        self.access_m = 0.0
        self.progressive = False
        self.extend_visual = False
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
        self.extend_visual = False
        neutral = dict(
            pedal="coast", steering=0.0, reason="position_unknown", pose=pose, remaining=None
        )
        if self.arrived:
            if not self.next_stops:
                return dict(neutral, reason="arrived")
            self.goal = np.asarray(self.next_stops.pop(0), dtype=float)
            self.stop_index += 1
            self.previous = self.path = self.motion_origin = self.arrival_time = None
            self.pending_access = self.access_origin = None
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
            path = np.asarray(result.get("path", []), float)
            joined = bool(
                len(path)
                and math.dist(path[0], ground) <= 2.5
                and math.dist(path[-1], self.goal) <= 2.5
            )
            on_surface = bool(
                options
                or (
                    joined
                    and math.dist(path[0, :2], eye[:2]) <= 0.4
                    and 0.6 < eye[2] - path[0, 2] < 2.6
                )
            )
            if not on_surface and not levels and self.access is not None:
                if self.pending_access is None or math.dist(eye, self.access_origin) > 2:
                    if self.pending_access is not None and not self.pending_access.done():
                        return dict(neutral, reason="road_level_unknown")
                    self.access_origin = eye.copy()
                    self.pending_access = self.access.executor.submit(
                        self.access.find, eye.copy(), self.goal.copy()
                    )
                if not self.pending_access.done():
                    return dict(neutral, reason="confirming_position")
                result = self.pending_access.result()
                if not result:
                    return dict(neutral, reason="road_level_unknown")
                path = np.asarray(result["path"], float)
                self.access_m = result["accessMeters"]
            elif result["status"] != "complete":
                return dict(neutral, reason="no_road_path" if options else "road_level_unknown")
            elif not joined:
                return dict(neutral, reason="endpoint_off_road")
            elif not on_surface:
                return dict(neutral, reason="road_level_unknown")
            else:
                self.access_m = 0.0
            self.progressive = not self.covers(path)
            if self.progressive and not self.local_covers:
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
        if self.progressive:
            horizon = min(self.arc[-1], station + max(5, 3 + 0.7 * speed + speed**2 / 8))
            ahead_stations = np.linspace(
                station, horizon, max(2, math.ceil((horizon - station) / 1.5) + 1)
            )
            envelope = np.column_stack(
                [np.interp(ahead_stations, self.arc, col) for col in self.path.T]
            )
            future = min(self.arc[-1], station + 14)
            future_point = [np.interp(future, self.arc, col) for col in self.path.T]
            self.extend_visual = not self.local_covers([future_point])
            if not self.local_covers(envelope):
                self.extend_visual = True
                self.motion_origin = None
                if speed > 0.8:
                    return dict(neutral, reason="stopping", pedal="brake", remaining=remaining)
                return dict(neutral, reason="outside_visual_coverage", remaining=remaining)
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
        if self.progressive:
            target = min(target, 2.0 if station < self.access_m else 3.5)
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


def probe_atlases(gray, main, districts, *, observed=None, include_main=True):
    # All indexes use the same RootSIFT representation and normalized image size.
    if observed is None:
        observed = main.describe(gray)
    found = []
    if observed is not None:
        indexes = [(None, main), *districts.items()] if include_main else districts.items()
        for name, bank in indexes:
            pose = bank.locate_features(gray, *observed)
            if pose is not None:
                x, y, z = pose["eye"]
                if bank.covers([[x, y, z - 1.45]]):
                    found.append(dict(pose=pose, district=name))
    for i, first in enumerate(found):
        for second in found[i + 1 :]:
            a, b = first["pose"], second["pose"]
            if math.dist(a["eye"], b["eye"]) > 1.0 or math.cos(
                a["heading"] - b["heading"]
            ) < math.cos(math.radians(5)):
                return dict(pose=None, district=None, ambiguous=True)
    # Overlapping source grids can recognize the very same street camera.
    best = max(
        found, key=lambda item: item["pose"]["supports"], default=dict(pose=None, district=None)
    )
    return dict(**best, ambiguous=False)


def probe_start_levels(road, eye):
    x, y, z = eye
    eligible = {}
    for mode, minimum, maximum in (("drive", 0.1, 3.5), ("walk", 0.85, 2.55)):
        surfaces = {"surface": "pavement"} if mode == "walk" else {}
        try:
            valid = [
                level
                for level in road.levels(x, y, mode=mode, **surfaces)
                if minimum < z - level < maximum
            ]
        except (KeyError, ValueError, OSError):
            valid = []
        eligible[mode] = valid[0] if len(valid) == 1 else None
    return eligible


def walking_exposure(gray):
    histogram = np.bincount(gray.ravel(), minlength=256).cumsum()
    low, high = np.searchsorted(histogram, [gray.size * .03, gray.size * .97])
    if high - low < 8:
        return None
    gain = min(4.0, 180.0 / (high - low))
    levels = np.uint8(np.clip((np.arange(256) - low) * gain + 18, 0, 255))
    return cv2.LUT(gray, levels)


def walk_pose_plausible(previous, pose, clock):
    if previous is None:
        return True
    stamp, eye, _ = previous
    elapsed = clock - stamp
    return not 0 < elapsed <= 1.2 or (
        abs(pose["eye"][2] - eye[2]) <= .30 + .18 * elapsed
        and math.dist(pose["eye"], eye) <= .28 + 3.6 * elapsed
    )


def preview_origin(value):
    try:
        url = urlsplit(value)
        if url.port and value == f"http://127.0.0.1:{url.port}":
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("preview origin must be an exact IPv4 loopback URL with a port")


def serve(args):
    code_revision = code_digest()
    road = RoadMap(args.planner)
    with args.atlas.open("rb") as f:
        atlas_digest = hashlib.file_digest(f, "sha256").hexdigest()
    locator = Locator(args.atlas, road.meta["placementRevision"])
    menu = menu_digest = None
    if args.menu_background:
        raw_menu = args.menu_background.read_bytes()
        with Image.open(BytesIO(raw_menu)) as image:
            menu = MenuBackdrop(np.asarray(image.convert("L")))
        menu_digest = hashlib.sha256(raw_menu).hexdigest()
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
    weather_locators, weather_digests = {}, {}
    for label, file in getattr(args, "walk_weather_atlas", []):
        if not label.strip() or label in district_locators or label in weather_locators:
            raise ValueError("duplicate or empty walking weather atlas name")
        bank = Locator(file, road.meta["placementRevision"])
        if bank.meta.get("source") != "source-map-grid" or not bank.meta.get("independentScenery"):
            raise ValueError("walking weather atlases require independent source-map references")
        bank.configure_search_lenses(locator.k, args.search_hfov)
        weather_locators[label] = bank
        with open(file, "rb") as src:
            weather_digests[label] = hashlib.file_digest(src, "sha256").hexdigest()
    walking_banks = {**district_locators, **weather_locators}

    def walk_fix(gray, observed):
        fix = probe_atlases(gray, locator, district_locators, observed=observed)
        if fix["pose"] is not None or fix["ambiguous"] or not weather_locators:
            return fix, False
        adjusted = walking_exposure(gray)
        if adjusted is None:
            return fix, False
        return probe_atlases(adjusted, locator, walking_banks), True
    drive_regions = list(getattr(args, "drive_region", []))
    if len(set(drive_regions)) != len(drive_regions) or any(
        name not in district_locators or not district_locators[name].meta.get("independentScenery")
        for name in drive_regions
    ):
        raise ValueError("drive regions require distinct independent source-map surveys")
    drive_banks = {name: district_locators[name] for name in drive_regions}

    search_only = {
        name: bank for name, bank in district_locators.items() if name not in drive_banks
    }

    def covers(path):
        return locator.covers(path) or any(bank.covers(path) for bank in drive_banks.values())

    tiles = DestinationTiles(
        road.base,
        terrain_folder=getattr(args, "terrain_overview", None),
        map_revision=road.meta["placementRevision"],
        bounds=road.meta["bounds"],
    )
    texture_pack = getattr(args, "texture_pack", None) or args.detail_folder
    detail = (
        StreetTiles(texture_pack, args.water, road.meta["bounds"], road.meta["placementRevision"])
        if texture_pack and args.water
        else None
    )
    cv2.setNumThreads(3)
    lock = threading.Lock()
    sessions = {}
    origins = {args.origin, *getattr(args, "preview_origin", [])}
    log_dir = args.logs.resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    search_config = getattr(args, "world_search_config", None)
    global_search = (
        WorldAcquisition(
            search_config, log_dir / "world-search", road.base, road.meta["placementRevision"]
        )
        if search_config
        else None
    )

    access = RoadAccess(args.detail_folder, road) if global_search and args.detail_folder else None
    foot = (
        FootSurface(args.detail_folder, road, check_visibility=False)
        if global_search and args.detail_folder
        else None
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body):
            raw = json.dumps(body, allow_nan=False).encode()
            try:
                self.send_response(status)
                origin = self.headers.get("Origin")
                if origin in origins:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def permitted(self):
            return (
                self.headers.get("Host") == f"127.0.0.1:{args.port}"
                and self.headers.get("Origin") in origins
            )

        def do_OPTIONS(self):
            if not self.permitted():
                return self.reply(403, dict(error="origin_denied"))
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-World-Session, X-Frame-Sequence, X-Frame-Media-Time",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def webp(self, data):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
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
                    menuBackgroundDigest=menu_digest,
                    driveRegions=drive_regions,
                    worldSearch=(
                        dict(config=global_search.signature, **global_search.status())
                        if global_search
                        else None
                    ),
                    searchCameraHfovs=args.search_hfov,
                    searchRegions=[
                        dict(
                            name=name,
                            points=bank.meta["visualTrace"],
                            radius=bank.meta["coverageRadius"],
                            driveEnabled=name in drive_banks,
                        )
                        for name, bank in district_locators.items()
                    ],
                    bounds=road.meta["bounds"],
                    mapRevision=road.meta["placementRevision"],
                    atlas=locator.meta,
                    atlasDigest=atlas_digest,
                    codeDigest=code_revision,
                    walkAutopilot=foot is not None,
                    walkWeatherAtlases=weather_digests,
                ),
            )

        def do_POST(self):
            if not self.permitted():
                return self.reply(403, dict(error="origin_denied"))
            try:
                size = int(self.headers.get("Content-Length", "0"))
                frame = self.path in ("/frame", "/probe", "/walk-probe")
                if (
                    not 0
                    <= size
                    <= (1536 * 1024 if frame and global_search else 384 * 1024 if frame else 4096)
                ):
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
                        200,
                        plan(
                            road,
                            payload["stops"],
                            payload["mode"],
                            covers,
                            surface=payload.get("surface"),
                        ),
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
                            covered=bool(covers(path)),
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
                        "walk_service_unavailable",
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
            pavement = payload.get("surface")
            if pavement is not None and (mode != "walk" or pavement != "pavement"):
                raise ValueError("invalid_goal")
            if not all(math.isfinite(v) for v in (x, y)):
                raise ValueError("invalid_goal")
            drive = road.levels(x, y)
            walk = road.levels(x, y, mode="walk", surface=pavement)
            levels = drive if surface == "drive" else walk
            suggestion = None
            if not levels:
                for radius in (0.75, 1.5, 3.0):
                    for direction in range(8):
                        angle = math.pi * direction / 4
                        sx, sy = x + radius * math.cos(angle), y + radius * math.sin(angle)
                        nearby = road.levels(sx, sy, mode=surface, surface=pavement)
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
                    coveredLevels=[z for z in levels if covers([[x, y, z]])],
                ),
            )

        @staticmethod
        def decode_frame(raw):
            with Image.open(BytesIO(raw)) as pic:
                sizes = (SIZE, (1280, 720), (1920, 1080)) if global_search else (SIZE,)
                if pic.format != "JPEG" or pic.size not in sizes:
                    raise ValueError("invalid_frame")
                gray = pic.convert("L")
                return np.asarray(
                    gray if gray.size == SIZE else gray.resize(SIZE, Image.Resampling.BOX)
                )

        def process(self, frame, raw):
            now = time.monotonic()
            for key, trip in list(sessions.items()):
                if now - trip.last_use > 45:
                    del sessions[key]
            if self.path in ("/probe", "/walk-probe"):
                survey = sessions.get(self.headers.get("X-World-Session"))
                if sessions and not isinstance(survey, WalkTrip):
                    return self.reply(409, dict(error="session_active"))
                if survey is not None:
                    survey.last_use = now
                    survey.previous = survey.arrival = survey.motion_origin = None
                gray = self.decode_frame(raw)
                observed = locator.describe(gray)
                if menu and menu.matches(observed):
                    return self.reply(
                        200, dict(pose=None, district=None, ambiguous=False, screen="menu_backdrop")
                    )
                if self.path == "/walk-probe":
                    result, _ = walk_fix(gray, observed)
                else:
                    result = probe_atlases(gray, locator, district_locators, observed=observed)
                if global_search and not result["pose"] and not result["ambiguous"]:
                    pose = global_search.observe(raw, gray, observed, walk_road=road)
                    result.update(
                        pose=pose,
                        district="Поиск по всей карте" if pose else None,
                        worldSearch=global_search.status(seeking_view=pose is None),
                    )
                if result["pose"] is not None:
                    if global_search:
                        global_search.recent_walk.remember(result["pose"])
                    result["startLevels"] = probe_start_levels(road, result["pose"]["eye"])
                return self.reply(200, result)
            if self.path == "/start":
                if sessions:
                    return self.reply(409, dict(error="session_active"))
                payload = json.loads(raw)
                if payload["revision"] != road.meta["placementRevision"]:
                    raise ValueError("invalid_goal")
                stops = payload.get("stops")
                mode = payload.get("mode", "drive")
                if mode == "walk":
                    if foot is None:
                        raise ValueError("walk_service_unavailable")
                    trip = WalkTrip.from_stops(road, stops if stops is not None else [payload["goal"]], foot)
                    key = secrets.token_hex(24)
                    trip.log = log_dir / (secrets.token_hex(12) + ".jsonl")
                    with trip.log.open("a", encoding="utf8") as stream:
                        print(json.dumps(dict(event="start", mode="walk", t=now,
                                              goal=trip.goal.tolist(),
                                              stops=[stop.tolist() for stop in trip.stops])), file=stream)
                    sessions[key] = trip
                    return self.reply(201, dict(session=key, mode="walk"))
                if mode != "drive":
                    raise ValueError("invalid_goal")
                if stops is not None:
                    selection = plan(road, stops, "drive", covers)
                    if selection.get("status") != "complete" or not selection["covered"]:
                        raise ValueError("outside_visual_coverage")
                trip = Trip(
                    road,
                    stops[0] if stops else payload["goal"],
                    covers,
                    access=access,
                    local_covers=global_search.covers if global_search else None,
                )
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
            if isinstance(trip, WalkTrip):
                return self.walk_frame(trip, raw, gray, now, clock, seq)
            observed = locator.describe(gray)
            at_menu = menu is not None and menu.matches(observed)
            fix = (
                dict(pose=None, district=None, ambiguous=False)
                if at_menu
                else probe_atlases(gray, locator, drive_banks, observed=observed)
            )
            passive = False
            if (
                not at_menu
                and observed is not None
                and not fix["pose"]
                and not fix["ambiguous"]
                and search_only
                and now >= getattr(trip, "next_region_search", 0)
            ):
                trip.next_region_search = now + 0.8
                fix = probe_atlases(
                    gray, locator, search_only, observed=observed, include_main=False
                )
                if fix["pose"]:
                    passive = True
            if global_search and not at_menu and not fix["pose"] and not fix["ambiguous"]:
                pose = global_search.observe(raw, gray, observed)
                if pose:
                    fix.update(pose=pose, district="Поиск по всей карте")
            response = trip.decide(None if passive else fix["pose"], clock)
            if at_menu:
                response.update(reason="menu_backdrop")
            if passive:
                response.update(pose=fix["pose"], reason="outside_visual_coverage")
            if global_search:
                if fix["pose"] and trip.extend_visual:
                    global_search.collect(raw, gray)
                response["worldSearch"] = global_search.status(
                    seeking_view=response["reason"] == "position_unknown"
                )
            response.update(district=fix["district"], ambiguous=fix["ambiguous"])
            response["stopIndex"] = trip.stop_index
            if response["pose"] and trip.path is not None:
                if getattr(trip, "_display_source", None) is not trip.path:
                    xy = trip.path[:, :2].astype(np.float32)
                    # Preserve horizontal bends and retain the real elevation of each selected vertex.
                    indices = cv2.approxPolyDP(xy, 0.35, False).reshape(-1, 2)
                    cursor = 0
                    trip.display_path = []
                    for pt in indices:
                        i = int(np.argmin(np.linalg.norm(xy[cursor:] - pt, axis=1))) + cursor
                        trip.display_path.append(trip.path[i].tolist())
                        cursor = i
                    trip._display_source = trip.path
                response.update(
                    path=trip.display_path,
                    accessMeters=trip.access_m,
                    locallyTracked=trip.progressive,
                )
            response.update(sequence=seq, computeMs=round((time.monotonic() - now) * 1000, 1))
            with trip.log.open("a", encoding="utf8") as f:
                print(
                    json.dumps(
                        dict(
                            t=now,
                            goal=trip.goal.tolist(),
                            **{
                                k: v
                                for k, v in response.items()
                                if k != "path"
                                or getattr(trip, "logged_path", None) is not trip.path
                            },
                        ),
                        allow_nan=False,
                    ),
                    file=f,
                )
            if "path" in response:
                trip.logged_path = trip.path
            self.reply(200, response)

        def walk_frame(self, trip, raw, gray, now, clock, seq):
            pose = (
                global_search.recent_walk.observe(raw, global_search.cfg, road)
                if global_search.dense_walk else None
            )
            at_menu = False
            collected = False
            normalized = False
            if pose is None and (trip.pose_bank is not None or now >= trip.next_search):
                observed = locator.describe(gray)
                at_menu = menu is not None and menu.matches(observed)
                if not at_menu and trip.pose_bank is not None and observed is not None:
                    bank = trip.pose_bank
                    normalized = trip.normalized_pose_bank
                    image = walking_exposure(gray) if normalized else gray
                    features = bank.describe(image) if normalized and image is not None else observed
                    candidate = bank.locate_features(image, *features) if image is not None and features else None
                    if candidate and bank.covers([[*candidate["eye"][:2], candidate["eye"][2] - 1.45]]) and (
                        not normalized or walk_pose_plausible(trip.last_visual_fix, candidate, clock)
                    ):
                        pose = candidate
                if not at_menu and pose is None and now >= trip.next_search:
                    trip.next_search = now + 0.65
                    fix, normalized = walk_fix(gray, observed)
                    pose = fix["pose"]
                    if normalized and pose is not None and not walk_pose_plausible(trip.last_visual_fix, pose, clock):
                        fix = dict(fix, ambiguous=True)
                        pose = None
                    if pose is not None:
                        trip.pose_bank = walking_banks.get(fix["district"], locator)
                        trip.normalized_pose_bank = normalized
                    elif not fix["ambiguous"]:
                        pose = global_search.observe(raw, gray, observed)
                        collected = pose is None
                        if pose is not None:
                            trip.pose_bank = global_search.bank
                            trip.normalized_pose_bank = normalized = False
                    if pose is not None:
                        global_search.recent_walk.remember(pose)
            if pose is not None:
                trip.last_visual_fix = clock, pose["eye"], pose["heading"]
            if pose is None and not at_menu and not collected:
                global_search.collect(raw, gray)
            response = trip.decide(pose, clock)
            if at_menu:
                response["reason"] = "menu_backdrop"
            response.update(
                sequence=seq,
                computeMs=round((time.monotonic() - now) * 1000, 1),
                worldSearch=global_search.status(seeking_view=pose is None),
            )
            with trip.log.open("a", encoding="utf8") as stream:
                row = {k: v for k, v in response.items() if k != "path" or trip.path is not getattr(trip, "logged_path", None)}
                print(json.dumps(dict(t=now, **row), allow_nan=False), file=stream)
                trip.logged_path = trip.path
            return self.reply(200, response)

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--world-search-config", type=Path)
    p.add_argument("--menu-background", type=Path)
    p.add_argument("--atlas", type=Path, required=True)
    p.add_argument("--logs", type=Path, required=True)
    p.add_argument("--planner", default="http://127.0.0.1:8817")
    p.add_argument("--origin", default="http://127.0.0.1:3015")
    p.add_argument("--preview-origin", action="append", default=[], type=preview_origin)
    p.add_argument(
        "--search-atlas", action="append", nargs=2, default=[], metavar=("DISTRICT", "NPZ")
    )
    p.add_argument(
        "--walk-weather-atlas", action="append", nargs=2, default=[], metavar=("LABEL", "NPZ")
    )
    p.add_argument("--drive-region", action="append", default=[], metavar="DISTRICT")
    p.add_argument("--search-hfov", action="append", type=float, default=[])
    p.add_argument("--detail-folder", type=Path)
    p.add_argument("--texture-pack", type=Path, help="Street textures for the same map revision")
    p.add_argument("--terrain-overview", type=Path, help="Verified map overview output directory")
    p.add_argument("--water", type=Path)
    p.add_argument("--port", type=int, default=8849)
    serve(p.parse_args())
