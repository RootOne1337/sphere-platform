"""
AdbBridgeManager — управление ADB-форвардингом для инстансов LDPlayer.
Детальная реализация — TZ-08 SPLIT-4.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from .config import config

if TYPE_CHECKING:
    from .ldplayer import LDPlayerManager


class AdbBridgeManager:
    def __init__(self, ldplayer_mgr: "LDPlayerManager") -> None:
        self._ldplayer = ldplayer_mgr
        # serial -> forwarded_port
        self._forwarded: dict[str, int] = {}

    async def forward(
        self,
        device_serial: str,
        local_port: int,
        remote_port: int,
    ) -> bool:
        """
        Устанавливает adb forward tcp:<local_port> tcp:<remote_port>
        для указанного устройства.
        """
        logger.info(
            f"ADB forward: {device_serial} "
            f"tcp:{local_port} -> tcp:{remote_port} (stub)"
        )
        # TODO: TZ-08 SPLIT-4
        self._forwarded[device_serial] = local_port
        return True

    async def remove_forward(self, device_serial: str) -> None:
        """Снимает форвардинг для устройства."""
        logger.info(f"ADB remove-forward: {device_serial} (stub)")
        self._forwarded.pop(device_serial, None)

    async def _run_adb(self, *args: str) -> tuple[int, str, str]:
        cmd = [config.adb_path, *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
