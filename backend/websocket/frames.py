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


def detect_nal_type(data: bytes) -> FrameType:
    """Определить тип NAL unit по первым байтам (после start code)."""
    if len(data) < 5:
        return FrameType.UNKNOWN

    # Найти start code 0x00 0x00 0x00 0x01
    start = -1
    for i in range(len(data) - 4):
        if data[i : i + 4] == b"\x00\x00\x00\x01":
            start = i + 4
            break

    if start == -1 or start >= len(data):
        return FrameType.UNKNOWN

    nal_unit_type = data[start] & 0x1F
    try:
        return FrameType(nal_unit_type)
    except ValueError:
        return FrameType.UNKNOWN


class VideoFrame:
    __slots__ = ("data", "nal_type", "timestamp", "device_id")

    def __init__(self, data: bytes, device_id: str) -> None:
        self.data = data
        self.device_id = device_id
        self.nal_type = detect_nal_type(data)
        self.timestamp = time.monotonic()

    @property
    def is_critical(self) -> bool:
        """I-frame, SPS, PPS — нельзя дропать."""
        return self.nal_type in (FrameType.IDR_SLICE, FrameType.SPS, FrameType.PPS)

    @property
    def size_kb(self) -> float:
        return len(self.data) / 1024
