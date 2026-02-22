# backend/api/v1/streaming/binary_handler.py
# ВЛАДЕЛЕЦ: TZ-05 SPLIT-3.
# Валидация бинарного фрейма Sphere Wire Format перед передачей в VideoStreamBridge.
from __future__ import annotations

import struct
import structlog

logger = structlog.get_logger()

# ─── Wire format constants (must match FramePackager.kt) ────────────────────
FRAME_VERSION = 0x01
HEADER_SIZE = 14          # FIX-5.1: 1+1+8+4
FLAG_KEYFRAME = 0x01


def validate_frame(data: bytes) -> bool:
    """
    Returns True if *data* is a well-formed Sphere H.264 binary frame.

    Checks:
    - Minimum header length (14 bytes)
    - Version field = 0x01
    - Embedded frame_size matches actual data length
    """
    if len(data) < HEADER_SIZE:
        logger.warning("Frame too short", size=len(data), min_size=HEADER_SIZE)
        return False

    version = data[0]
    if version != FRAME_VERSION:
        logger.warning("Unknown frame version", version=version)
        return False

    # timestamp: data[2:10] — not validated, any value is acceptable
    # frame_size: data[10:14]
    (frame_size,) = struct.unpack_from(">I", data, 10)
    expected_total = HEADER_SIZE + frame_size

    if len(data) != expected_total:
        logger.warning(
            "Frame size mismatch",
            expected=expected_total,
            actual=len(data),
            header_frame_size=frame_size,
        )
        return False

    return True


def is_keyframe(data: bytes) -> bool:
    """Returns True if the keyframe flag is set in the Sphere frame header."""
    if len(data) < 2:
        return False
    return bool(data[1] & FLAG_KEYFRAME)


def parse_timestamp_ms(data: bytes) -> int | None:
    """Extract the 64-bit timestamp (ms) from the frame header."""
    if len(data) < 10:
        return None
    (ts,) = struct.unpack_from(">q", data, 2)   # signed 64-bit big-endian
    return ts
