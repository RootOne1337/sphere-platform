"""
LDPlayerManager — управление экземплярами LDPlayer через ldconsole.exe.
Детальная реализация — TZ-08 SPLIT-2.
"""
from __future__ import annotations

import asyncio
from loguru import logger

from .config import config


class LDPlayerManager:
    """Stub — полная реализация в TZ-08 SPLIT-2."""

    async def list_instances(self) -> list[dict]:
        """Возвращает список запущенных инстансов LDPlayer."""
        logger.debug("LDPlayerManager.list_instances (stub)")
        return []

    async def start_instance(self, instance_id: int) -> bool:
        """Запускает инстанс LDPlayer по порядковому номеру."""
        logger.info(f"LDPlayerManager.start_instance({instance_id}) stub")
        return True

    async def stop_instance(self, instance_id: int) -> bool:
        """Останавливает инстанс LDPlayer."""
        logger.info(f"LDPlayerManager.stop_instance({instance_id}) stub")
        return True

    async def _run_ldconsole(self, *args: str) -> tuple[int, str, str]:
        """
        Хелпер: запускает ldconsole.exe с заданными аргументами,
        возвращает (returncode, stdout, stderr).
        """
        cmd = [config.ldconsole, *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
