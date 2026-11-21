"""Pack compatible Black Russia texture dictionaries into stock SA streaming slots."""

import argparse
import hashlib
import json
import re
import shutil
import struct
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.browser_solid_models import collision_names, near_model_distances
from scripts.pilot.world_map_lab.export_full_game_world import img_directory
from scripts.pilot.world_map_lab.native_collisions import ENTRY, SECTOR

CHUNK = struct.Struct("<III")
MAX_GROUP = 8
MAX_BYTES = 16 * 1024**2


def chunk_header(stream, end):
    start = stream.tell()
    if start + CHUNK.size > end:
        raise ValueError("truncated RenderWare header")
    kind, size, version = CHUNK.unpack(stream.read(CHUNK.size))
    if start + CHUNK.size + size > end:
        raise ValueError("truncated RenderWare chunk")
    return kind, size, version


def dictionary(stream, start, length):
    stream.seek(start)
    kind, size, version = chunk_header(stream, start + length)
    if kind != 0x16:
        raise ValueError("expected a texture dictionary")
    end = stream.tell() + size
    kind, size, struct_version = chunk_header(stream, end)
    if kind != 1 or size != 4:
        raise ValueError("unsupported dictionary struct")
    count, device = struct.unpack("<HH", stream.read(4))
    members = []
    for _ in range(count):
        offset = stream.tell()
        kind, size, _ = chunk_header(stream, end)
        if kind != 0x15:
            raise ValueError("expected a native texture")
        tex_end = stream.tell() + size
        kind, native_size, _ = chunk_header(stream, tex_end)
        if kind != 1 or native_size < 72:
            raise ValueError("incomplete native texture")
        (platform,) = struct.unpack("<I", stream.read(4))
        if platform not in (8, 9):
            raise ValueError(f"unsupported raster platform {platform}")
        stream.read(4)
        name = stream.read(32).partition(b"\0")[0].lower()
        members.append((name, offset, size + CHUNK.size))
        stream.seek(tex_end)
    ext = stream.read(end - stream.tell())
    if len(ext) != CHUNK.size or CHUNK.unpack(ext)[:2] != (3, 0):
        raise ValueError("dictionary extension requires a specific merge rule")
    if any(stream.read(start + length - end)):
        raise ValueError("unexpected content following dictionary")
    return (version, struct_version, device, ext), members


def read_bindings(rows):
    section = None
    models, parents = {}, {}
    for raw in rows:
        row = raw.partition("#")[0].strip().lower()
        if not row:
            continue
        if section is None:
            section = row
        elif row == "end":
            section = None
        elif section == "txdp":
            child, parent = row.replace(",", " ").split()
            if child in parents and parents[child] != parent:
                raise ValueError("ambiguous texture parent " + child)
            parents[child] = parent
        elif section in {"objs", "tobj", "anim"}:
            _, model, name, *_ = (v.strip() for v in row.split(","))
            models[model] = name
        else:
            raise ValueError("unhandled IDE section " + section)
    if section is not None:
        raise ValueError("unterminated IDE section")
    return models, parents


def resource_names(banks, models):
    """Conservatively include every possible native texture string used by each DFF."""
    known = set()
    directories = {bank: img_directory(bank) for bank in banks}
    for bank, directory in directories.items():
        with bank.open("rb") as stream:
            for name, (_, start, size) in directory.items():
                if name.endswith(".txd"):
                    _, members = dictionary(stream, start, size)
                    known.update(member[0] for member in members)
    if any(not k or len(k) >= 32 or not all(32 <= b <= 126 for b in k) for k in known):
        raise ValueError("this source requires non-ASCII or full-width texture name support")
    tokens = re.compile(rb"[ -~]{1,32}\x00")
    referenced = {name: set() for name in models.values()}
    seen = set()
    for bank, directory in directories.items():
        with bank.open("rb") as stream:
            for name, (_, start, size) in directory.items():
                if not name.endswith(".dff") or name[:-4] not in models:
                    continue
                seen.add(name[:-4])
                stream.seek(start)
                # The prefix can be binary material flags. Its suffix still contains the name.
                strings = set(tokens.findall(stream.read(size)))
                used = referenced[models[name[:-4]]]
                for text in strings:
                    text = text[:-1].lower()
                    used.update(text[i:] for i in range(len(text)) if text[i:] in known)
    if missing := set(models) - seen:
        raise ValueError(
            "missing model while checking texture uses: " + ", ".join(sorted(missing)[:3])
        )
    return referenced


def rewrite_ide(rows, binding):
    output, emitted = [], set()
    section = None
    for line in rows:
        text = line.partition("#")[0].strip().lower()
        if text:
            if section is None:
                section = text
            elif text == "end":
                section = None
            elif section == "txdp":
                child, parent = text.replace(",", " ").split()
                link = (binding.get(child, child), binding.get(parent, parent))
                if link in emitted:
                    continue
                emitted.add(link)
                line = " ".join(link)
            else:
                fields = line.split(",")
                key = fields[2].strip().lower()
                if key in binding:
                    fields[2] = " " + binding[key]
                line = ",".join(fields)
        output.append(line)
    return output


def groups(stream, entries, parents, referenced):
    ancestors = set(parents.values())
    packs = []
    pending = []
    for name, (_, start, length) in entries.items():
        if not name.endswith(".txd"):
            continue
        signature, members = dictionary(stream, start, length)
        names = {m[0] for m in members}
        key = name[:-4]
        parent = parents.get(key)
        uses = referenced.get(key, set())
        # A parent keeps its identity for every descendant. A merged leaf may never
        # shadow an inherited lookup (including an originally missing texture).
        # Never change resolution order for a name shared by two dictionaries.
        for group in pending:
            if (
                key not in ancestors
                and group["parent"] == parent
                and group["signature"] == signature
                and group["used"].isdisjoint(names)
                and group["names"].isdisjoint(uses)
                and group["names"].isdisjoint(names)
                and group["size"] + length <= MAX_BYTES
                and len(group["sources"]) < MAX_GROUP
            ):
                break
        else:
            group = dict(
                signature=signature,
                parent=parent,
                used=set(),
                names=set(),
                size=0,
                sources=[],
                members=[],
            )
            pending.append(group)
            packs.append(group)
        group["sources"].append(name)
        group["size"] += length
        group["members"].extend(members)
        group["names"].update(names)
        group["used"].update(uses)
        if key in ancestors or len(group["sources"]) == MAX_GROUP or group["size"] >= MAX_BYTES:
            pending.remove(group)
    return packs


def packed_bytes(stream, group):
    version, struct_version, device, extension = group["signature"]
    members = group["members"]
    content = bytearray(CHUNK.pack(1, 4, struct_version) + struct.pack("<HH", len(members), device))
    for _, start, size in members:
        stream.seek(start)
        blob = stream.read(size)
        if len(blob) != size:
            raise ValueError("truncated texture payload")
        content.extend(blob)
    content.extend(extension)
    return CHUNK.pack(0x16, len(content), version) + content


def write_archive(source, dest, bank_id, binding, parents=None, referenced=None):
    entries = img_directory(source)
    expected = {}
    rows = []
    with source.open("rb") as original:
        packs = groups(original, entries, parents or {}, referenced or {})
        plain = [(name, origin) for name, origin in entries.items() if not name.endswith(".txd")]
        count = len(plain) + len(packs)
        with dest.open("xb") as out:
            out.seek(((8 + count * ENTRY.size + SECTOR - 1) // SECTOR) * SECTOR)

            def put(name, blob):
                offset = out.tell() // SECTOR
                sectors = (len(blob) + SECTOR - 1) // SECTOR
                if not 0 < sectors <= 65535:
                    raise ValueError("IMG entry cannot be represented")
                padded = blob + bytes(-len(blob) % SECTOR)
                out.write(padded)
                rows.append(ENTRY.pack(offset, sectors, 0, name.encode("ascii")))
                expected[name] = hashlib.sha256(padded).digest()

            for name, (_, start, size) in plain:
                original.seek(start)
                data = original.read(size)
                if len(data) != size:
                    raise ValueError("truncated source entry")
                put(name, data)
            for number, group in enumerate(packs):
                target = f"brd{bank_id:02x}{number:04x}"
                for name in group["sources"]:
                    key = name[:-4]
                    if key in binding:
                        raise ValueError("duplicate source dictionary " + key)
                    binding[key] = target
                put(target + ".txd", packed_bytes(original, group))
            out.seek(0)
            out.write(struct.pack("<4sI", b"VER2", count))
            out.writelines(rows)

        index = img_directory(dest)
        if set(index) != set(expected):
            raise ValueError("rebuilt IMG index differs")
        with dest.open("rb") as result:
            for name, (_, start, size) in index.items():
                result.seek(start)
                if hashlib.sha256(result.read(size)).digest() != expected[name]:
                    raise ValueError("IMG readback differs for " + name)
            for group in packs:
                target = binding[group["sources"][0][:-4]]
                _, start, size = index[target + ".txd"]
                signature, members = dictionary(result, start, size)
                if signature != group["signature"] or len(members) != len(group["members"]):
                    raise ValueError("changed texture dictionary layout")
                for before, after in zip(group["members"], members, strict=True):
                    if before[0] != after[0] or before[2] != after[2]:
                        raise ValueError("changed native texture metadata")
                    original.seek(before[1])
                    result.seek(after[1])
                    if original.read(before[2]) != result.read(after[2]):
                        raise ValueError("changed native texture payload")
    return len(packs)


def compact(source, target):
    source = source.resolve(strict=True)
    target = target.resolve()
    if source == target or target.is_relative_to(source) or target.exists():
        raise ValueError("choose a fresh output outside the staged game")
    manifest = json.loads((source / "sphere-full-world.json").read_bytes())
    if manifest["runtime"] != "browser-wasm":
        raise ValueError("expected an isolated browser game")
    rel = Path("data/maps/brworld")
    banks = sorted((source / rel).glob("brw*.img"))
    if len(banks) != manifest["additionalImageArchives"]:
        raise ValueError("missing staged archive")
    source_names = {
        name[:-4] for bank in banks for name in img_directory(bank) if name.endswith(".txd")
    }
    ide_rows = (source / rel / "brworld.ide").read_text("ascii").splitlines()
    models, parents = read_bindings(ide_rows)
    required = set(models.values()) | set(parents) | set(parents.values())
    inherited = required - source_names
    if inherited - {"generic"}:
        raise ValueError("unresolved external dictionaries: " + ", ".join(sorted(inherited)))
    referenced = resource_names(banks, models)
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent) as tmp:
        dest = Path(tmp) / "game"
        shutil.copytree(
            source,
            dest,
            ignore=lambda folder, names: (
                [b.name for b in banks] if Path(folder) == source / rel else []
            ),
        )
        binding = {}
        totals = {}
        for i, bank in enumerate(banks):
            totals[bank.name] = write_archive(
                bank, dest / rel / bank.name, i, binding, parents, referenced
            )
            print(f"{bank.name}: {totals[bank.name]} packed dictionaries", flush=True)
        rows = rewrite_ide(ide_rows, binding)
        after_models, after_parents = read_bindings(rows)
        if after_models != {model: binding.get(name, name) for model, name in models.items()}:
            raise ValueError("material binding changed")
        for child, parent in parents.items():
            if after_parents.get(binding.get(child, child)) != binding.get(parent, parent):
                raise ValueError("dictionary inheritance changed for " + child)
        colliders = set()
        for bank in banks:
            with bank.open("rb") as stream:
                for name, (_, at, length) in img_directory(bank).items():
                    if name.endswith(".col"):
                        stream.seek(at)
                        colliders.update(collision_names(stream.read(length)))
        scenes = (p.read_text("ascii") for p in sorted((source / rel).glob("*.ipl")))
        ide, near_report = near_model_distances("\n".join(rows), scenes, colliders)
        (dest / rel / "brworld.ide").write_bytes(ide.encode("ascii"))
        report = dict(
            nearCollisionModels=near_report,
            sourceDictionaries=len(binding),
            packedDictionaries=sum(totals.values()),
            archives=totals,
            inherited=sorted(inherited),
            binding=binding,
            routeSha256=manifest["routeSha256"],
        )
        (dest / "sphere-texture-packing.json").write_text(
            json.dumps(report, indent=2), encoding="utf8"
        )
        dest.rename(target)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("game", type=Path)
    cli.add_argument("destination", type=Path)
    args = cli.parse_args()
    compact(args.game, args.destination)
