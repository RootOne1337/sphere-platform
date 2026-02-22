"""
TelemetryReporter — периодическая отправка psutil-метрик воркстанции.
Детальная реализация — TZ-08 SPLIT-3.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psutil
from loguru import logger

from .config import config

if TYPE_CHECKING:
    from .client import AgentWebSocketClient


class TelemetryReporter:
    def __init__(self, ws_client: "AgentWebSocketClient") -> None:
        self._ws = ws_client

    async def run(self) -> None:
        """Цикл периодической отправки метрик."""
        logger.info(
            f"Telemetry reporter запущен (интервал {config.telemetry_interval}с)"
        )
        while True:
            try:
                metrics = self._collect()
                await self._ws.send({"type": "telemetry", "data": metrics})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"Ошибка сбора телеметрии: {exc!r}")
            await asyncio.sleep(config.telemetry_interval)

    def _collect(self) -> dict:
        """Собирает CPU, RAM, disk метрики через psutil."""
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "workstation_id": config.workstation_id,
            "cpu_percent": cpu_pct,
            "memory_total_mb": mem.total // (1024 * 1024),
            "memory_used_mb": mem.used // (1024 * 1024),
            "memory_percent": mem.percent,
            "disk_total_gb": disk.total // (1024 ** 3),
            "disk_used_gb": disk.used // (1024 ** 3),
            "disk_percent": disk.percent,
        }
