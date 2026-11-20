"""Read a bounded neighborhood of the offline geometry pack for the local viewer."""

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from pathlib import Path

VENDOR = {
    "three.module.js": "build/three.module.js",
    "three.core.js": "build/three.core.js",
    "GLTFLoader.js": "examples/jsm/loaders/GLTFLoader.js",
    "OrbitControls.js": "examples/jsm/controls/OrbitControls.js",
    "BufferGeometryUtils.js": "examples/jsm/utils/BufferGeometryUtils.js",
}


def recorded_movie(folder, item):
    ident = item["id"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,70}", ident):
        raise ValueError("invalid run identifier")
    archive = folder / "runs" / ident
    if not (archive / "film.json").is_file():
        return None
    receipt = json.loads((archive / "film.json").read_bytes())
    if receipt["mode"] != "recorded_rgb_control" or receipt["result"] != item["outcome"]:
        return None
    for file, expected in (
        (archive / "film.mp4", receipt["movieSha256"]),
        (archive / "telemetry.jsonl", receipt["sourceHashes"]["telemetry.jsonl"]),
        (archive / "route.json", receipt["sourceHashes"]["attemptRoute"]),
    ):
        with file.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("attempt movie or source changed")
    return archive / "film.mp4"


def journey_files(folder, revision):
    assets = (
        "route.json",
        "premier.glb",
        "faggio.glb",
        "vehicles.json",
        "horizon.bin",
        "terrain.jpg",
    )
    if any(not (folder / name).is_file() for name in assets):
        return {}
    config = (folder / "route.json").read_bytes()
    try:
        if json.loads(config).get("revision") != revision:
            return {}
    except (ValueError, AttributeError):
        return {}
    files = {"/journey/" + name: folder / name for name in assets}
    files["/explore"] = Path(__file__).with_name("world_journey.html")
    for name in ("app", "scene", "path", "vehicle"):
        files["/journey/" + name + ".mjs"] = Path(__file__).with_name("journey_" + name + ".mjs")
    try:
        receipt = json.loads((folder / "film.json").read_bytes())
        movie = folder / "film.mp4"
        if receipt.get("routeSha256") == hashlib.sha256(config).hexdigest():
            with movie.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == receipt.get("movieSha256"):
                    files["/journey/film.mp4"] = movie
    except (ValueError, OSError, AttributeError):
        pass
    if all(
        (folder / name).is_file()
        for name in ("gameplay.html", "gameplay-proof.json", "engine-boot.json")
    ):
        files["/gameplay"] = folder / "gameplay.html"
        for name in (
            "engine-boot.json",
            "gameplay-proof.json",
            "displacement-probes.json",
            "displacement-holdout.json",
            "native-boot-gxt/engine-boot.json",
            "native-trace/engine-boot.json",
        ):
            if (folder / name).is_file():
                files["/journey/" + name] = folder / name
    if (folder / "native-stand.html").is_file():
        files["/classic-game"] = folder / "native-stand.html"
    report = folder / "journey-report.json"
    try:
        results = json.loads(report.read_bytes())
        for group in ("city", "cross"):
            movie = recorded_movie(folder, results[group])
            if movie:
                files[f"/journey/{group}-camera.mp4"] = movie
        for name in ("journey-report.html", "journey-overview.jpg"):
            if (folder / name).is_file():
                files["/journey/" + name] = folder / name
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        report = folder / "taxi-report.json"
        data = json.loads(report.read_bytes())
        if data["revision"] == revision and (movie := recorded_movie(folder, data["featured"])):
            files["/journey/taxi-camera.mp4"] = movie
            files["/journey/taxi-report.json"] = report
            files["/taxi-report"] = Path(__file__).with_name("taxi_report.html")
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        record = folder / "scooter4-observations.mp4"
        info = json.loads(record.with_suffix(".json").read_bytes())
        data = (folder.parent / "first-person" / "shortlisted-game-replay.json").read_bytes()
        if (
            info["mode"] == "archived_game_observation"
            and info["observationsSha256"] == hashlib.sha256(data).hexdigest()
            and info["sourceSha256"] == json.loads(data)["videoSha256"]
        ):
            with record.open("rb") as stream:
                if info["movieSha256"] == hashlib.file_digest(stream, "sha256").hexdigest():
                    files["/journey/scooter4-observations.mp4"] = record
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return files


def scene_files(folder, nets):
    files = {}
    review = folder / "review.json"
    if (
        review.is_file()
        and (folder / "navigation-report.html").is_file()
        and all(
            v["manifest"] == nets[m].meta
            for m, v in json.loads(review.read_bytes())["summary"].items()
        )
    ):
        files["/review.json"] = review
        files["/review"] = folder / "navigation-report.html"
    if (folder / "detail-scene.sqlite").is_file():
        uri = (folder / "detail-scene.sqlite").resolve().as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            record = json.loads(db.execute("select value from meta").fetchone()[0])
        if record["revision"] != nets["drive"].meta["placementRevision"]:
            return files
        vendor = folder / "viewer-deps/node_modules/three"
        package = vendor / "package.json"
        if package.exists() and json.loads(package.read_bytes())["version"] == "0.180.0":
            files["/detail"] = Path(__file__).with_name("world_detail.html")
            files.update(journey_files(folder / "journey", record["revision"]))
            for name, rel in VENDOR.items():
                path = "/detail/utils/" if name == "BufferGeometryUtils.js" else "/detail/js/"
                files[path + name] = vendor / rel
    receipt = folder / "first-person" / "published.json"
    if receipt.is_file():
        try:
            record = json.loads(receipt.read_bytes())
        except (OSError, ValueError):
            return files
        if not isinstance(record, dict):
            return files
        if (
            record.get("revision") == nets["drive"].meta["placementRevision"]
            and isinstance(record.get("files"), dict)
            and "report.html" in record["files"]
        ):
            media = {}
            for name, sha in record["files"].items():
                if not re.fullmatch(
                    r"report-[a-z0-9-]+\.mp4|game-(?:map-comparison|coverage)\.png|report\.html",
                    name,
                ):
                    break
                path = receipt.parent / name
                if not path.is_file():
                    break
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != sha:
                        break
                media["/first-person/" + name] = path
            else:
                files.update(media)
    return files


def read_scene(folder, req, args):
    resource = re.fullmatch(r"/detail/(model/([0-9]{1,6})\.glb|texture/([a-f0-9]{64})\.png)", req)
    if not resource and req != "/api/neighborhood":
        return None
    uri = (folder / "detail-scene.sqlite").resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        if resource:
            model, tex = resource.group(2, 3)
            row = (
                db.execute("select glb from model where id=?", (int(model),))
                if model
                else db.execute("select png from texture where key=?", (tex,))
            ).fetchone()
            if not row:
                return 404, b"", "text/plain", None
            return (
                200,
                row[0],
                "model/gltf-binary" if model else "image/png",
                "gzip" if model else None,
            )
        x, y, z = [float(args[k][0]) for k in ("x", "y", "z")]
        radius = int(args.get("radius", ["96"])[0])
        if radius not in (48, 96, 160, 320) or not all(
            math.isfinite(v) and abs(v) < 10000 for v in (x, y, z)
        ):
            raise ValueError("invalid detail viewport")
        groups = {}
        rows = db.execute(
            """select i.model,m.name,m.triangles,i.x,i.y,i.z,i.qx,i.qy,i.qz,i.qw
        from spatial s join instance i on i.id=s.id join model m on m.id=i.model
        where minx<=? and maxx>=? and miny<=? and maxy>=? and minz<=? and maxz>=? order by i.model,i.id""",
            (x + radius, x - radius, y + radius, y - radius, z + 100, z - 60),
        )
        for ident, name, tris, *transform in rows:
            group = groups.setdefault(
                ident, {"id": ident, "name": name, "triangles": tris, "instances": []}
            )
            group["instances"].append(transform)
        return (
            200,
            json.dumps(list(groups.values()), separators=(",", ":")).encode(),
            "application/json",
            None,
        )
