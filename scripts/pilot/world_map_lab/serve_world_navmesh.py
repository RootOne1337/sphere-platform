"""Serve the local Black Russia point-to-point map and static geometry queries."""

import argparse
import json
import math
import mimetypes
import re
import shutil
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import numpy as np

from scripts.pilot.world_map_lab.detail_scene_service import read_scene, scene_files
from scripts.pilot.world_map_lab.journey_runs import JourneyRuns
from scripts.pilot.world_map_lab.pedestrian_surface import FootSurface
from scripts.pilot.world_map_lab.taxi_surface import TaxiSurface
from scripts.pilot.world_map_lab.world_navmesh import FLOATS, Network, checksum
from scripts.pilot.world_map_lab.world_trip import TripPlanner


def movie_range(header, size):
    match = re.fullmatch(r"bytes=(\d{0,18})-(\d{0,18})", header.strip())
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError("unsupported byte range")
    start, end = match.groups()
    if start:
        lo = int(start)
        hi = min(size - 1, int(end)) if end else size - 1
    else:
        lo = max(0, size - int(end))
        hi = size - 1
    if not 0 <= lo <= hi < size:
        raise ValueError("range outside movie")
    return lo, hi


def movement_step(network, start, xy, mode):
    if len(start) != 3 or len(xy) != 2 or not all(map(math.isfinite, (*start, *xy))):
        raise ValueError("invalid movement coordinates")
    step = math.dist(start[:2], xy)
    if step > 6 or mode not in ("walk", "drive"):
        raise ValueError("invalid movement step")
    if hasattr(network.dll, "move_body"):
        xyz = np.asarray(start, dtype=np.float32)
        dest = np.asarray([*xy, start[2]], dtype=np.float32)
        out = np.zeros(3, np.float32)
        ok = network.dll.move_body(
            network.handle,
            xyz.ctypes.data_as(FLOATS),
            dest.ctypes.data_as(FLOATS),
            out.ctypes.data_as(FLOATS),
        )
        if ok < 0:
            raise RuntimeError("local motion query failed")
        moved = ok == 1 and math.dist(start[:2], out[:2]) > max(0.0001, step * 0.02)
        return {"position": out.tolist() if moved else start, "moved": bool(moved)}
    for height in sorted(network.levels(*xy), key=lambda z: abs(z - start[2])):
        if abs(height - start[2]) > 0.55 + step * (0.7 if mode == "walk" else 0.45):
            continue
        dest = [*xy, height]
        route = network.route(start, dest)
        if (
            route["status"] == "complete"
            and route["path"]
            and route["length"] <= 1.15 * math.dist(start, dest) + 0.12
            and math.dist(route["path"][-1], dest) < 0.15
        ):
            return {"position": route["path"][-1], "moved": True}
    return {"position": start, "moved": False}


class PlannerServer(ThreadingHTTPServer):
    # Avoid SYN retries when multiple clients request a route at once.
    request_queue_size = 64


def pedestrian_release(folder):
    selection = folder / "pedestrian-release.json"
    if not selection.is_file():
        return folder
    name = json.loads(selection.read_bytes())["release"]
    if (
        not isinstance(name, str)
        or not name
        or not all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in name)
    ):
        raise ValueError("invalid pedestrian release name")
    return folder / "pedestrian-releases" / name


def serve(folder, port, adapter=None, *, walk_folder=None):
    walk_folder = pedestrian_release(folder) if walk_folder is None else walk_folder
    with ExitStack() as stack:
        nets = {
            "drive": stack.enter_context(Network(folder, "drive", adapter=adapter)),
            "walk": stack.enter_context(
                Network(walk_folder, "walk", adapter=adapter if walk_folder == folder else None)
            ),
        }
        if any(
            nets["drive"].meta[key] != nets["walk"].meta[key]
            for key in ("geometrySha256", "placementRevision", "bounds")
        ):
            raise ValueError("travel modes are from different source revisions")
        trip = TripPlanner(nets, folder, walk_folder=walk_folder)
        accessible = TaxiSurface(trip)
        walk = nets["walk"]
        pavement = None
        if walk.meta.get("walkMaterialVersion") and hasattr(walk.dll, "query_pavement_path"):
            pavement = FootSurface(
                folder, SimpleNamespace(meta=walk.meta), pavement=True, check_visibility=False
            )
            stack.callback(pavement.close)
        files = {
            "/": Path(__file__).with_name("world_nav_planner.html"),
            "/world.png": folder / "atlas/ariane-world-top.png",
            "/drive.png": folder / "drive-overlay.png",
            "/walk.png": walk_folder / "walk-overlay.png",
        }
        for file in files.values():
            if not file.is_file():
                raise FileNotFoundError(file)

        files.update(scene_files(folder, nets))
        examples = {}
        paved_example = walk_folder / "pavement-example.json"
        if pavement and paved_example.is_file():
            case = json.loads(paved_example.read_bytes())
            if case.get("geometrySha256") == walk.meta["geometrySha256"]:
                examples["pavement"] = {key: case[key] for key in ("start", "end")}
        for name in (
            "navigation-report.html",
            "street-comparison.jpg",
            "world-navigation-audit.json",
            "fixed-pair-recheck.json",
            "world-gap-review.json",
        ):
            location = walk_folder if name == "world-navigation-audit.json" else folder
            path = location / name
            if path.is_file():
                files["/" + name] = path
        for district in ("", "batyrevo/", "uzhny/"):
            for name in (
                "ariane-world-map.html",
                "ariane-world-3d.html",
                "ariane-world-color-3d.png",
                "ariane-world-top.png",
                "ariane-world-road-overlay.png",
                "ariane-world-map-with-roads.png",
            ):
                relative = "atlas/" + district + name
                path = folder / relative
                if path.is_file():
                    files["/" + relative] = path
        audit_file = walk_folder / "world-navigation-audit.json"
        if audit_file.is_file():
            audit = json.loads(audit_file.read_bytes())
            for mode, network in nets.items():
                entry = audit[mode]
                if entry["manifest"] != network.meta:
                    continue
                route = next((r for r in entry["routeExamples"] if r["status"] == "complete"), None)
                if route:
                    examples[mode] = {"start": route["start"], "end": route["end"]}
        cases_file = folder / "fixed-pair-recheck.json"
        if cases_file.is_file() and "drive" in examples and "walk" in examples:
            cases = json.loads(cases_file.read_bytes())
            transfer = next((t for t in cases["trips"] if t["modes"] == ["drive", "walk"]), None)
            if transfer:
                examples["trip"] = {"start": transfer["start"], "end": transfer["goal"]}

        mixed_file = folder / "mixed-validation.json"
        if mixed_file.is_file():
            mixed = json.loads(mixed_file.read_bytes())
            mesh_files = {"drive": folder / "drive.nav.zip", "walk": walk_folder / "walk.nav.zip"}
            if all(
                mixed["meshes"].get(mode) == checksum(file) for mode, file in mesh_files.items()
            ):
                examples["trip"] = {key: mixed[key] for key in ("start", "vehicle", "end")}
                examples["taxi"] = {key: mixed[key] for key in ("start", "end")}

        parked = None
        if "/journey/route.json" in files:
            scene = json.loads(files["/journey/route.json"].read_bytes())
            spot = scene.get("vehicle")
            if (
                scene.get("revision") == nets["drive"].meta["placementRevision"]
                and isinstance(spot, list)
                and len(spot) == 3
                and all(isinstance(n, (float, int)) and math.isfinite(n) for n in spot)
                and any(abs(z - spot[2]) <= 0.375 for z in nets["drive"].levels(*spot[:2]))
            ):
                parked = spot

        runs = JourneyRuns(folder, port, adapter)
        stack.callback(runs.close)

        class Handler(BaseHTTPRequestHandler):
            disable_nagle_algorithm = True

            def send_json(self, document, status=200):
                body = json.dumps(document, ensure_ascii=False, allow_nan=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                req = urlsplit(self.path)
                if (
                    req.path not in ("/api/journey/start", "/api/journey/stop")
                    or "/explore" not in files
                ):
                    self.send_error(404)
                    return
                if (
                    self.headers.get("Origin")
                    not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
                    or self.headers.get_content_type() != "application/json"
                ):
                    self.send_error(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 4096:
                        raise ValueError("invalid request size")
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict):
                        raise ValueError("invalid request")
                    if req.path.endswith("/stop"):
                        self.send_json(runs.stop(data["id"]))
                        return
                    mode = data.get("mode", "trip")
                    if mode == "taxi" and (
                        "start" not in data or "end" not in data or "vehicle" in data
                    ):
                        raise ValueError("taxi mode requires both endpoints and automatic pickup")
                    if "start" not in data and "end" not in data:
                        route = json.loads(files["/journey/route.json"].read_bytes())
                    elif mode == "taxi":
                        route = trip.taxi(data["start"], data["end"])
                    elif mode == "trip":
                        route = trip.route(data["start"], data["end"], vehicle=data.get("vehicle"))
                    else:
                        result = nets[mode].route(data["start"], data["end"])
                        route = {
                            "status": result["status"],
                            "legs": [{"mode": mode, "path": result["path"]}],
                        }
                    self.send_json(runs.start(route, data.get("model", "faggio")), 201)
                except (ValueError, KeyError, TypeError, OverflowError):
                    self.send_json(
                        {"error": "Неверные точки, транспорт или недоступный маршрут"}, 400
                    )
                except RuntimeError as exc:
                    self.send_json({"error": str(exc)}, 409)

            def do_GET(self):
                req = urlsplit(self.path)
                if req.path in ("/api/journey/state", "/api/journey/trace"):
                    try:
                        ident = parse_qs(req.query, strict_parsing=True, max_num_fields=1)["id"][0]
                        if req.path.endswith("/state"):
                            self.send_json(runs.state(ident))
                        else:
                            path = runs.directory(ident) / "telemetry.jsonl"
                            if not path.is_file():
                                raise KeyError("no telemetry")
                            with path.open("rb") as stream:
                                size = path.stat().st_size
                                self.send_response(200)
                                self.send_header("Content-Type", "application/x-ndjson")
                                self.send_header("Content-Length", str(size))
                                self.end_headers()
                                remaining = size
                                while remaining:
                                    chunk = stream.read(min(65536, remaining))
                                    if not chunk:
                                        break
                                    self.wfile.write(chunk)
                                    remaining -= len(chunk)
                    except (KeyError, ValueError, TypeError):
                        self.send_json({"error": "Попытка не найдена"}, 404)
                    return
                if req.path in files:
                    path = files[req.path]
                    size = path.stat().st_size
                    request_range = self.headers.get("Range") if path.suffix == ".mp4" else None
                    try:
                        lo, hi = (
                            movie_range(request_range, size) if request_range else (0, size - 1)
                        )
                    except ValueError:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206 if request_range else 200)
                    if path.suffix == ".mp4":
                        self.send_header("Accept-Ranges", "bytes")
                    if request_range:
                        self.send_header("Content-Range", f"bytes {lo}-{hi}/{size}")
                    self.send_header(
                        "Content-Type",
                        (
                            "text/html; charset=utf-8"
                            if path.suffix == ".html"
                            else "text/javascript"
                            if path.suffix in (".js", ".mjs")
                            else mimetypes.guess_type(path)[0] or "application/octet-stream"
                        ),
                    )
                    self.send_header("Content-Length", str(hi - lo + 1))
                    self.end_headers()
                    with path.open("rb") as f:
                        try:
                            if not request_range:
                                shutil.copyfileobj(f, self.wfile)
                            else:
                                f.seek(lo)
                                remaining = hi - lo + 1
                                while remaining:
                                    chunk = f.read(min(remaining, 256 * 1024))
                                    if not chunk:
                                        break
                                    self.wfile.write(chunk)
                                    remaining -= len(chunk)
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                            return
                    return
                if req.path == "/api/world":
                    self.send_json(
                        {
                            **{m: n.meta for m, n in nets.items()},
                            "examples": list(examples),
                            "pavement": pavement is not None,
                            "parkedVehicle": parked,
                            "review": "/review" in files,
                            "detail": "/detail" in files,
                            "explore": "/explore" in files,
                            "gameplay": "/gameplay" in files,
                            "classicGame": "/classic-game" in files,
                            "journeyReport": "/journey/journey-report.html" in files,
                            "archiveMovie": "/journey/scooter4-observations.mp4" in files,
                            "crossMovie": "/journey/cross-camera.mp4" in files,
                            "taxiReport": "/taxi-report" in files,
                            "journeyMovie": "/journey/film.mp4" in files,
                            "firstPersonReport": "/first-person/report.html" in files,
                            "report": "/navigation-report.html" in files,
                        }
                    )
                    return
                if "/detail" in files and (
                    req.path.startswith("/detail/") or req.path == "/api/neighborhood"
                ):
                    try:
                        resource = read_scene(
                            folder,
                            req.path,
                            parse_qs(req.query, strict_parsing=True, max_num_fields=4),
                        )
                    except (ValueError, KeyError, OverflowError):
                        self.send_json({"error": "invalid detail request"}, 400)
                        return
                    if resource is not None:
                        code, body, mime, encoding = resource
                        self.send_response(code)
                        self.send_header("Content-Type", mime)
                        if req.path.startswith("/detail/texture/"):
                            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                        self.send_header("Content-Length", str(len(body)))
                        if encoding:
                            self.send_header("Content-Encoding", encoding)
                        self.end_headers()
                        self.wfile.write(body)
                        return
                if req.path == "/api/taxi-surface.png":
                    try:
                        value = parse_qs(req.query, strict_parsing=True, max_num_fields=1)["start"][
                            0
                        ]
                        png = accessible.png([float(v) for v in value.split(",")])
                    except (ValueError, KeyError, OverflowError):
                        self.send_json({"error": "invalid origin"}, 400)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(png)))
                    self.end_headers()
                    self.wfile.write(png)
                    return
                if req.path not in ("/api/levels", "/api/path", "/api/example", "/api/step"):
                    self.send_error(404)
                    return
                try:
                    args = parse_qs(req.query, strict_parsing=True, max_num_fields=4)
                    mode = args["mode"][0]
                    nav = nets["walk" if mode in ("trip", "taxi") else mode]
                    if req.path == "/api/example":
                        surface = args.get("surface")
                        key = "pavement" if mode == "walk" and surface == ["pavement"] else mode
                        self.send_json(examples[key])
                    elif req.path == "/api/step":
                        start, xy = (
                            [float(n) for n in args[k][0].split(",")] for k in ("start", "xy")
                        )
                        self.send_json(movement_step(nav, start, xy, mode))
                    elif req.path == "/api/levels":
                        self.send_json(
                            {"levels": nav.levels(float(args["x"][0]), float(args["y"][0]))}
                        )
                    else:
                        ends = [[float(n) for n in args[k][0].split(",")] for k in ("start", "end")]
                        vehicle = args.get("vehicle")
                        if vehicle and mode != "trip":
                            raise ValueError("vehicle requires mixed mode")
                        surface = args.get("surface")
                        if surface is not None and (mode != "walk" or surface != ["pavement"]):
                            raise ValueError("expected pavement restriction on a walking route")
                        point = [float(n) for n in vehicle[0].split(",")] if vehicle else None
                        result = (
                            trip.taxi(*ends)
                            if mode == "taxi"
                            else trip.route(*ends, vehicle=point)
                            if mode == "trip"
                            else nav.route(*ends, pavement=surface is not None)
                        )
                        if surface and result["status"] == "complete":
                            if pavement is None or not pavement.paved_route(
                                [ends[0], *result["path"], ends[1]]
                            ):
                                result = dict(status="surface_unconfirmed", length=0, path=[])
                        self.send_json(result)
                except (KeyError, TypeError, ValueError, OverflowError):
                    self.send_json({"error": "invalid query"}, 400)

        http = stack.enter_context(PlannerServer(("127.0.0.1", port), Handler))
        print(f"http://127.0.0.1:{http.server_port}/", flush=True)
        http.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8817)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument(
        "--walk-folder", type=Path, help="Preview a separately baked pedestrian release"
    )
    args = parser.parse_args()
    serve(args.folder, args.port, args.adapter, walk_folder=args.walk_folder)
