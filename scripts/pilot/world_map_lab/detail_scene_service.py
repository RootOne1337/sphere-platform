"""Read a bounded neighborhood of the offline geometry pack for the local viewer."""

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
            for name, rel in VENDOR.items():
                path = "/detail/utils/" if name == "BufferGeometryUtils.js" else "/detail/js/"
                files[path + name] = vendor / rel
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
        if radius not in (48, 96, 160) or not all(
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
