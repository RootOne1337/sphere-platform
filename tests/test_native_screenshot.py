import base64
import hashlib
import struct
import uuid
import zlib
from unittest.mock import AsyncMock

import pytest

from backend.services.native_screenshot import (
    MAX_PNG_BYTES,
    PNG_SIGNATURE,
    READ_CHUNK_BYTES,
    InvalidScreenshot,
    capture_png,
    decode_chunk,
    png_geometry,
)


def png_fixture(width=2, height=1, padding=0):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + (chunk(b"tEXt", b"fixture\0" + b"x" * padding) if padding else b"")
            + chunk(b"IDAT", zlib.compress(b"\0" + b"\xff\0\0\xff" * width)) + chunk(b"IEND", b""))


def test_png_is_original_and_complete_without_video_resizing():
    data = png_fixture()
    assert png_geometry(data) == (2, 1)


@pytest.mark.parametrize("data", [b"", b"jpeg", PNG_SIGNATURE, png_fixture()[:-1],
    png_fixture() + b"trailing", png_fixture(0), png_fixture(4097),
    PNG_SIGNATURE + b"x" * MAX_PNG_BYTES, png_fixture()[:-16] + b"broken checksum!"],
    ids=["empty", "jpeg", "signature-only", "truncated", "trailing", "zero-width", "width-limit", "size-limit", "crc"])
def test_rejects_truncation_crc_trailing_bytes_geometry_and_size(data):
    with pytest.raises(InvalidScreenshot):
        png_geometry(data)


@pytest.mark.parametrize("text,expected", [("not-base64!", 1), (base64.b64encode(b"abc").decode(), 4),
    ("界", 1), ("A" * (180 * 1024 + 1), 1)], ids=["syntax", "short", "unicode", "size-limit"])
def test_rejects_invalid_or_incomplete_transport_chunks(text, expected):
    with pytest.raises(InvalidScreenshot):
        decode_chunk(text, expected)


async def test_chunking_keeps_exact_bytes_and_uuid_owned_cleanup():
    data = png_fixture(padding=READ_CHUNK_BYTES + 1)
    commands = []
    index = 0
    snapshot_id = uuid.uuid4().hex

    async def shell(command):
        nonlocal index
        commands.append(command)
        if command == "wm size":
            return "Physical size: 1x2"
        if command.startswith("wc -c "):
            return str(len(data)) + " native-file"
        if command.startswith("dd "):
            index = int(command.split("skip=")[1].split()[0])
        if command.startswith("base64 "):
            return base64.encodebytes(data[index * READ_CHUNK_BYTES:(index + 1) * READ_CHUNK_BYTES]).decode()
        return ""

    result = await capture_png(shell, snapshot_id)
    assert result.data == data and result.sha256 == hashlib.sha256(data).hexdigest()
    assert (result.width, result.height) == (2, 1) and result.cleanup_confirmed
    prefix = "/data/local/tmp/sphere-shot-" + snapshot_id
    assert commands[-1] == f"rm -f {prefix}.png {prefix}.part"
    assert len([c for c in commands if c.startswith("base64 ")]) == 2
    assert not any(char in "".join(commands) for char in "|;&$`(){}\\<>!#~\n\r")


async def test_capture_failure_preserved_even_when_cleanup_also_fails():
    shell = AsyncMock(side_effect=RuntimeError("transport unavailable"))
    with pytest.raises(RuntimeError, match="transport unavailable"):
        await capture_png(shell, uuid.uuid4().hex)
    assert shell.await_count == 2


async def test_size_limit_stops_before_any_binary_read_and_still_cleans_up():
    shell = AsyncMock(side_effect=["Physical size: 2x1", "", str(MAX_PNG_BYTES + 1), ""])
    with pytest.raises(InvalidScreenshot, match="5 MiB"):
        await capture_png(shell, uuid.uuid4().hex)
    assert shell.await_count == 4


async def test_invalid_owner_cannot_form_a_shell_path():
    shell = AsyncMock()
    with pytest.raises(ValueError):
        await capture_png(shell, "../../other")
    shell.assert_not_awaited()
