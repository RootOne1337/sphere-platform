"""Bind an area's GTA collision models to gameplay IDs and stream them from its IMG."""

import hashlib
import shutil
import struct

COL = struct.Struct("<4sI22sH")
ENTRY = struct.Struct("<IHH24s")
SECTOR = 2048
COL_NAME = b"spherebr.col"


def img_directory(path):
    size = path.stat().st_size
    with path.open("rb") as stream:
        magic, count = struct.unpack("<4sI", stream.read(8))
        table_size = 8 + count * ENTRY.size
        if magic != b"VER2" or not count or table_size > size:
            raise ValueError(f"invalid IMG table in {path}")
        entries = {}
        for sector, logical, physical, raw in ENTRY.iter_unpack(stream.read(count * ENTRY.size)):
            name = raw.split(b"\0")[0].decode("ascii").lower()
            start, length = sector * SECTOR, (physical or logical) * SECTOR
            if (
                not name
                or name in entries
                or start < table_size
                or not length
                or start + length > size
            ):
                raise ValueError(f"invalid IMG entry {name} in {path}")
            entries[name] = (path, start, length)
        return entries


def bind_collisions(raw, ids):
    data = bytearray(raw)
    offset = 0
    names = set()
    while offset < len(data):
        if len(data) - offset < COL.size:
            raise ValueError("truncated COL record")
        tag, size, name_bytes, _ = COL.unpack_from(data, offset)
        end = offset + 8 + size
        # The pinned engine's first streaming pass understands these three formats.
        if (
            tag not in (b"COLL", b"COL2", b"COL3")
            or not COL.size <= end - offset <= len(data) - offset
        ):
            raise ValueError("unsupported or incomplete streamed collision")
        name = name_bytes.partition(b"\0")[0].decode("ascii").lower()
        if name in names or name not in ids or not 0 <= ids[name] < 20000:
            raise ValueError("duplicate or unbound collision " + name)
        names.add(name)
        struct.pack_into("<H", data, offset + COL.size - 2, ids[name])
        offset = end
    if not names:
        raise ValueError("empty collision archive")
    return data


def write_game_img(source, destination, collision):
    """Copy original sectors unchanged, extending the directory even at its sector boundary."""
    with source.open("rb") as inp, destination.open("xb") as out:
        magic, count = struct.unpack("<4sI", inp.read(8))
        if magic != b"VER2" or not count or 8 + count * ENTRY.size > source.stat().st_size:
            raise ValueError("invalid native IMG directory")
        directory = list(ENTRY.iter_unpack(inp.read(count * ENTRY.size)))
        data_start = min(entry[0] for entry in directory)
        file_size = source.stat().st_size
        if file_size % SECTOR or data_start * SECTOR < 8 + count * ENTRY.size:
            raise ValueError("IMG directory overlaps data")
        delta = max(0, (8 + (count + 1) * ENTRY.size + SECTOR - 1) // SECTOR - data_start)
        col_sector = file_size // SECTOR + delta
        col_size = (len(collision) + SECTOR - 1) // SECTOR
        if not 0 < col_size <= 65535:
            raise ValueError("collision bank exceeds IMG entry size")
        out.write(struct.pack("<4sI", magic, count + 1))
        for start, logical, physical, name in directory:
            if (start + (physical or logical)) * SECTOR > file_size or name.rstrip(
                b"\0"
            ).lower() == COL_NAME:
                raise ValueError("invalid or duplicate IMG entry")
            out.write(ENTRY.pack(start + delta, logical, physical, name))
        out.write(ENTRY.pack(col_sector, col_size, 0, COL_NAME))
        out.seek((data_start + delta) * SECTOR)
        inp.seek(data_start * SECTOR)
        shutil.copyfileobj(inp, out, 1024 * 1024)
        out.write(collision)
        out.write(bytes(-len(collision) % SECTOR))
    with destination.open("rb") as check:
        check.seek(8 + count * ENTRY.size)
        sector, size, _, name = ENTRY.unpack(check.read(ENTRY.size))
        check.seek(sector * SECTOR)
        if (
            name.rstrip(b"\0") != COL_NAME
            or size != col_size
            or check.read(len(collision)) != collision
        ):
            raise ValueError("streamed collision archive readback failed")
    return hashlib.sha256(collision).hexdigest()
