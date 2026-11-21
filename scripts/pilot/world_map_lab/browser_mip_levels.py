"""Select existing D3D9 RGBA mip levels in a staged map without retouching the images."""

import struct

from scripts.pilot.world_map_lab.native_collisions import ENTRY, SECTOR, img_directory

CHUNK = struct.Struct("<III")


def chunks(blob):
    at = 0
    while at < len(blob):
        if at + CHUNK.size > len(blob):
            raise ValueError("truncated texture chunk")
        tag, length, version = CHUNK.unpack_from(blob, at)
        end = at + CHUNK.size + length
        if end > len(blob):
            raise ValueError("truncated texture chunk")
        yield tag, version, blob[at + CHUNK.size : end]
        at = end


def chunk(tag, version, data):
    return CHUNK.pack(tag, len(data), version) + data


def trim_native(data, side):
    if len(data) < 88 or struct.unpack_from("<I", data)[0] != 9:
        return data
    width, height, depth, levels = struct.unpack_from("<HHBB", data, 80)
    if depth != 32 or struct.unpack_from("<I", data, 76)[0] != 21 or levels <= 1:
        return data
    offset, first, drop = 88, 88, 0
    for level in range(levels):
        if offset + 4 > len(data):
            raise ValueError("truncated mip length")
        size = struct.unpack_from("<I", data, offset)[0]
        if size != max(1, width >> level) * max(1, height >> level) * 4:
            raise ValueError("unexpected RGBA mip dimensions")
        offset += 4 + size
        if level + 1 < levels and max(width, height) >> level > side:
            drop, first = level + 1, offset
    if offset != len(data):
        raise ValueError("mip chain length mismatch")
    if not drop:
        return data
    header = bytearray(data[:88])
    struct.pack_into("<HH", header, 80, max(1, width >> drop), max(1, height >> drop))
    header[85] = levels - drop
    return header + data[first:]


def trim_dictionary(data, side):
    tag, size, version = CHUNK.unpack_from(data)
    if tag != 22 or size + 12 > len(data) or any(data[12 + size :]):
        raise ValueError("invalid texture dictionary")
    result = bytearray()
    for kind, rev, payload in chunks(data[12 : 12 + size]):
        if kind == 21:
            payload = b"".join(
                chunk(key, v, trim_native(part, side) if key == 1 else part)
                for key, v, part in chunks(payload)
            )
        result.extend(chunk(kind, rev, payload))
    return chunk(tag, version, result)


def write_mip_archive(source, target, side):
    if side < 1 or side & (side - 1):
        raise ValueError("expected a power-of-two texture limit")
    directory = img_directory(source)
    records = []
    with source.open("rb") as inp, target.open("xb") as out:
        header_bytes = 8 + len(directory) * ENTRY.size
        out.seek((header_bytes + SECTOR - 1) // SECTOR * SECTOR)
        for name, (_, offset, length) in directory.items():
            inp.seek(offset)
            raw = inp.read(length)
            if len(raw) != length:
                raise ValueError("truncated input archive")
            if name.endswith(".txd"):
                raw = trim_dictionary(raw, side)
            sectors = (len(raw) + SECTOR - 1) // SECTOR
            records.append(ENTRY.pack(out.tell() // SECTOR, sectors, 0, name.encode("ascii")))
            out.write(raw)
            out.write(bytes(-len(raw) % SECTOR))
        out.seek(0)
        out.write(struct.pack("<4sI", b"VER2", len(records)))
        out.writelines(records)
    if img_directory(target).keys() != directory.keys():
        raise ValueError("changed archive directory")
