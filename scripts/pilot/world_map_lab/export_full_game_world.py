"""Build and verify a full native GTA SA map overlay from the ordered Ariane manifest."""

import argparse
import hashlib
import json
import math
import shutil
import struct
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.native_collisions import (
    COL,
    ENTRY,
    SECTOR,
    bind_collisions,
    img_directory,
)
from scripts.pilot.world_map_lab.stage_game_quarter import directives


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_file(root, relative):
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"invalid source file {relative}")
    return path


def definitions(path):
    models, textures, animations = {}, set(), set()
    section = None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.partition("#")[0].strip().lower()
        if not line:
            continue
        if section is None:
            section = line
        elif line == "end":
            section = None
        elif section == "txdp":
            child, parent = line.replace(",", " ").split()
            textures.update((child, parent))
        elif section in {"objs", "tobj", "anim"}:
            ident, name, texture, *fields = (part.strip() for part in line.split(","))
            if name in models:
                raise ValueError(f"duplicate model {name}")
            models[name] = int(ident)
            textures.add(texture)
            if section == "anim":
                animations.add(fields[0])
        else:
            raise ValueError(f"unsupported IDE section {section}")
    if not models or section is not None or len(set(models.values())) != len(models):
        raise ValueError("incomplete or ambiguous IDE")
    return models, textures, animations


def check_scene(path, ids):
    areas = Counter()
    lods = []
    bounds = [[math.inf] * 3, [-math.inf] * 3]
    skipped = 0
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.partition("#")[0].strip()
        if not line or line.lower() in {"inst", "end"}:
            skipped += raw.lstrip().startswith("# unavailable source:")
            continue
        row = [v.strip() for v in line.split(",")]
        if len(row) != 11 or ids.get(row[1].lower()) != int(row[0]):
            raise ValueError(f"unbound placement in {path.name}: {line}")
        transform = [float(v) for v in row[3:10]]
        if not all(math.isfinite(v) for v in transform):
            raise ValueError(f"invalid transform in {path.name}")
        area = int(row[2])
        areas[area] += 1
        if area == 0:
            for axis, value in enumerate(transform[:3]):
                bounds[0][axis] = min(bounds[0][axis], value)
                bounds[1][axis] = max(bounds[1][axis], value)
        lods.append(int(row[10]))
    if any(target < -1 or target >= len(lods) for target in lods):
        raise ValueError(f"invalid scene-local LOD in {path.name}")
    checked = set()
    for index in range(len(lods)):
        chain = set()
        while index != -1 and index not in checked:
            if index in chain:
                raise ValueError(f"LOD cycle in {path.name}")
            chain.add(index)
            index = lods[index]
        checked.update(chain)
    return dict(
        instances=len(lods),
        lodLinks=sum(v >= 0 for v in lods),
        areas=dict(areas),
        exteriorBounds=bounds if areas[0] else None,
        unavailableSourceRows=skipped,
    )


def patch_collision(payload, ids, names):
    offset = 0
    changed = 0
    while payload[offset : offset + 4] in (b"COL3", b"COL2", b"COLL"):
        tag, size, raw, previous = COL.unpack_from(payload, offset)
        name = raw.partition(b"\0")[0].decode("ascii").lower()
        if (
            name in names
            or name not in ids
            or size + 8 < COL.size
            or offset + size + 8 > len(payload)
        ):
            raise ValueError(f"ambiguous or invalid collision {name}")
        names.add(name)
        changed += ids[name] != previous
        offset += size + 8
    if not offset or any(payload[offset:]):
        raise ValueError("unsupported data after collision records")
    return bind_collisions(payload[:offset], ids) + payload[offset:], changed


def check_renderware(payload, name):
    required = 0x10 if name.endswith(".dff") else 0x16
    offset = 0
    while offset + 12 <= len(payload):
        kind, length = struct.unpack_from("<II", payload, offset)
        offset += 12 + length
        if offset > len(payload):
            break
        if kind == required:
            return
        # Animated geometry can begin with a UV animation dictionary.
        if required != 0x10 or kind != 0x2B:
            break
    raise ValueError(f"bad RenderWare entry {name}")


def write_bank(target, entries, ids, collider_names, files):
    table_sectors = math.ceil((8 + ENTRY.size * len(entries)) / SECTOR)
    cursor = table_sectors
    expected = {}
    changed = 0
    with target.open("xb") as stream:
        stream.write(struct.pack("<4sI", b"VER2", len(entries)))
        for name, (_, _, size) in entries:
            stream.write(ENTRY.pack(cursor, size // SECTOR, 0, name.encode("ascii")))
            cursor += size // SECTOR
        stream.seek(table_sectors * SECTOR)
        for name, (path, offset, size) in entries:
            source = files[path]
            source.seek(offset)
            payload = source.read(size)
            if len(payload) != size:
                raise ValueError(f"truncated source {name}")
            if name.endswith(".col"):
                payload, rebound = patch_collision(payload, ids, collider_names)
                changed += rebound
            else:
                check_renderware(payload, name)
            stream.write(payload)
            expected[name] = hashlib.sha256(payload).digest()
    restored = img_directory(target)
    if set(restored) != set(expected):
        raise ValueError(f"repacked index differs: {target.name}")
    with target.open("rb") as stream:
        for name, (_, start, size) in restored.items():
            stream.seek(start)
            if hashlib.sha256(stream.read(size)).digest() != expected[name]:
                raise ValueError(f"repacked content differs: {name}")
    return changed


def banks(entries, limit):
    group, size = [], 0
    for name, origin in entries.items():
        length = origin[2]
        header = math.ceil((8 + (len(group) + 1) * ENTRY.size) / SECTOR) * SECTOR
        if group and size + length + header > limit:
            yield group
            group, size = [], 0
        if length + SECTOR > limit:
            raise ValueError(f"entry exceeds archive budget: {name}")
        group.append((name, origin))
        size += length
    if group:
        yield group


def copy_verified(source, target):
    shutil.copyfile(source, target)
    value = digest(source)
    if digest(target) != value:
        raise ValueError(f"copy verification failed: {source}")
    return value


def build(source, destination, limit=1900 * 1024**2, scenario=None, route=None):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(source) or bool(scenario) != bool(route):
        raise ValueError("select a new output and supply scenario and route together")
    default = list(directives(source / "data/default.dat"))
    world = list(directives(source / "data/gta.dat"))
    if any(k not in {"IMG", "IDE"} for k, _ in default) or any(k != "IPL" for k, _ in world):
        raise ValueError("unhandled map directive")
    (ide,) = (source_file(source, p) for k, p in default if k == "IDE")
    ids, textures, anim = definitions(ide)
    sources = [source_file(source, p) for k, p in default if k == "IMG"]
    entries = {}
    overridden = Counter()
    for path in sources:
        current = img_directory(path)
        overridden.update(Path(n).suffix for n in current.keys() & entries.keys())
        entries.update(current)
    missing = ({name + ".dff" for name in ids} | {n + ".txd" for n in textures}) - entries.keys()
    external_textures = sorted(missing & {"generic.txd"})
    missing.difference_update(external_textures)
    base_assets = set()
    for archive in (source / "models").glob("*.img"):
        base_assets.update(img_directory(archive))
    if missing or any(Path(n).suffix not in {".col", ".txd", ".dff"} for n in entries):
        raise ValueError(f"unresolved or unsupported native assets: {sorted(missing)[:10]}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        shutil.disk_usage(destination.parent).free
        < sum(v[2] for v in entries.values()) + 128 * 1024**2
    ):
        raise ValueError("insufficient disk for full verified package")
    with TemporaryDirectory(dir=destination.parent) as temp:
        root = Path(temp) / "world"
        folder = root / "data/maps/brworld"
        folder.mkdir(parents=True)
        config, scene_reports, archives = [], [], []
        col_names = set()
        changed = 0
        with ExitStack() as stack:
            handles = {p: stack.enter_context(p.open("rb")) for p in sources}
            for idx, group in enumerate(banks(entries, limit)):
                path = folder / f"brw{idx:02}.img"
                changed += write_bank(path, group, ids, col_names, handles)
                archives.append(
                    dict(
                        name=path.name,
                        entries=len(group),
                        bytes=path.stat().st_size,
                        sha256=digest(path),
                    )
                )
                config.append(f"IMG DATA\\MAPS\\BRWORLD\\{path.name.upper()}")
                print(f"Verified {path.name} ({len(group)} entries)", flush=True)
        ide_hash = copy_verified(ide, folder / "brworld.ide")
        config.append(r"IDE DATA\MAPS\BRWORLD\BRWORLD.IDE")
        for idx, (_, relative) in enumerate(world):
            path = source_file(source, relative)
            target = folder / f"brs{idx:03}.ipl"
            sha = copy_verified(path, target)
            scene_reports.append(
                dict(source=relative, packaged=target.name, sha256=sha, **check_scene(target, ids))
            )
            config.append(f"IPL DATA\\MAPS\\BRWORLD\\{target.name.upper()}")
        if not scene_reports:
            raise ValueError("empty world")
        environment = {
            n: copy_verified(source / "data" / n, root / "data" / n)
            for n in ("water.dat", "timecyc.dat")
        }
        scenario_hash = None
        if scenario:
            manifest = json.loads((scenario / "classic-scenario.json").read_bytes())
            scenario_hash = copy_verified(route, root / "sphere-route.json")
            if manifest["routeSha256"] != scenario_hash:
                raise ValueError("scenario route mismatch")
            target = root / "data/script"
            target.mkdir()
            for name in ("main.scm", "script.img"):
                if copy_verified(scenario / name, target / name) != manifest["files"][name]:
                    raise ValueError("scenario binary differs")
        fragment = root / "world-fragment.dat"
        fragment.write_text("\n".join(config) + "\n", encoding="ascii")
        for _, name in directives(fragment):
            source_file(root, name.lower())
        bounds = [r["exteriorBounds"] for r in scene_reports if r["exteriorBounds"]]
        report = dict(
            scope="all-active-source-scenes",
            sourceArchives=len(sources),
            archives=archives,
            archiveBudgetBytes=limit,
            modelDefinitions=len(ids),
            textures=len(textures),
            effectiveEntries=dict(Counter(Path(k).suffix for k in entries)),
            overriddenSourceEntries=dict(overridden),
            ideSha256=ide_hash,
            instances=sum(r["instances"] for r in scene_reports),
            lodLinks=sum(r["lodLinks"] for r in scene_reports),
            unavailableSourceRows=sum(r["unavailableSourceRows"] for r in scene_reports),
            exteriorBounds=[
                [min(b[0][i] for b in bounds) for i in range(3)],
                [max(b[1][i] for b in bounds) for i in range(3)],
            ]
            if bounds
            else None,
            collisions=len(col_names),
            reboundCollisionIds=changed,
            modelsWithoutOwnCollision=sorted(set(ids) - col_names),
            externalTextureReferences=external_textures,
            requiredAnimationLibraries=sorted(anim),
            missingSourceAnimations=sorted(n for n in anim if n + ".ifp" not in base_assets),
            scenes=scene_reports,
            modelIdRange=[min(ids.values()), max(ids.values())],
            environment=environment,
            routeSha256=scenario_hash,
            gameRuntimeTested=False,
        )
        (root / "world-manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        root.rename(destination)
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "output", "classic-scenario", "route"):
        cli.add_argument("--" + key, type=Path, required=key in {"source", "output"})
    args = cli.parse_args()
    build(args.source, args.output, scenario=args.classic_scenario, route=args.route)
