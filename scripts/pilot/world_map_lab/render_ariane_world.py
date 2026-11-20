"""Render the active exterior of Ariane with source meshes, water and sampled TXD colors."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from struct import Struct

import numpy as np
from PIL import Image

from scripts.pilot.world_map_lab.ariane_geometry import REGIONS, instance_parts, model_types
from scripts.pilot.world_map_lab.index_ariane_world import inventory
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter

CHUNK = Struct("<3I")
UINT = Struct("<I")
SKY = (28, 46, 54)
WATER = (47, 86, 102)


def chunks(blob):
    position = 0
    while position + CHUNK.size <= len(blob):
        kind, length, _ = CHUNK.unpack_from(blob, position)
        start = position + CHUNK.size
        stop = start + length
        if stop > len(blob):
            break
        yield kind, blob[start:stop]
        position = stop


def splat_textures(plugin):
    names = []
    position = 8
    for _ in range(5):
        position += 4  # Per-layer UV tiling factor.
        if position + CHUNK.size > len(plugin):
            return ()
        kind, length, _ = CHUNK.unpack_from(plugin, position)
        start = position + CHUNK.size
        position = start + length
        if kind != 6 or position > len(plugin):
            return ()
        strings = [value for tag, value in chunks(plugin[start:position]) if tag == 2]
        if not strings:
            return ()
        names.append(bytes(strings[0]).split(b"\0", 1)[0].decode("ascii").lower())
    return tuple(names)


def terrain_materials(blob):
    result = []
    for clump_kind, clump in chunks(memoryview(blob)):
        if clump_kind != 0x10:
            continue
        for list_kind, geometry_list in chunks(clump):
            if list_kind != 0x1A:
                continue
            for shape_kind, shape in chunks(geometry_list):
                if shape_kind != 0x0F:
                    continue
                for materials_kind, materials in chunks(shape):
                    if materials_kind != 8:
                        continue
                    for material_kind, material in chunks(materials):
                        if material_kind != 7:
                            continue
                        names = ()
                        for ext_kind, extension in chunks(material):
                            if ext_kind != 3:
                                continue
                            for plugin_kind, plugin in chunks(extension):
                                if (
                                    plugin_kind == 0x120
                                    and len(plugin) >= 12
                                    and UINT.unpack_from(plugin)[0] == 9
                                ):
                                    names = splat_textures(plugin)
                        result.append(names)
    return result


def texture_parents(source):
    ide = source / "data/br_map.ide"
    active = False
    parents = {}
    for line in ide.read_text(encoding="utf-8-sig").splitlines():
        words = line.split("#", 1)[0].replace(",", " ").lower().split()
        if words == ["txdp"]:
            active = True
        elif active and words == ["end"]:
            active = False
        elif active and len(words) == 2:
            parents[words[0]] = words[1]
    return parents


class Textures:
    def __init__(self, source, geometry):
        folder = source / "models/img"
        self.geometry = geometry
        self.entries = geometry.index_files(
            sorted(folder.glob("br_textures_*.img")) + [folder / "br_terrain.img"]
        )
        self.parents = texture_parents(source)
        self.txd = import_module("gtaLib.txd")
        self.stats = Counter()
        self.packs = lru_cache(maxsize=2048)(self.read_pack)

    def read_pack(self, pack):
        key = pack + ".txd"
        if key not in self.entries:
            return {}
        parsed = self.txd.txd()
        result = {}
        try:
            parsed.load_memory(self.geometry.read_entry(self.entries, key))
        except (ValueError, KeyError, TypeError, AssertionError, IndexError):
            self.stats["unreadable_dictionaries"] += 1
            return {}
        for tex in parsed.native_textures:
            first = next(
                (
                    i
                    for i in range(tex.num_levels)
                    if max(tex.get_width(i), tex.get_height(i)) <= 64
                ),
                max(0, tex.num_levels - 1),
            )
            try:
                rgba = np.frombuffer(tex.to_rgba(first), np.uint8).reshape(
                    tex.get_height(first), tex.get_width(first), 4
                )
            except (ValueError, KeyError, TypeError, AttributeError, AssertionError, IndexError):
                self.stats["unreadable_textures"] += 1
                continue
            result[tex.name.lower()] = rgba
        return result

    def find(self, pack, name):
        visited = set()
        while pack and pack not in visited:
            visited.add(pack)
            image = self.packs(pack).get(name)
            if image is not None:
                return image
            pack = self.parents.get(pack)
        return None

    def material(self, pack, item, splat=()):
        if len(splat) == 5:
            layers = [self.find(pack, name) if name else None for name in splat]
            mask = layers[-1]
            available = [i for i, layer in enumerate(layers[:4]) if layer is not None]
            if available:
                base = np.stack([layers[i][..., :3].mean(axis=(0, 1)) for i in available])
                if mask is None:
                    self.stats["terrain_material_fallback"] += 1
                    color = np.asarray([*np.rint(base[0]), 255], np.uint8)
                    return color.reshape(1, 1, 4)
                rgb = mask[..., :3].astype(np.float32) / 255
                weights = np.concatenate(
                    (rgb, np.maximum(1 - rgb.sum(axis=2, keepdims=True), 0)), axis=2
                )[:, :, available]
                mass = weights.sum(axis=2, keepdims=True)
                if np.any(mass < 1e-6):
                    self.stats["terrain_pixels_with_unresolved_weight"] += int(
                        np.count_nonzero(mass < 1e-6)
                    )
                output = np.where(mass > 1e-6, weights @ base / np.maximum(mass, 1e-6), base[0])
                self.stats["masked_terrain_materials"] += 1
                return np.dstack(
                    (
                        np.rint(output).astype(np.uint8),
                        np.full(output.shape[:2], 255, np.uint8),
                    )
                )
            self.stats["terrain_material_fallback"] += 1
        if item.textures:
            texture = self.find(pack, item.textures[0].name.lower())
            if texture is not None:
                self.stats["sampled_diffuse_materials"] += 1
                return texture
            self.stats["unresolved_diffuse_materials"] += 1
        self.stats["flat_materials"] += 1
        return np.asarray(item.color, dtype=np.uint8).reshape(1, 1, 4)


def pack_textures(images):
    offsets = np.asarray(
        [0, *np.cumsum([image.shape[0] * image.shape[1] for image in images[:-1]])], np.int64
    )
    sizes = np.asarray([(image.shape[1], image.shape[0]) for image in images], np.int64)
    pixels = np.concatenate([image.reshape(-1, 4) for image in images])
    return pixels, offsets, sizes


def render(points, uv, shade, texture_ids, pixels, offsets, sizes, frame, depth):
    height, width, _ = frame.shape
    for i in range(len(points)):
        triangle = points[i]
        x0, y0, z0 = triangle[0]
        x1, y1, z1 = triangle[1]
        x2, y2, z2 = triangle[2]
        divisor = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(divisor) < 1e-6:
            continue
        xmin = max(0, math.ceil(min(x0, x1, x2) - 0.5))
        xmax = min(width - 1, math.floor(max(x0, x1, x2) - 0.5))
        ymin = max(0, math.ceil(min(y0, y1, y2) - 0.5))
        ymax = min(height - 1, math.floor(max(y0, y1, y2) - 0.5))
        if xmin > xmax or ymin > ymax:
            continue
        tex = texture_ids[i]
        tw, th = sizes[tex]
        for y in range(ymin, ymax + 1):
            dy = y + 0.5 - y2
            for x in range(xmin, xmax + 1):
                dx = x + 0.5 - x2
                a = ((y1 - y2) * dx + (x2 - x1) * dy) / divisor
                b = ((y2 - y0) * dx + (x0 - x2) * dy) / divisor
                c = 1 - a - b
                if min(a, b, c) < 0:
                    continue
                z = a * z0 + b * z1 + c * z2
                if z >= depth[y, x]:
                    continue
                u = a * uv[i, 0, 0] + b * uv[i, 1, 0] + c * uv[i, 2, 0]
                v = a * uv[i, 0, 1] + b * uv[i, 1, 1] + c * uv[i, 2, 1]
                tx = int((u - math.floor(u)) * tw)
                ty = int((v - math.floor(v)) * th)
                offset = offsets[tex] + ty * tw + tx
                if pixels[offset, 3] < 125:
                    continue
                for channel in range(3):
                    frame[y, x, channel] = min(255, int(pixels[offset, channel] * shade[i] + 0.5))
                depth[y, x] = z


class View:
    def __init__(self, bounds, width, azimuth=None):
        if azimuth is None:
            self.basis = np.diag((1.0, -1.0, -1.0))
        else:
            azimuth = math.radians(azimuth)
            angle = math.radians(47)
            east = np.asarray([math.cos(azimuth), math.sin(azimuth), 0.0])
            north = np.asarray([-math.sin(azimuth), math.cos(azimuth), 0.0])
            vertical = np.asarray([0.0, 0.0, 1.0])
            self.basis = np.asarray(
                [
                    east,
                    -north * math.sin(angle) - vertical * math.cos(angle),
                    north * math.cos(angle) - vertical * math.sin(angle),
                ]
            )
        bounds_points = (
            np.asarray(
                [
                    (x, y, z)
                    for x in (bounds["left"], bounds["right"])
                    for y in (bounds["bottom"], bounds["top"])
                    for z in ((0.0,) if azimuth is None else (-10.0, 190.0))
                ]
            )
            @ self.basis.T
        )
        minimum, maximum = bounds_points.min(axis=0), bounds_points.max(axis=0)
        self.scale = width / (maximum[0] - minimum[0])
        height = int(math.ceil((maximum[1] - minimum[1]) * self.scale))
        self.min_xy = minimum[:2]
        self.image = np.full((height, width, 3), SKY, np.uint8)
        self.depth = np.full((height, width), np.inf, np.float32)
        self.matrix = self.basis * np.asarray([self.scale, self.scale, 1])[:, None]
        self.origin = np.asarray([*(self.min_xy * self.scale), 0.0])

    def draw(self, raster, positions, uv, shade, texture_ids, textures):
        points = np.asarray(positions @ self.matrix.T - self.origin, dtype=np.float32)
        raster(points, uv, shade, texture_ids, *textures, self.image, self.depth)


def water_triangles(source):
    with (source / "data/water.dat").open(encoding="utf-8-sig") as file:
        for line in file:
            values = line.split("#", 1)[0].split()
            if len(values) not in (22, 29):
                continue
            points = np.asarray(values[:-1], dtype=np.float64).reshape(-1, 7)[:, :3]
            yield points[[0, 1, 2]]
            if len(points) == 4:
                yield points[[1, 2, 3]]


def model_mesh(geometry, models, name, kind, pack, textures, instances, bounds, restrict):
    """Cull by a conservative rotated model radius. Keep geometry that crosses the crop edge."""
    blob = geometry.read_entry(models, name)
    splat = terrain_materials(blob) if b"\x20\x01\x00\x00" in blob else []
    for vertices, mesh in instance_parts(blob, kind):
        visible = instances
        if restrict and len(vertices):
            radius = float(np.linalg.norm(vertices, axis=1).max())
            visible = [
                item
                for item in instances
                if bounds["left"] - radius <= item.position[0] <= bounds["right"] + radius
                and bounds["bottom"] - radius <= item.position[1] <= bounds["top"] + radius
            ]
        if not visible:
            continue
        indexes = np.asarray(
            [(face.a, face.b, face.c, face.material) for face in mesh.triangles], np.intp
        )
        if not indexes.size or not mesh.materials:
            continue
        indexes = indexes[(indexes[:, 3] >= 0) & (indexes[:, 3] < len(mesh.materials))]
        if not len(indexes):
            continue
        material_ids, assigned = np.unique(indexes[:, 3], return_inverse=True)
        source_materials = [
            textures.material(pack, mesh.materials[i], splat[i] if i < len(splat) else ())
            for i in material_ids
        ]
        corners = indexes[:, :3]
        if mesh.uv_layers and len(mesh.uv_layers[0]) == len(vertices):
            uv = np.asarray(mesh.uv_layers[0], np.float32)[corners]
        else:
            uv = np.zeros((len(corners), 3, 2), np.float32)
        yield vertices, corners, uv, assigned, pack_textures(source_materials), visible


def shaded(positions):
    cross = np.cross(positions[:, 1] - positions[:, 0], positions[:, 2] - positions[:, 0])
    light = np.asarray([-0.32, 0.48, 0.82])
    lengths = np.linalg.norm(cross, axis=1)
    facing = cross @ light / np.maximum(lengths, 1e-9)
    facing *= np.where(cross[:, 2] < -1e-8, -1.0, 1.0)
    return np.asarray(0.75 + 0.23 * np.maximum(facing, 0.0), dtype=np.float32)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--geometry-tools", required=True, type=Path)
    parser.add_argument("--road-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", type=int, default=3200)
    parser.add_argument("--area", choices=REGIONS)
    parser.add_argument(
        "--navigation-geometry",
        type=Path,
        help="Render the elevation band containing the authored road surfaces",
    )
    args = parser.parse_args()
    if not 320 <= args.width <= 4800:
        parser.error("--width must be between 320 and 4800")
    source, output = args.source.resolve(), args.output.resolve()
    geometry = load_local_adapter(source, args.geometry_tools.resolve())
    sys.path.insert(0, str(args.geometry_tools / "deps-raster"))
    numba = import_module("numba")
    raster = numba.njit(cache=True)(render)
    report = json.loads(args.road_report.read_bytes())
    bounds = report["placementBounds"]
    if args.area:
        bounds = dict(zip(("left", "right", "bottom", "top"), REGIONS[args.area], strict=True))
    expected = inventory(source, "black-russia-ariane")
    if (
        report["worldId"] != expected["world_id"]
        or report["placementRevision"] != expected["placement_revision"]
    ):
        raise ValueError("the overlay belongs to another world or map revision")
    views = {"top": View(bounds, args.width), "color-3d": View(bounds, args.width, -24)}
    water = np.asarray(list(water_triangles(source)))
    street_band = None
    if args.navigation_geometry:
        from scripts.pilot.world_map_lab.world_navmesh import checksum, spatial_index

        directory = args.navigation_geometry
        geo = json.loads((directory / "geometry.json").read_bytes())
        binary = directory / "world-geometry.bin"
        if (
            geo["placementRevision"] != expected["placement_revision"]
            or checksum(binary) != geo["geometrySha256"]
        ):
            raise ValueError("street elevation source does not match the rendered world")
        raw = np.memmap(binary, dtype="u1", mode="r")
        _, batches = spatial_index(raw, [bounds[k] for k in ("left", "right", "bottom", "top")])
        bands = []
        for _, n, kind, low, high in sorted(
            (row for row in batches if row[2] in (0, 1, 3)), key=lambda row: row[3]
        ):
            if not bands or low > bands[-1][1] + 2:
                bands.append([low, high, 0])
            else:
                bands[-1][1] = max(bands[-1][1], high)
            if kind == 3:
                bands[-1][2] += n
        low, high, roads = max(bands, key=lambda band: band[2])
        if not roads:
            raise ValueError("no road height band")
        street_band = (low - 2, high + 2)
        water = water[
            (water[:, :, 2].max(axis=1) >= street_band[0])
            & (water[:, :, 2].min(axis=1) <= street_band[1])
        ]
    water[:, :, 2] -= 0.04
    water_atlas = pack_textures([np.asarray([*WATER, 255], np.uint8).reshape(1, 1, 4)])
    for view in views.values():
        view.draw(
            raster,
            water,
            np.zeros((len(water), 3, 2), np.float32),
            np.ones(len(water), np.float32),
            np.zeros(len(water), np.int64),
            water_atlas,
        )
    textures = Textures(source, geometry)
    folder = source / "models/img"
    models = geometry.index_files(
        sorted(folder.glob("br_models_*.img")) + [folder / "br_terrain_models.img"]
    )
    placements = defaultdict(list)
    for placement in geometry.active_exterior():
        placements[placement.name + ".dff"].append(placement)
    types = model_types(source)
    packs = geometry.definition_dicts(source)
    counts = Counter()
    for name, _ in sorted(models.items(), key=lambda item: item[1][:2]):
        instances = placements.get(name)
        if not instances:
            continue
        bare_name = name.removesuffix(".dff")
        rendered = set()
        for local, corners, uv, assigned, atlas, visible in model_mesh(
            geometry,
            models,
            name,
            types[bare_name],
            packs.get(bare_name, ""),
            textures,
            instances,
            bounds,
            bool(args.area),
        ):
            for placed in visible:
                position = (geometry.ariane_rotation(placed.quat).apply(local) + placed.position)[
                    corners
                ]
                if street_band and (
                    position[:, :, 2].max() < street_band[0]
                    or position[:, :, 2].min() > street_band[1]
                ):
                    continue
                shade = shaded(position)
                for view in views.values():
                    view.draw(raster, position, uv, shade, assigned, atlas)
                counts["triangles"] += len(corners)
                rendered.add((placed.scene, placed.ordinal))
        counts["models"] += 1
        counts["placements"] += len(instances)
        counts["placements_with_geometry_in_view"] += len(rendered)
        if counts["models"] % 1000 == 0:
            print(dict(counts), dict(textures.stats), flush=True)

    if counts["placements"] != expected["exterior_placements"]:
        raise ValueError("a source model is missing from the rendered exterior")
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "worldId": report["worldId"],
        "placementRevision": report["placementRevision"],
        "bounds": bounds,
        "area": args.area,
        "geometry": dict(counts),
        "texture_materials": dict(textures.stats),
        "water_triangles": len(water),
        "streetHeightBand": street_band,
        "views": {},
    }
    for name, view in views.items():
        path = output / f"ariane-world-{name}.png"
        Image.fromarray(view.image).save(path, compress_level=4)
        result["views"][name] = {
            "dimensions": list(view.image.shape[1::-1]),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "populated_pixels": int(np.isfinite(view.depth).sum()),
        }
    top = views["top"]
    if street_band:
        np.savez_compressed(output / "ariane-world-visible-height.npz", height=-top.depth)
    np.savez_compressed(
        output / "ariane-world-heightfield.npz",
        height=-top.depth[::3, ::3],
        rgb=top.image[::3, ::3],
    )
    (output / "ariane-world-render.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
