"""Translate Ariane terrain passes and misplaced static bounds into a browser game overlay."""

import argparse
import hashlib
import json
import math
import struct
from collections import defaultdict
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from scripts.pilot.world_map_lab.browser_mip_levels import chunk, chunks
from scripts.pilot.world_map_lab.compact_browser_textures import read_bindings
from scripts.pilot.world_map_lab.native_collisions import ENTRY, SECTOR, img_directory


def payload(directory, name):
    path, off, size = directory[name]
    with path.open("rb") as stream:
        stream.seek(off)
        parts = []
        while size >= 12:
            head = stream.read(12)
            tag, length, _version = struct.unpack("<III", head)
            if length + 12 > size:
                raise ValueError(f"bad RW root {name}")
            data = stream.read(length)
            if len(data) != length:
                raise EOFError(name)
            parts.extend((head, data))
            if name.lower().endswith(".dff") and tag == 0x2B:
                size -= 12 + length
                continue
            return b"".join(parts)
        raise ValueError(f"missing RW root {name}")


def layers(plugin):
    if len(plugin) < 12 or struct.unpack_from("<I", plugin)[0] != 9:
        return None
    pos = 8
    result = []
    for _ in range(5):
        factor, tag, n, _rev = struct.unpack_from("<fIII", plugin, pos)
        if tag != 6 or pos + 16 + n > len(plugin) or not math.isfinite(factor):
            raise ValueError("invalid terrain layer")
        name = next((d for k, _, d in chunks(plugin[pos + 16 : pos + 16 + n]) if k == 2), None)
        if name is None:
            raise ValueError("missing terrain texture name")
        result.append((name.partition(b"\0")[0].decode("ascii").lower(), factor))
        pos += 16 + n
    return tuple(result)


def local_sphere(data):
    if len(data) < 16:
        raise ValueError("short geometry")
    flags, nt, nv, nm = struct.unpack_from("<4I", data)
    if nm != 1 or not nv or flags & 0x01000000:
        return data
    n_uv = (flags >> 16) & 255 or (2 if flags & 128 else int(bool(flags & 4)))
    off = 16 + nv * (4 * int(bool(flags & 8)) + 8 * n_uv) + 8 * nt
    if off + 24 + 12 * nv > len(data) or not struct.unpack_from("<I", data, off + 16)[0]:
        return data
    pts = np.frombuffer(data, "<f4", count=nv * 3, offset=off + 24).reshape(-1, 3).astype(float)
    sphere = np.frombuffer(data, "<f4", count=4, offset=off)
    center = (pts.min(axis=0) + pts.max(axis=0)) * 0.5
    radius = float(np.max(np.linalg.norm(pts - center, axis=1)))
    if not np.isfinite(pts).all() or not np.isfinite(sphere).all():
        raise ValueError("non-finite geometry")
    # A partially overlapping sphere can hide fences and branches during a camera turn.
    tolerance = max(0.002, abs(float(sphere[3])) * 1e-5)
    if sphere[3] >= 0 and np.linalg.norm(pts - sphere[:3], axis=1).max() <= sphere[3] + tolerance:
        return data
    return data[:off] + struct.pack("<4f", *center, radius + 0.015) + data[off + 16 :]


def bake(layers_, lookup):
    images = [lookup(name) if name else None for name, _ in layers_]
    if images[-1] is None or any(
        name and image is None for (name, _), image in zip(layers_, images)
    ):
        raise KeyError(
            [name for (name, _), image in zip(layers_, images) if name and image is None]
        )
    h, w = images[-1].shape[:2]
    yy, xx = np.indices((h, w), np.float32)
    uv = ((xx + 0.5) / w, (yy + 0.5) / h)

    def sample(image, factor):
        return cv2.remap(
            image,
            (uv[0] * factor * image.shape[1] - 0.5).astype("f4"),
            (uv[1] * factor * image.shape[0] - 0.5).astype("f4"),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_WRAP,
        )

    mask = sample(images[-1], layers_[-1][1])[:, :, :3].astype("f4") / 255
    # Native PC rasters are BGRA. The mask names the layers in RGBA order.
    weights = [mask[:, :, 2], mask[:, :, 1], mask[:, :, 0], np.maximum(0, 1 - mask.sum(axis=2))]
    acc = np.zeros((h, w, 3), "f4")
    mass = np.zeros((h, w), "f4")
    for image, (_, factor), weight in zip(images[:4], layers_[:4], weights):
        if image is not None:
            acc += sample(image, factor)[:, :, :3] * weight[:, :, None]
            mass += weight
    if np.any(mass < 1e-6):
        raise ValueError("terrain mask assigns pixels to missing layers")
    result = np.full((h, w, 4), 255, np.uint8)
    result[:, :, :3] = np.rint(acc / mass[:, :, None]).clip(0, 255).astype(np.uint8)
    return result


def native_texture(image, name, v):
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 9, 0x1106)
    header[8 : 8 + len(name)] = name.encode()
    h, w = image.shape[:2]
    mips = []
    while True:
        raw = image.tobytes()
        mips.extend([struct.pack("<I", len(raw)), raw])
        if max(image.shape[:2]) == 1:
            break
        image = cv2.resize(
            image,
            (max(1, image.shape[1] // 2), max(1, image.shape[0] // 2)),
            interpolation=cv2.INTER_AREA,
        )
    struct.pack_into("<IIHHBBBB", header, 72, 0x8500, 21, w, h, 32, len(mips) // 2, 4, 0)
    return chunk(21, v, chunk(1, v, bytes(header) + b"".join(mips)) + chunk(3, v, b""))


class Bank:
    def __init__(self, path):
        self.path = path
        self.stream = path.open("xb")
        self.stream.seek(SECTOR * 300)
        self.directory = []

    def add(self, name, data):
        if len(self.directory) >= 19000 or len(name.encode()) > 23 or len(data) > 65535 * SECTOR:
            raise ValueError("resource exceeds IMG format limits")
        self.directory.append(
            ENTRY.pack(
                self.stream.tell() // SECTOR, math.ceil(len(data) / SECTOR), 0, name.encode()
            )
        )
        self.stream.write(data)
        self.stream.write(bytes(-len(data) % SECTOR))

    def finish(self):
        self.stream.seek(0)
        self.stream.write(struct.pack("<4sI", b"VER2", len(self.directory)))
        self.stream.writelines(self.directory)
        self.stream.close()
        if len(img_directory(self.path)) != len(self.directory):
            raise ValueError("overlay directory mismatch")


def build(game, ide, output):
    if output.exists():
        raise FileExistsError(output)
    from scripts.pilot.world_map_lab.browser_cutout_order import sorted_cutouts

    lines, cutout_models = sorted_cutouts(game, ide)
    models, parents = read_bindings(lines)
    directory = {}
    for path in sorted((game / "data/maps/brworld").glob("brw*.img")):
        directory.update(img_directory(path))

    @lru_cache(maxsize=12)
    def textures(pack):
        data = payload(directory, pack + ".txd")
        parsed = {}
        for tag, _, native in chunks(data[12:]):
            if tag != 21:
                continue
            h = next(d for k, _, d in chunks(native) if k == 1)
            w, height = struct.unpack_from("<HH", h, 80)
            n = struct.unpack_from("<I", h, 88)[0]
            if struct.unpack_from("<I", h, 76)[0] == 21 and n == w * height * 4:
                parsed[h[8:40].partition(b"\0")[0].decode("ascii").lower()] = np.frombuffer(
                    h, np.uint8, n, 92
                ).reshape(height, w, 4)
        return parsed

    def lookup(pack, name):
        seen = set()
        while pack and pack not in seen:
            seen.add(pack)
            if pack + ".txd" in directory:
                im = textures(pack).get(name)
                if im is not None:
                    return im
            pack = parents.get(pack)
        return None

    groups = defaultdict(list)
    for model, pack in models.items():
        if model + ".dff" in directory:
            groups[pack].append(model)
    changes = {}
    parents_added = {}
    stats = dict(
        models=0,
        bounds=0,
        bakedMaterials=0,
        sortedCutoutModels=len(cutout_models),
        sourceIdeSha256=hashlib.sha256(ide.read_bytes()).hexdigest(),
        unresolved=[],
        banks=[],
    )
    with TemporaryDirectory(dir=output.parent) as temp, ExitStack() as open_banks:
        dest = Path(temp) / "materials"
        dest.mkdir()
        banks = []

        def add(name, data):
            if not banks or banks[-1].stream.tell() + len(data) > 1500 * 1024**2:
                if banks:
                    banks[-1].finish()
                name_bank = f"brvis{len(banks):02d}.img"
                banks.append(Bank(dest / name_bank))
                open_banks.callback(banks[-1].stream.close)
                stats["banks"].append(name_bank)
            banks[-1].add(name, data)

        for i, (pack, names) in enumerate(sorted(groups.items())):
            newpack = f"brvis{i:04x}"
            mats = {}
            for model in names:
                name = model + ".dff"
                data = payload(directory, name)
                modmat = False

                def convert(part, container):
                    nonlocal modmat
                    out = []
                    for tag, v, d in chunks(part):
                        if tag in (16, 26, 15, 8):
                            d = convert(d, tag)
                        elif tag == 1 and container == 15:
                            new = local_sphere(d)
                            stats["bounds"] += int(new is not d)
                            d = new
                        elif tag == 7 and container == 8:
                            children = list(chunks(d))
                            ext = next((e for k, _, e in children if k == 3), b"")
                            splat = next(
                                (
                                    z
                                    for plugin, _, z in chunks(ext)
                                    if plugin == 0x120 and z[:4] == b"\x09\0\0\0"
                                ),
                                None,
                            )
                            if splat is not None:
                                inputs = layers(splat)
                                key = "land" + hashlib.sha256(splat).hexdigest()[:18]
                                try:
                                    if key not in mats:
                                        rgba = bake(inputs, lambda texture: lookup(pack, texture))
                                        mats[key] = native_texture(rgba, key, v)
                                    fixed = []
                                    for k, r, sub in children:
                                        if k == 1:
                                            h = bytearray(sub)
                                            h[4:8] = bytes([255] * 4)
                                            struct.pack_into("<I", h, 12, 1)
                                            fixed.append(chunk(1, r, h))
                                            text = key.encode() + b"\0"
                                            text += bytes(-len(text) % 4)
                                            fixed.append(
                                                chunk(
                                                    6,
                                                    r,
                                                    chunk(1, r, struct.pack("<I", 0x1106))
                                                    + chunk(2, r, text)
                                                    + chunk(2, r, bytes(4))
                                                    + chunk(3, r, b""),
                                                )
                                            )
                                        elif k == 3:
                                            fixed.append(
                                                chunk(
                                                    3,
                                                    r,
                                                    b"".join(
                                                        chunk(j, rv, b)
                                                        for j, rv, b in chunks(sub)
                                                        if j != 0x120
                                                    ),
                                                )
                                            )
                                        elif k != 6:
                                            fixed.append(chunk(k, r, sub))
                                    d = b"".join(fixed)
                                    modmat = True
                                    stats["bakedMaterials"] += 1
                                except (KeyError, ValueError) as e:
                                    stats["unresolved"].append([model, str(e)])
                        out.append(chunk(tag, v, d))
                    return b"".join(out)

                new = convert(data, 0)
                if modmat:
                    changes[model] = newpack
                if new != data:
                    add(name, new)
                    stats["models"] += 1
            if mats:
                parents_added[newpack] = pack
                v = struct.unpack_from("<I", next(iter(mats.values())), 8)[0]
                add(
                    newpack + ".txd",
                    chunk(
                        22,
                        v,
                        chunk(1, v, struct.pack("<HH", len(mats), 2))
                        + b"".join(mats.values())
                        + chunk(3, v, b""),
                    ),
                )
        for bank in banks[-1:]:
            bank.finish()
        out = []
        for line in lines:
            fields = line.split(",")
            if len(fields) > 3 and fields[1].strip().lower() in changes:
                fields[2] = " " + changes[fields[1].strip().lower()]
                line = ",".join(fields)
            out.append(line)
        out += ["txdp", *(f"{child} {parent}" for child, parent in parents_added.items()), "end"]
        (dest / "brworld.ide").write_text("\n".join(out) + "\n", encoding="ascii")
        (dest / "report.json").write_text(json.dumps(stats, indent=2), encoding="utf8")
        dest.rename(output)
    return stats


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "ide", "output"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    summary = build(args.game, args.ide, args.output)
    print({k: (len(v) if k == "unresolved" else v) for k, v in summary.items()})
