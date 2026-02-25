"""
LDPlayerManager — асинхронный враппер над ldconsole.exe.
SPHERE-042  TZ-08 SPLIT-2
"""
from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from .config import config
from .models import InstanceStatus, LDPlayerInstance


class LDPlayerManager:
    BASE_ADB_PORT = 5554  # LDPlayer: 5554, 5556, 5558...

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run(self, *args: str, timeout: float = 30.0) -> str:
        """Запустить ldconsole.exe с аргументами, вернуть stdout."""
        cmd = [config.ldconsole, *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"ldconsole timeout: {' '.join(str(a) for a in args)}")

        output = stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"ldconsole error (rc={proc.returncode}): {err or output}"
            )
        return output

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_instances(self) -> list[LDPlayerInstance]:
        """Получить список всех экземпляров через ldconsole list2."""
        output = await self._run("list2")
        instances: list[LDPlayerInstance] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            try:
                idx = int(parts[0])
                name = parts[1].strip()
                pid_str = parts[2].strip()
                status_str = parts[4].strip() if len(parts) > 4 else "0"

                status = (
                    InstanceStatus.RUNNING
                    if status_str == "1"
                    else InstanceStatus.STOPPED
                )
                pid = int(pid_str) if pid_str.isdigit() and int(pid_str) > 0 else None

                instances.append(
                    LDPlayerInstance(
                        index=idx,
                        name=name,
                        status=status,
                        pid=pid,
                        adb_port=self.BASE_ADB_PORT + idx * 2,
                    )
                )
            except (ValueError, IndexError) as exc:
                logger.debug(f"Cannot parse ldconsole line: {line!r} — {exc}")
        return instances

    async def get_instance(self, index: int) -> Optional[LDPlayerInstance]:
        """Вернуть инстанс по индексу или None."""
        instances = await self.list_instances()
        return next((i for i in instances if i.index == index), None)

    async def launch(self, index: int) -> None:
        """Запустить инстанс и ждать его готовности (до 60 секунд)."""
        logger.info(f"Запускаем LDPlayer instance #{index}")
        await self._run("launch", "--index", str(index))

        for _ in range(30):  # 30 × 2s = 60 секунд
            await asyncio.sleep(2)
            inst = await self.get_instance(index)
            if inst and inst.status == InstanceStatus.RUNNING:
                logger.info(f"Instance #{index} запущен (pid={inst.pid})")
                return
        raise TimeoutError(f"Instance #{index} не запустился за 60 секунд")

    async def quit(self, index: int) -> None:
        """Остановить инстанс."""
        logger.info(f"Останавливаем LDPlayer instance #{index}")
        await self._run("quit", "--index", str(index), timeout=15.0)

    async def reboot(self, index: int) -> None:
        """Перезапустить инстанс."""
        logger.info(f"Перезапускаем LDPlayer instance #{index}")
        await self.quit(index)
        await asyncio.sleep(2)
        await self.launch(index)

    async def create(self, name: str) -> int:
        """Создать новый экземпляр, вернуть его index."""
        await self._run("add", "--name", name)
        instances = await self.list_instances()
        created = next((i for i in instances if i.name == name), None)
        if not created:
            raise RuntimeError(f"Не удалось создать инстанс name={name!r}")
        return created.index

    async def install_apk(self, index: int, apk_path: str) -> None:
        """Установить APK в инстанс (таймаут 120с для больших APK)."""
        await self._run(
            "installapp", "--index", str(index), "--filename", apk_path,
            timeout=120.0,
        )

    async def run_app(self, index: int, package_name: str) -> None:
        """Запустить приложение по package name."""
        await self._run("runapp", "--index", str(index), "--packagename", package_name)

    async def exec_command(self, index: int, command: str) -> str:
        """Выполнить ADB-команду через ldconsole (без прямого ADB)."""
        return await self._run(
            "adb", "--index", str(index), "--command", command
        )
