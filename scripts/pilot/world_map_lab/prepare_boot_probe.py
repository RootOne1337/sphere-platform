"""Authored minimal English UI strings for the isolated native engine boot experiment."""

import struct
import zlib


def language_table():
    # PC GXT v4, single MAIN table, CRC32 keys with the game's uncomplemented accumulator.
    entries = {"CDERROR": "Test data unavailable", "FEM_STA": "Start", "FET_QG": "Quit"}
    keys = []
    strings = bytearray()
    for name, text in entries.items():
        keys.append((zlib.crc32(name.encode("ascii")) ^ 0xFFFFFFFF, len(strings)))
        strings.extend(text.encode("ascii") + b"\0")

    def chunk(name, data):
        return struct.pack("<4sI", name, len(data)) + data

    return (
        struct.pack("<HH", 4, 8)
        + chunk(b"TABL", struct.pack("<8sI", b"MAIN", 24))
        + chunk(b"TKEY", b"".join(struct.pack("<II", offset, key) for key, offset in sorted(keys)))
        + chunk(b"TDAT", strings)
    )
