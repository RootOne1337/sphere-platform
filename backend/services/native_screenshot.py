"""One-shot original PNG through the installed APK's bounded root SHELL RPC.

No PC agent, video decoder, persistent artifact or command auto-retry. Chunked
reads stay below the APK's 256 KiB stdout cap. A deadline bounds slow WAN reads.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
import struct
import time
import uuid
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

from backend.services.ui_hierarchy import display_size

MAX_PNG_BYTES = 5 * 1024 * 1024
READ_CHUNK_BYTES = 128 * 1024
MAX_ENCODED_CHUNK_BYTES = 180 * 1024
MAX_PIXELS = 4096 * 4096
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class InvalidScreenshot(ValueError):
    """A full native screenshot was not obtained; never return partial bytes."""


def png_geometry(data: bytes) -> tuple[int, int]:
    """Validate complete bounded PNG structure/CRCs without inflating pixels."""
    if not 57 <= len(data) <= MAX_PNG_BYTES or not data.startswith(PNG_SIGNATURE):
        raise InvalidScreenshot("Original screenshot is not a bounded PNG")
    cursor, chunks = 8, 0
    width, height = 0, 0
    seen_data = False
    while cursor < len(data):
        chunks += 1
        if chunks > 4096 or cursor + 12 > len(data):
            raise InvalidScreenshot("Original PNG is incomplete")
        length = struct.unpack_from(">I", data, cursor)[0]
        kind = data[cursor + 4:cursor + 8]
        end = cursor + 12 + length
        if end > len(data):
            raise InvalidScreenshot("Original PNG is incomplete")
        content = data[cursor + 8:cursor + 8 + length]
        crc = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(kind + content) & 0xffffffff != crc:
            raise InvalidScreenshot("Original PNG checksum mismatch")
        if chunks == 1:
            if kind != b"IHDR" or length != 13:
                raise InvalidScreenshot("Original PNG has no valid header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", content)
            if (not 1 <= width <= 4096 or not 1 <= height <= 4096
                    or width * height > MAX_PIXELS or depth != 8 or color not in (2, 6)
                    or compression != 0 or filtering != 0 or interlace != 0):
                raise InvalidScreenshot("Original PNG geometry/format is unsupported")
        elif kind == b"IHDR":
            raise InvalidScreenshot("Original PNG has a repeated header")
        if kind == b"IDAT":
            seen_data = True
        if kind == b"IEND":
            if length or not seen_data or end != len(data):
                raise InvalidScreenshot("Original PNG is incomplete")
            return width, height
        cursor = end
    raise InvalidScreenshot("Original PNG is incomplete")


def decode_chunk(output: str, expected: int) -> bytes:
    if not isinstance(output, str) or len(output.encode()) > MAX_ENCODED_CHUNK_BYTES:
        raise InvalidScreenshot("Screenshot chunk exceeds the transport limit")
    try:
        data = base64.b64decode("".join(output.split()), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidScreenshot("Screenshot chunk encoding is invalid") from exc
    if len(data) != expected:
        raise InvalidScreenshot("Screenshot chunk is incomplete")
    return data


@dataclass
class NativeScreenshot:
    data: bytes
    width: int
    height: int
    sha256: str
    cleanup_confirmed: bool = False


@dataclass
class CaptureTrace:
    """Bounded stage metadata only: never commands, output, pixels or tokens."""

    started: float = field(default_factory=time.monotonic)
    phase: str = "initialize"
    rpc_count: int = 0
    completed_rpcs: int = 0
    failure_phase: str | None = None
    failure_rpc_index: int | None = None
    cleanup_confirmed: bool = False
    cleanup_failed: bool = False
    phase_elapsed_ms: dict[str, int] = field(default_factory=dict)

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((time.monotonic() - self.started) * 1000))


async def capture_png(shell: Callable[[str], Awaitable[str]], snapshot_id: str,
                      *, trace: CaptureTrace | None = None) -> NativeScreenshot:
    # UUID-owned paths only. Validate even when called outside the HTTP route.
    if uuid.UUID(hex=snapshot_id).hex != snapshot_id:
        raise ValueError("Invalid screenshot ID")
    path = f"/data/local/tmp/sphere-shot-{snapshot_id}.png"
    chunk_path = f"/data/local/tmp/sphere-shot-{snapshot_id}.part"
    trace = trace or CaptureTrace()
    screenshot = None

    async def step(phase: str, command: str) -> str:
        trace.rpc_count += 1
        index = trace.rpc_count
        if phase != "cleanup":
            trace.phase = phase
        started = time.monotonic()
        try:
            with structlog.contextvars.bound_contextvars(
                screenshot_id=snapshot_id, screenshot_phase=phase, screenshot_rpc_index=index,
            ):
                output = await shell(command)
            trace.completed_rpcs += 1
            return output
        except BaseException:
            if phase != "cleanup" and trace.failure_phase is None:
                trace.failure_phase, trace.failure_rpc_index = phase, index
            raise
        finally:
            trace.phase_elapsed_ms[phase] = trace.phase_elapsed_ms.get(phase, 0) + max(0, int((time.monotonic() - started) * 1000))

    try:
        async with asyncio.timeout(80):
            before = display_size(await step("display_before", "wm size"))
            await step("capture", f"screencap -p {path}")
            size_output = (await step("file_size", f"wc -c {path}")).split()
            if not size_output or not size_output[0].isdigit():
                raise InvalidScreenshot("Android did not report the screenshot size")
            size = int(size_output[0])
            if not 57 <= size <= MAX_PNG_BYTES:
                raise InvalidScreenshot("Original screenshot exceeds the 5 MiB limit or is empty")
            digest_output = await step("android_digest", f"sha256sum {path}")
            digest = (re.fullmatch(r"([a-f0-9]{64})[ \t]+\*?" + re.escape(path), digest_output.strip())
                      if isinstance(digest_output, str) and len(digest_output) <= 512 else None)
            if digest is None:
                raise InvalidScreenshot("Android did not confirm the original PNG checksum")
            data = bytearray()
            for index in range((size + READ_CHUNK_BYTES - 1) // READ_CHUNK_BYTES):
                await step("chunk_copy", f"dd if={path} of={chunk_path} bs={READ_CHUNK_BYTES} skip={index} count=1")
                output = await step("chunk_read", f"base64 {chunk_path}")
                data.extend(decode_chunk(output, min(READ_CHUNK_BYTES, size - len(data))))
            if display_size(await step("display_after", "wm size")) != before:
                raise InvalidScreenshot("Android display size changed during capture")
            trace.phase = "validate_png"
            raw = bytes(data)
            sha256 = hashlib.sha256(raw).hexdigest()
            if sha256 != digest.group(1):
                raise InvalidScreenshot("Original PNG changed during transfer")
            width, height = png_geometry(raw)
            if (width, height) not in (before, before[::-1]):
                raise InvalidScreenshot("Original PNG does not match the Android display size")
            screenshot = NativeScreenshot(raw, width, height, sha256)
            trace.phase = "complete"
            return screenshot
    except BaseException:
        if trace.failure_phase is None:
            trace.failure_phase = trace.phase
        raise
    finally:
        # One fixed cleanup command; installed SHELL allows multiple file args.
        try:
            await step("cleanup", f"rm -f {path} {chunk_path}")
            trace.cleanup_confirmed = True
            if screenshot is not None:
                screenshot.cleanup_confirmed = True
        except Exception:
            trace.cleanup_failed = True
            # Preserve the original error/snapshot. No raw commands or bytes
            # go into logs. The response exposes unconfirmed cleanup explicitly.
            pass
