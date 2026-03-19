# -*- coding: utf-8 -*-
"""
Эмулятор видео-стриминга (H.264 NAL-юниты).

Генерирует поток бинарных фреймов, имитирующих H.264 данные
от MediaProjection на Android-устройстве.

Параметры NAL-юнитов приближены к реальным — SPS (67), PPS (68),
IDR (65), non-IDR (61). Размеры кадров варьируются для реалистичности.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import struct
import time

from tests.load.core.metrics_collector import MetricsCollector

logger = logging.getLogger("loadtest.video")

# NAL unit types (first byte after start code, & 0x1f)
_NAL_SPS = 7    # 0x67
_NAL_PPS = 8    # 0x68
_NAL_IDR = 5    # 0x65
_NAL_SLICE = 1  # 0x61 (non-IDR)

# Размеры (байт)
_SPS_SIZE = 32
_PPS_SIZE = 8
_IDR_FRAME_MIN = 8_000
_IDR_FRAME_MAX = 25_000
_P_FRAME_MIN = 800
_P_FRAME_MAX = 4_000

# GOP: IDR каждые 30 кадров
_GOP_SIZE = 30


class VideoStreamer:
    """Эмулятор H.264 стриминга по WebSocket (бинарные фреймы).

    Параметры:
        send_fn: Корутина для отправки бинарного фрейма
                 (например, ws_client.send_binary).
        fps: Целевой FPS (по умолчанию 15).
        metrics: Сборщик метрик.
        device_id: ID устройства (для логов).
    """

    def __init__(
        self,
        send_fn,
        fps: int = 15,
        metrics: MetricsCollector | None = None,
        device_id: str = "",
    ) -> None:
        self._send = send_fn
        self._fps = fps
        self._metrics = metrics
        self._device_id = device_id
        self._frame_interval = 1.0 / fps
        self._running = False
        self._frame_count = 0

    async def start(self, stop_event: asyncio.Event) -> None:
        """Стриминг до установки stop_event."""
        self._running = True
        self._frame_count = 0
        logger.debug("Video START [%s] fps=%d", self._device_id, self._fps)

        # Отправляем SPS+PPS как первые фреймы
        await self._send_sps_pps()

        try:
            while self._running and not stop_event.is_set():
                t0 = time.monotonic()

                nal_data = self._generate_frame()
                ok = await self._send(nal_data)

                if not ok:
                    logger.debug(
                        "Video send failed [%s], stopping", self._device_id
                    )
                    break

                self._frame_count += 1
                if self._metrics:
                    self._metrics.inc("video_frames_sent")
                    self._metrics.record(
                        "video_frame_size", len(nal_data)
                    )

                # Выдерживаем FPS
                elapsed = time.monotonic() - t0
                sleep_time = self._frame_interval - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            logger.debug(
                "Video STOP [%s] frames=%d", self._device_id, self._frame_count
            )

    def stop(self) -> None:
        """Остановить стриминг."""
        self._running = False

    # ---------------------------------------------------------------
    # Генерация NAL-юнитов
    # ---------------------------------------------------------------

    async def _send_sps_pps(self) -> None:
        """Отправить SPS и PPS (начало стрима)."""
        sps = self._make_nal(_NAL_SPS, _SPS_SIZE)
        pps = self._make_nal(_NAL_PPS, _PPS_SIZE)
        await self._send(sps + pps)

    def _generate_frame(self) -> bytes:
        """Генерировать один NAL-юнит (IDR или P-frame)."""
        if self._frame_count % _GOP_SIZE == 0:
            # IDR (ключевой кадр)
            size = random.randint(_IDR_FRAME_MIN, _IDR_FRAME_MAX)
            return self._make_nal(_NAL_IDR, size)
        else:
            # P-frame
            size = random.randint(_P_FRAME_MIN, _P_FRAME_MAX)
            return self._make_nal(_NAL_SLICE, size)

    @staticmethod
    def _make_nal(nal_type: int, payload_size: int) -> bytes:
        """Собрать NAL-юнит: start_code + header + payload."""
        # Start code: 0x00000001 (4 bytes)
        start_code = b"\x00\x00\x00\x01"

        # NAL header: forbidden_zero_bit(0) + nal_ref_idc(3) + nal_unit_type
        # nal_ref_idc = 3 для SPS/PPS/IDR, 2 для P-frame
        if nal_type in (_NAL_SPS, _NAL_PPS, _NAL_IDR):
            header_byte = (3 << 5) | nal_type  # 0x60 | type
        else:
            header_byte = (2 << 5) | nal_type  # 0x40 | type

        header = struct.pack("B", header_byte)
        payload = os.urandom(payload_size)

        return start_code + header + payload
