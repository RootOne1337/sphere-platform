"""Serve the local Black Russia point-to-point map and static geometry queries."""

import argparse
import json
import mimetypes
import shutil
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from scripts.pilot.world_map_lab.detail_scene_service import read_scene, scene_files
from scripts.pilot.world_map_lab.world_navmesh import Network, checksum
from scripts.pilot.world_map_lab.world_trip import TripPlanner


class PlannerServer(ThreadingHTTPServer):
    # Avoid SYN retries when multiple clients request a route at once.
    request_queue_size = 64


def serve(folder, port):
    with ExitStack() as stack:
        nets = {mode: stack.enter_context(Network(folder, mode)) for mode in ("drive", "walk")}
        if nets["drive"].meta["geometrySha256"] != nets["walk"].meta["geometrySha256"]:
            raise ValueError("travel modes are from different source revisions")
        trip = TripPlanner(nets, folder)
        files = {
            "/": Path(__file__).with_name("world_nav_planner.html"),
            "/world.png": folder / "atlas/ariane-world-top.png",
            "/drive.png": folder / "drive-overlay.png",
            "/walk.png": folder / "walk-overlay.png",
        }
        for file in files.values():
            if not file.is_file():
                raise FileNotFoundError(file)

        files.update(scene_files(folder, nets))
        examples = {}
        for name in (
            "navigation-report.html",
            "street-comparison.jpg",
            "world-navigation-audit.json",
            "fixed-pair-recheck.json",
            "world-gap-review.json",
        ):
            path = folder / name
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
        audit_file = folder / "world-navigation-audit.json"
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
            if all(mixed["meshes"].get(m) == checksum(folder / f"{m}.nav.zip") for m in nets):
                examples["trip"] = {key: mixed[key] for key in ("start", "vehicle", "end")}

        class Handler(BaseHTTPRequestHandler):
            disable_nagle_algorithm = True

            def send_json(self, document, status=200):
                body = json.dumps(document, ensure_ascii=False, allow_nan=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                req = urlsplit(self.path)
                if req.path in files:
                    path = files[req.path]
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        (
                            "text/html; charset=utf-8"
                            if path.suffix == ".html"
                            else mimetypes.guess_type(path)[0] or "application/octet-stream"
                        ),
                    )
                    self.send_header("Content-Length", str(path.stat().st_size))
                    self.end_headers()
                    with path.open("rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                    return
                if req.path == "/api/world":
                    self.send_json(
                        {
                            **{m: n.meta for m, n in nets.items()},
                            "examples": list(examples),
                            "review": "/review" in files,
                            "detail": "/detail" in files,
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
                        self.send_header("Content-Length", str(len(body)))
                        if encoding:
                            self.send_header("Content-Encoding", encoding)
                        self.end_headers()
                        self.wfile.write(body)
                        return
                if req.path not in ("/api/levels", "/api/path", "/api/example"):
                    self.send_error(404)
                    return
                try:
                    args = parse_qs(req.query, strict_parsing=True, max_num_fields=4)
                    mode = args["mode"][0]
                    nav = nets["walk" if mode == "trip" else mode]
                    if req.path == "/api/example":
                        self.send_json(examples[mode])
                    elif req.path == "/api/levels":
                        self.send_json(
                            {"levels": nav.levels(float(args["x"][0]), float(args["y"][0]))}
                        )
                    else:
                        ends = [[float(n) for n in args[k][0].split(",")] for k in ("start", "end")]
                        vehicle = args.get("vehicle")
                        if vehicle and mode != "trip":
                            raise ValueError("vehicle requires mixed mode")
                        point = [float(n) for n in vehicle[0].split(",")] if vehicle else None
                        self.send_json(
                            trip.route(*ends, vehicle=point) if mode == "trip" else nav.route(*ends)
                        )
                except (KeyError, TypeError, ValueError, OverflowError):
                    self.send_json({"error": "invalid query"}, 400)

        http = stack.enter_context(PlannerServer(("127.0.0.1", port), Handler))
        print(f"http://127.0.0.1:{http.server_port}/", flush=True)
        http.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8817)
    args = parser.parse_args()
    serve(args.folder, args.port)
