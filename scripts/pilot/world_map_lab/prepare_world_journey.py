"""Prepare a cross-world mixed trip, original parked car, and distant terrain for the local simulator."""

import argparse
import gzip
import hashlib
import json
import math
import struct
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.pilot.world_map_lab.build_detail_scene import mesh_file
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter
from scripts.pilot.world_map_lab.render_ariane_world import Textures
from scripts.pilot.world_map_lab.world_navmesh import Network
from scripts.pilot.world_map_lab.world_trip import TripPlanner


def pedestrian_near(walk, drive, road):
    for radius in (65, 90, 35, 130):
        for a in np.arange(16) * math.pi / 8:
            x, y = road[0] + radius * math.cos(a), road[1] + radius * math.sin(a)
            for z in sorted(walk.levels(x, y), key=lambda h: abs(road[2] - h)):
                if abs(z - road[2]) > 6 or any(abs(h - z) < 0.5 for h in drive.levels(x, y)):
                    continue
                if walk.route([x, y, z], road)["status"] == "complete":
                    yield [x, y, z]


def select_trip(folder):
    cases = json.loads((folder / "fixed-pair-recheck.json").read_bytes())
    ends = [
        pt
        for r in cases["drive"]["pairs"]
        if r["after"] == "complete"
        for pt in [r["start"], r["end"]]
    ]
    pairs = sorted(
        (
            (a, b)
            for a in ends
            if a[0] > 1800 and a[1] < -1600
            for b in ends
            if b[0] < -1700 and b[1] > 1700
        ),
        key=lambda p: -math.dist(*p),
    )
    with ExitStack() as stack:
        nets = {m: stack.enter_context(Network(folder, m)) for m in ("drive", "walk")}
        trip = TripPlanner(nets, folder)
        for a, b in pairs:
            if nets["drive"].route(a, b)["status"] != "complete":
                continue
            start = next(pedestrian_near(nets["walk"], nets["drive"], a), None)
            if start is None:
                continue
            for end in pedestrian_near(nets["walk"], nets["drive"], b):
                route = trip.route(start, end, a)
                if [leg["mode"] for leg in route["legs"]] != ["walk", "drive", "walk"]:
                    continue
                if min(route["legs"][0]["length"], route["legs"][2]["length"]) < 25:
                    continue
                if (
                    max(
                        math.dist(one["path"][-1], two["path"][0])
                        for one, two in zip(route["legs"], route["legs"][1:])
                    )
                    > 0.38
                ):
                    continue
                return dict(
                    start=start,
                    vehicle=a,
                    end=end,
                    revision=nets["drive"].meta["placementRevision"],
                    **route,
                )
    raise ValueError("no connected cross-world trip")


def vehicle(source, adapter, out, kind):
    if kind not in ("premier", "faggio"):
        raise ValueError("unexpected vehicle")
    entries = {(kind + ext).encode() for ext in (".dff", ".txd")}
    g = load_local_adapter(source, adapter)
    from gtaLib.dff import dff

    path = source / "models/gta3.img"
    with path.open("rb") as stream:
        if stream.read(4) != b"VER2":
            raise ValueError("expected IMG v2")
        count = struct.unpack("<I", stream.read(4))[0]
        archive = {
            raw.split(b"\0", 1)[0].decode("ascii").lower(): (
                path,
                sector * 2048,
                (physical or logical) * 2048,
            )
            for sector, logical, physical, raw in struct.iter_unpack(
                "<IHH24s", stream.read(count * 32)
            )
            if raw.split(b"\0", 1)[0] in entries
        }
    blob = g.read_entry(archive, kind + ".dff")
    model = dff()
    model.load_memory(blob)
    textures = Textures(source, g, texture_size=512)
    textures.entries = archive

    def material(item):
        name = item.textures[0].name.lower() if item.textures else ""
        rgb = tuple(item.color[:3])
        alpha = item.color[3]
        color = None
        if rgb == (60, 255, 0):
            color = (153, 65, 40, 255) if kind == "faggio" else (51, 78, 96, 255)
        elif rgb == (255, 0, 175):
            color = (48, 54, 59, 255)
        elif name == "vehiclelights128":
            color = (
                (155, 40, 33, 255) if rgb in ((255, 60, 0), (0, 255, 200)) else (189, 183, 168, 255)
            )
        elif alpha < 220:
            color = (92, 126, 140, 104)
        elif name == "vehicletyres128":
            color = (35, 36, 37, 255)
        elif name == "vehiclegeneric256":
            color = (79, 82, 84, 255)
        elif name in ("vehiclesteering128", "vehicledash32"):
            color = (45, 46, 44, 255)
        return (
            np.array(color, np.uint8).reshape(1, 1, 4)
            if color
            else textures.material(kind, item, ())
        )

    parts = []
    groups = []
    sockets = {}
    for node in model.clumps:
        for i, frame in enumerate(node.frame_list):
            origin = np.zeros(3)
            idx = i
            while idx > 0:
                f = node.frame_list[idx]
                origin = origin @ np.asarray(f.rotation_matrix) + np.asarray(f.position)
                idx = f.parent
            sockets[frame.name] = origin.tolist()
        for atomic in node.atomic_list:
            frame = node.frame_list[atomic.frame]
            piece = frame.name
            if (
                "_dam" in frame.name
                or "vlo" in frame.name
                or "wind" in frame.name
                and "dummy" in frame.name
            ):
                continue
            geom = node.geometry_list[atomic.geometry]
            vert = np.array(geom.vertices)
            index = atomic.frame
            while index > 0:
                frame = node.frame_list[index]
                vert = vert @ np.asarray(frame.rotation_matrix) + np.asarray(frame.position)
                index = frame.parent
            faces = np.array(
                [(t.a, t.b, t.c, t.material) for t in geom.triangles], dtype=int
            ).reshape(-1, 4)
            if not len(faces):
                continue
            uv = np.asarray(geom.uv_layers[0]) if geom.uv_layers else np.zeros((len(vert), 2))
            colors = {i: material(geom.materials[i]) for i in np.unique(faces[:, 3])}
            groups.append((piece, len(colors)))
            parts.append((vert, uv, faces[:, :3], faces[:, 3], colors))
            if piece == "wheel":
                wheels = {
                    f.name: np.asarray(f.position)
                    for f in node.frame_list
                    if f.name.startswith("wheel_") and f.name.endswith("_dummy")
                }
                for name, center in wheels.items():
                    if name == "wheel_rf_dummy":
                        continue
                    copy = vert - wheels["wheel_rf_dummy"]
                    mirror = name in ("wheel_lf_dummy", "wheel_lb_dummy")
                    if mirror:
                        copy[:, 0] *= -1
                    groups.append((name, len(colors)))
                    parts.append(
                        (
                            copy + center,
                            uv,
                            faces[:, [0, 2, 1]] if mirror else faces[:, :3],
                            faces[:, 3],
                            colors,
                        )
                    )

    def tex(img):
        import base64
        import io

        stream = io.BytesIO()
        Image.fromarray(img.astype(np.uint8)).save(stream, format="PNG")
        key = hashlib.sha256(stream.getvalue()).hexdigest()
        urls[key] = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()
        return key, np.min(img[:, :, 3]) < 125

    urls = {}
    glb, lo, hi, _ = mesh_file(parts, tex)
    raw = gzip.decompress(glb)
    size = struct.unpack_from("<I", raw, 12)[0]
    spec = json.loads(raw[20 : 20 + size])
    for mat in spec["materials"]:
        if mat.get("alphaMode") == "MASK":
            mat["alphaMode"] = "BLEND"
            mat.pop("alphaCutoff", None)
    primitives = spec["meshes"][0]["primitives"]
    cursor = 0
    spec["meshes"] = []
    spec["nodes"] = []
    for idx, (piece, count) in enumerate(groups):
        spec["meshes"].append({"primitives": primitives[cursor : cursor + count]})
        spec["nodes"].append({"mesh": idx, "name": piece})
        cursor += count
    if cursor != len(primitives):
        raise ValueError("vehicle part binding mismatch")
    spec["scenes"][0]["nodes"] = list(range(len(groups)))
    for image in spec["images"]:
        image["uri"] = urls[Path(image["uri"]).stem]
    meta = json.dumps(spec, separators=(",", ":")).encode()
    meta += b" " * (-len(meta) % 4)
    payload = raw[20 + size :]
    (out / (kind + ".glb")).write_bytes(
        struct.pack("<4sIIII", b"glTF", 2, 20 + len(meta) + len(payload), len(meta), 0x4E4F534A)
        + meta
        + payload
    )
    front, rear = (
        ("wheel_front", "wheel_rear") if kind == "faggio" else ("wheel_rf_dummy", "wheel_rb_dummy")
    )
    return dict(
        lift=float(-lo[2]),
        wheelbase=math.dist(sockets[front][:2], sockets[rear][:2]),
        seat=sockets["ped_frontseat"],
        sockets={
            k: sockets[k]
            for k in ("handlebars", "forks_front", "wheel_front", "wheel_rear")
            if k in sockets
        },
        size=(hi - lo).tolist(),
        sourceDffSha256=hashlib.sha256(blob).hexdigest(),
        handlingSource="simulator",
        sourceFile="models/gta3.img",
    )


def prepare_vehicles(source, adapter, out):
    profiles = {k: vehicle(source, adapter, out, k) for k in ("premier", "faggio")}
    (out / "vehicles.json").write_text(json.dumps(profiles, indent=2), encoding="utf8")
    return profiles


def prepare(folder, source, adapter):
    out = folder / "journey"
    out.mkdir(exist_ok=True)
    route = select_trip(folder)
    vehicles = prepare_vehicles(source, adapter, out)
    route["vehicleLift"] = vehicles["premier"]["lift"]
    atlas = folder / "atlas"
    bounds = json.loads((atlas / "ariane-world-render.json").read_bytes())["bounds"]
    with np.load(atlas / "ariane-world-heightfield.npz") as src:
        h = src["height"][::6, ::6]
        data = np.where(np.isfinite(h), np.clip(h * 8, -32767, 32767), -32768).astype("<i2")
        (out / "horizon.bin").write_bytes(data.tobytes())
        route["terrain"] = dict(
            bounds=bounds,
            cols=h.shape[1],
            rows=h.shape[0],
            nx=src["height"].shape[1],
            ny=src["height"].shape[0],
            stride=6,
        )
    with Image.open(atlas / "ariane-world-top.png") as im:
        im.thumbnail((2048, 2048))
        im.convert("RGB").save(out / "terrain.jpg", quality=90)
    route["legs"] = [{**leg, "path": np.round(leg["path"], 4).tolist()} for leg in route["legs"]]
    (out / "route.json").write_text(json.dumps(route, separators=(",", ":")), encoding="utf-8")
    print(
        route["start"],
        route["end"],
        [(leg["mode"], leg["length"]) for leg in route["legs"]],
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("folder", "source", "adapter"):
        p.add_argument("--" + k, type=Path, required=True)
    args = p.parse_args()
    prepare(args.folder, args.source, args.adapter)
