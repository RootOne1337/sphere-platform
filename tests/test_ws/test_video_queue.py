# tests/test_ws/test_video_queue.py
# TZ-03 SPLIT-3: Tests for VideoStreamQueue backpressure and frame drop strategy.
from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio

from backend.websocket.frames import FrameType, VideoFrame, detect_nal_type
from backend.websocket.video_queue import VideoStreamQueue


# ── Helper factories ─────────────────────────────────────────────────────────

def make_idr_frame(device_id: str = "dev-1") -> VideoFrame:
    """Создать I-frame (IDR) с правильным NAL start code."""
    # NAL unit: start_code + IDR byte (0x65 = 0b01100101, type = 0x05 = 5)
    data = b"\x00\x00\x00\x01\x65" + b"\xff" * 100
    frame = VideoFrame(data, device_id)
    assert frame.nal_type == FrameType.IDR_SLICE
    return frame


def make_p_frame(device_id: str = "dev-1") -> VideoFrame:
    """Создать P-frame (non-IDR) с правильным NAL start code."""
    # NAL unit: start_code + non-IDR byte (0x41 = 0b01000001, type = 0x01 = 1)
    data = b"\x00\x00\x00\x01\x41" + b"\xaa" * 50
    frame = VideoFrame(data, device_id)
    assert frame.nal_type == FrameType.NON_IDR
    return frame


def make_sps_frame(device_id: str = "dev-1") -> VideoFrame:
    """Создать SPS frame (критичен)."""
    # NAL unit type = 7 (0b01100111)
    data = b"\x00\x00\x00\x01\x67" + b"\x00" * 20
    frame = VideoFrame(data, device_id)
    assert frame.nal_type == FrameType.SPS
    return frame


# ── FrameType detection ───────────────────────────────────────────────────────

class TestNALDetection:
    def test_detect_idr_slice(self):
        data = b"\x00\x00\x00\x01\x65abc"
        assert detect_nal_type(data) == FrameType.IDR_SLICE

    def test_detect_non_idr(self):
        data = b"\x00\x00\x00\x01\x41abc"
        assert detect_nal_type(data) == FrameType.NON_IDR

    def test_detect_sps(self):
        data = b"\x00\x00\x00\x01\x67abc"
        assert detect_nal_type(data) == FrameType.SPS

    def test_detect_pps(self):
        data = b"\x00\x00\x00\x01\x68abc"
        assert detect_nal_type(data) == FrameType.PPS

    def test_detect_sei(self):
        data = b"\x00\x00\x00\x01\x06abc"
        assert detect_nal_type(data) == FrameType.SEI

    def test_unknown_for_short_data(self):
        assert detect_nal_type(b"\x00\x01") == FrameType.UNKNOWN

    def test_unknown_for_no_start_code(self):
        data = b"\xff\xfe\xfd\xfc\xfb"
        assert detect_nal_type(data) == FrameType.UNKNOWN


class TestVideoFrame:
    def test_idr_is_critical(self):
        frame = make_idr_frame()
        assert frame.is_critical is True

    def test_p_frame_not_critical(self):
        frame = make_p_frame()
        assert frame.is_critical is False

    def test_sps_is_critical(self):
        frame = make_sps_frame()
        assert frame.is_critical is True

    def test_size_kb(self):
        data = b"\x00\x00\x00\x01\x65" + b"\xff" * 1019  # ~1KB
        frame = VideoFrame(data, "dev-1")
        assert abs(frame.size_kb - 1.0) < 0.01


# ── VideoStreamQueue ──────────────────────────────────────────────────────────

class TestVideoStreamQueue:
    @pytest.fixture
    def queue(self):
        return VideoStreamQueue("dev-1")

    async def test_put_and_get_frame(self, queue):
        frame = make_idr_frame()
        added = await queue.put(frame)
        assert added is True

        retrieved = await queue.get()
        assert retrieved is frame

    async def test_get_empty_queue_returns_none(self, queue):
        result = await queue.get()
        assert result is None

    async def test_frames_queued_counter(self, queue):
        for _ in range(5):
            await queue.put(make_p_frame())
        assert queue.frames_queued == 5

    async def test_frames_sent_counter(self, queue):
        await queue.put(make_p_frame())
        await queue.get()
        assert queue.frames_sent == 1

    async def test_p_frame_dropped_when_queue_full(self, queue):
        # Заполнить очередь критичными (SPS) фреймами — нельзя дропать
        # VideoStreamQueue.MAX_SIZE = 50
        for _ in range(VideoStreamQueue.MAX_SIZE):
            f = make_sps_frame()  # критичный — не дропается
            await queue.put(f)

        # Теперь пытаемся добавить P-frame — должен быть дропнут
        p_frame = make_p_frame()
        result = await queue.put(p_frame)
        assert result is False
        assert queue.frames_dropped >= 1

    async def test_idr_frame_not_dropped_when_queue_full_of_droppable(self, queue):
        """IDR frame должен быть добавлен, даже если очередь полная P-frames."""
        # Заполнить очередь P-frames
        for _ in range(VideoStreamQueue.MAX_SIZE):
            await queue.put(make_p_frame())

        # IDR frame не должен быть дропнут — один P-frame дропается вместо
        idr = make_idr_frame()
        result = await queue.put(idr)
        assert result is True

    async def test_drop_ratio_zero_initially(self, queue):
        assert queue.drop_ratio == 0.0

    async def test_drop_ratio_after_drops(self, queue):
        # Добавить 5 фреймов, потом дропнуть 1
        # Заполняем до MAX_SIZE SPS фреймами
        for _ in range(VideoStreamQueue.MAX_SIZE):
            await queue.put(make_sps_frame())
        await queue.put(make_p_frame())  # дропнутый
        assert queue.drop_ratio > 0.0

    async def test_stale_p_frames_evicted(self, queue):
        """P-frames старше MAX_LATENCY_MS удаляются при следующем put."""
        # Создать P-frame и вручную состарить его
        old_frame = make_p_frame()
        old_frame.timestamp = time.monotonic() - (VideoStreamQueue.MAX_LATENCY_MS / 1000.0 + 1)
        await queue.put(old_frame)

        # Новый фрейм триггерит eviction
        new_frame = make_idr_frame()
        await queue.put(new_frame)

        # Старый P-frame должен быть выброшен
        all_frames = []
        while True:
            f = await queue.get()
            if f is None:
                break
            all_frames.append(f)

        assert old_frame not in all_frames
        assert new_frame in all_frames

    async def test_critical_frames_not_evicted_when_stale(self, queue):
        """IDR/SPS/PPS фреймы НЕ дропаются даже если устарели."""
        old_idr = make_idr_frame()
        old_idr.timestamp = time.monotonic() - 10.0  # 10s старый
        await queue.put(old_idr)

        # Новый P-frame триггерит eviction
        new_p = make_p_frame()
        await queue.put(new_p)

        # IDR должен сохраниться
        frames = []
        while True:
            f = await queue.get()
            if f is None:
                break
            frames.append(f)
        assert old_idr in frames

    async def test_queue_size_property(self, queue):
        assert queue.size == 0
        await queue.put(make_p_frame())
        assert queue.size == 1
        await queue.get()
        assert queue.size == 0
