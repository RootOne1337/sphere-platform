# backend/websocket/frames.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-3. H.264 NAL unit frame types для приоритизации backpressure.
from __future__ import annotations

import time
from enum import IntEnum


class FrameType(IntEnum):
    """H.264 NAL unit types для приоритизации."""
    UNKNOWN = 0
    NON_IDR = 1      # P-frame — можно дропать
    IDR_SLICE = 5    # I-frame — ключевой, НЕЛЬЗЯ дропать
    SEI = 6          # SEI metadata — можно дропать
    SPS = 7          # SPS — критично для декодера
    PPS = 8          # PPS — критично для декодера


_SPHERE_FRAME_HEADER_SIZE = 14
_SPHERE_FRAME_VERSION = 0x01
_ANNEX_B_START_CODE_3 = b"\x00\x00\x01"
_ANNEX_B_START_CODE_4 = b"\x00\x00\x00\x01"


def _unwrap_sphere_frame(data: bytes) -> tuple[bytes, bool]:
    """Return the H.264 payload and keyframe flag for a complete Sphere frame."""
    if len(data) < _SPHERE_FRAME_HEADER_SIZE or data[0] != _SPHERE_FRAME_VERSION:
        return data, False

    payload_size = int.from_bytes(data[10:14], "big")
    if payload_size != len(data) - _SPHERE_FRAME_HEADER_SIZE:
        return data, False

    return data[_SPHERE_FRAME_HEADER_SIZE:], bool(data[1] & 0x01)


def _detect_nal_type(payload: bytes) -> FrameType:
    if len(payload) < 4:
        return FrameType.UNKNOWN

    # Annex B permits both 3-byte and 4-byte start codes. Check four bytes first
    # so a 4-byte prefix is not mistaken for its overlapping 3-byte suffix.
    nal_offset = -1
    for i in range(len(payload) - 2):
        if payload[i : i + 4] == _ANNEX_B_START_CODE_4:
            nal_offset = i + 4
            break
        if payload[i : i + 3] == _ANNEX_B_START_CODE_3:
            nal_offset = i + 3
            break

    if nal_offset < 0 or nal_offset >= len(payload):
        return FrameType.UNKNOWN

    nal_unit_type = payload[nal_offset] & 0x1F
    try:
        return FrameType(nal_unit_type)
    except ValueError:
        return FrameType.UNKNOWN


def detect_nal_type(data: bytes) -> FrameType:
    """Detect an H.264 NAL in raw Annex-B bytes or the Sphere binary wire frame."""
    payload, _ = _unwrap_sphere_frame(data)
    return _detect_nal_type(payload)


def detect_first_nal_type(data: bytes) -> FrameType:
    """Classify an access unit's leading NAL in O(1), for hot-path telemetry."""
    payload, _ = _unwrap_sphere_frame(data)
    if payload.startswith(_ANNEX_B_START_CODE_4):
        nal_offset = 4
    elif payload.startswith(_ANNEX_B_START_CODE_3):
        nal_offset = 3
    else:
        return FrameType.UNKNOWN
    if nal_offset >= len(payload):
        return FrameType.UNKNOWN
    try:
        return FrameType(payload[nal_offset] & 0x1F)
    except ValueError:
        return FrameType.UNKNOWN


class VideoFrame:
    __slots__ = ("data", "nal_type", "keyframe_flag", "timestamp", "device_id")

    def __init__(self, data: bytes, device_id: str) -> None:
        self.data = data
        self.device_id = device_id
        payload, self.keyframe_flag = _unwrap_sphere_frame(data)
        self.nal_type = _detect_nal_type(payload)
        self.timestamp = time.monotonic()

    @property
    def is_critical(self) -> bool:
        """Protect codec configuration and keyframes from latency/backpressure drops."""
        return self.keyframe_flag or self.nal_type in (
            FrameType.IDR_SLICE,
            FrameType.SPS,
            FrameType.PPS,
        )

    @property
    def size_kb(self) -> float:
        return len(self.data) / 1024
