# -*- coding: utf-8 -*-
"""
Сценарий S5: Видео-стриминг.

Проверяет массовую отправку бинарных H.264 фреймов
через WebSocket. Включается для 5% агентов (streamers).
Измеряет пропускную способность, fps, frame loss.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tests.load.core.agent_pool import AgentPool
from tests.load.core.metrics_collector import MetricsCollector

logger = logging.getLogger("loadtest.scenario.video")


class VideoStreamingScenario:
    """Сценарий массового видео-стриминга.

    Работает поверх AgentPool — стримеры уже запускают
    VideoStreamer внутри VirtualAgent. Здесь мы мониторим метрики.
    """

    def __init__(
        self,
        pool: AgentPool,
        metrics: MetricsCollector,
    ) -> None:
        self._pool = pool
        self._metrics = metrics

    async def run(self, hold_sec: float = 60.0) -> dict[str, Any]:
        """Мониторинг видео-стриминга *hold_sec* секунд."""
        logger.info("S5: Мониторинг видео %.0f сек", hold_sec)

        t0 = time.monotonic()

        # Начальные счётчики
        initial = self._metrics.snapshot()
        initial_frames = initial.get("counters", {}).get("video_frames_sent", 0)

        while (time.monotonic() - t0) < hold_sec:
            await asyncio.sleep(10.0)
            snap = self._metrics.snapshot()
            frames = snap.get("counters", {}).get("video_frames_sent", 0)
            delta = frames - initial_frames
            elapsed = time.monotonic() - t0
            fps = delta / max(elapsed, 1)
            logger.info("  S5 → frames=%d  avg_fps=%.1f", delta, fps)

        duration = time.monotonic() - t0
        final = self._metrics.snapshot()
        total_frames = (
            final.get("counters", {}).get("video_frames_sent", 0) - initial_frames
        )
        avg_fps = total_frames / max(duration, 1)

        # Размер фреймов
        frame_size = final.get("histograms", {}).get("video_frame_size", {})

        summary = {
            "scenario": "S5_VideoStreaming",
            "duration_sec": round(duration, 2),
            "total_frames": total_frames,
            "avg_fps": round(avg_fps, 1),
            "frame_size_p50": frame_size.get("p50", 0),
            "frame_size_p99": frame_size.get("p99", 0),
            "online": self._pool.online_count,
        }
        logger.info("S5 результат: %s", summary)
        return summary
