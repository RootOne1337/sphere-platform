# tests/test_services/test_binary_handler.py
# TZ-05 SPLIT-3: Unit-тесты для validate_frame, is_keyframe, parse_timestamp_ms.
from __future__ import annotations

import struct

from backend.api.v1.streaming.binary_handler import (
    FRAME_VERSION,
    HEADER_SIZE,
    is_keyframe,
    parse_timestamp_ms,
    validate_frame,
)


def _make_frame(
    frame_payload: bytes = b"",
    version: int = FRAME_VERSION,
    flags: int = 0x00,
    timestamp_ms: int = 1234567890,
) -> bytes:
    """Собрать корректный Sphere Wire Format фрейм."""
    header = struct.pack(
        ">BBqI",
        version,
        flags,
        timestamp_ms,
        len(frame_payload),
    )
    return header + frame_payload


class TestValidateFrame:
    def test_valid_frame_no_payload(self):
        assert validate_frame(_make_frame()) is True

    def test_valid_frame_with_payload(self):
        assert validate_frame(_make_frame(b"\x00" * 100)) is True

    def test_too_short_returns_false(self):
        assert validate_frame(b"\x01\x00") is False

    def test_empty_returns_false(self):
        assert validate_frame(b"") is False

    def test_wrong_version_returns_false(self):
        bad = _make_frame(version=0x02)
        assert validate_frame(bad) is False

    def test_size_mismatch_returns_false(self):
        """frame_size поле указывает 50 байт, а данных только 14 (пустая нагрузка)."""
        # Создаём фрейм с нагрузкой 10 байт, но обрезаем последние 5
        frame = _make_frame(b"\x00" * 10)
        assert validate_frame(frame[:-5]) is False

    def test_frame_size_prefix_too_large(self):
        """frame_size больше реальных данных → mismatch."""
        header = struct.pack(">BBqI", FRAME_VERSION, 0, 0, 9999)
        # нет нагрузки → actual != HEADER_SIZE + 9999
        assert validate_frame(header) is False

    def test_exactly_header_size_with_zero_payload(self):
        """frame_size=0 → valid, total=14."""
        frame = _make_frame(b"")
        assert len(frame) == HEADER_SIZE
        assert validate_frame(frame) is True


class TestIsKeyframe:
    def test_keyframe_flag_set(self):
        assert is_keyframe(_make_frame(flags=0x01)) is True

    def test_keyframe_flag_not_set(self):
        assert is_keyframe(_make_frame(flags=0x00)) is False

    def test_only_first_two_bytes_checked(self):
        """Флаг 0x01 во втором байте — keyframe."""
        data = bytes([FRAME_VERSION, 0xFF]) + b"\x00" * 12
        assert is_keyframe(data) is True

    def test_too_short_returns_false(self):
        assert is_keyframe(b"\x01") is False

    def test_empty_returns_false(self):
        assert is_keyframe(b"") is False


class TestParseTimestampMs:
    def test_returns_correct_timestamp(self):
        ts = 1_700_000_000_000
        frame = _make_frame(timestamp_ms=ts)
        assert parse_timestamp_ms(frame) == ts

    def test_zero_timestamp(self):
        frame = _make_frame(timestamp_ms=0)
        assert parse_timestamp_ms(frame) == 0

    def test_negative_timestamp(self):
        """64-bit signed — отрицательное значение допустимо."""
        frame = _make_frame(timestamp_ms=-1)
        assert parse_timestamp_ms(frame) == -1

    def test_too_short_returns_none(self):
        assert parse_timestamp_ms(b"\x01\x00") is None

    def test_empty_returns_none(self):
        assert parse_timestamp_ms(b"") is None

    def test_exactly_10_bytes_ok(self):
        data = struct.pack(">BBq", FRAME_VERSION, 0, 42)
        assert parse_timestamp_ms(data) == 42
