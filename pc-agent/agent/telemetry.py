"""
TelemetryReporter — периодическая отправка psutil-метрик воркстанции.
SPHERE-043  TZ-08 SPLIT-3
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import psutil
from loguru import logger

from .config import config
from .models import DiskStats, NetworkStats, WorkstationTelemetry

if TYPE_CHECKING:
    from .client import AgentWebSocketClient
    from .ldplayer import LDPlayerManager


class TelemetryReporter:
    def __init__(
        self,
        ws_client: "AgentWebSocketClient",
        ldplayer_mgr: "LDPlayerManager | None" = None,
    ) -> None:
        self._ws = ws_client
        self._ldplayer = ldplayer_mgr

    async def run(self) -> None:
        """Цикл периодической отправки метрик."""
        logger.info(f"Telemetry reporter запущен (интервал {config.telemetry_interval}с)")
        while True:
            try:
                await asyncio.sleep(config.telemetry_interval)
                telemetry = await self._collect()
                await self._ws.send({
                    "type": "workstation_telemetry",
                    "payload": telemetry.model_dump(),
                })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"Ошибка сбора телеметрии: {exc!r}")

    async def _collect(self) -> WorkstationTelemetry:
        # CPU: cpu_percent(interval=1) блокирует на 1с — запускаем в executor
        # ⚠️ asyncio.get_running_loop(), не get_event_loop() (deprecated в 3.10+)
        loop = asyncio.get_running_loop()
        cpu_pct: float = await loop.run_in_executor(
            None, lambda: psutil.cpu_percent(interval=1)
        )

        mem = psutil.virtual_memory()

        # Физические диски (all=False исключает tmpfs, proc и т.п.)
        disks: list[DiskStats] = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append(
                    DiskStats(
                        path=part.mountpoint,
                        total_gb=round(usage.total / 1024 ** 3, 2),
                        used_gb=round(usage.used / 1024 ** 3, 2),
                        free_gb=round(usage.free / 1024 ** 3, 2),
                        percent=usage.percent,
                    )
                )
            except PermissionError:
                pass

        # Сетевые счётчики (абсолютные, не дельта — бэкенд считает diff)
        curr_net = psutil.net_io_counters()
        net = NetworkStats(
            bytes_sent=curr_net.bytes_sent,
            bytes_recv=curr_net.bytes_recv,
            packets_sent=curr_net.packets_sent,
            packets_recv=curr_net.packets_recv,
        )

        # Количество запущенных инстансов LDPlayer
        running_count = 0
        if self._ldplayer:
            try:
                instances = await self._ldplayer.list_instances()
                running_count = sum(
                    1 for inst in instances if inst.status.value == "running"
                )
            except Exception as exc:
                logger.debug(f"LDPlayer недоступен при сборе телеметрии: {exc!r}")

        return WorkstationTelemetry(
            workstation_id=config.workstation_id,
            timestamp=time.time(),
            cpu_percent=cpu_pct,
            cpu_count=psutil.cpu_count(logical=True) or 1,
            ram_total_mb=mem.total // (1024 ** 2),
            ram_used_mb=mem.used // (1024 ** 2),
            ram_percent=mem.percent,
            disk=disks,
            network=net,
            ldplayer_instances_running=running_count,
        )
