"""
AdbBridgeManager — управление ADB-соединениями с экземплярами LDPlayer.
SPHERE-044  TZ-08 SPLIT-4

LDPlayer порты ADB: 5554, 5556, 5558, ... (BASE_PORT + index * 2)
FIX 8.3: sync_connections() проверяет реальный статус уже подключённых портов,
а не просто сравнивает с running_ports — иначе зависшие offline-сессии остаются.
"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from loguru import logger

from .config import config

if TYPE_CHECKING:
    from .ldplayer import LDPlayerManager

# Запрещённые в shell-командах символы — allowlist подход
_SHELL_INJECTION_RE = re.compile(r'[;|&$`(){}\\<>!\n\r#~]')


class AdbBridgeManager:
    BASE_PORT = 5554

    def __init__(self, ldplayer_mgr: "LDPlayerManager") -> None:
        self._ldplayer = ldplayer_mgr
        self._connected_ports: set[int] = set()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def sync_connections(self) -> None:
        """
        Синхронизировать ADB-соединения с запущенными инстансами.
        Идемпотентно: подключает новые, переподключает зависшие, отключает остановленные.
        """
        instances = await self._ldplayer.list_instances()
        running_ports = {
            self.BASE_PORT + inst.index * 2
            for inst in instances
            if inst.status.value == "running"
        }

        # Снапшот до изменений: FIX 8.3 проверяем только ранее установленные соединения,
        # а не только что подключённые (иначе новые порты считались бы stale).
        previously_connected = set(self._connected_ports)

        # Подключить новые порты
        for port in running_ports - previously_connected:
            success = await self.connect(port)
            if success:
                self._connected_ports.add(port)

        # FIX 8.3: проверяем реальный статус уже подключённых (ранее) портов
        # (эмулятор мог перезагрузиться — порт тот же, но сессия offline)
        devices = await self.list_devices()
        device_map = {d["serial"]: d["state"] for d in devices}

        stale_ports: set[int] = set()
        for port in list(previously_connected):
            serial = f"127.0.0.1:{port}"
            state = device_map.get(serial)
            if state is None:
                stale_ports.add(port)  # вовсе нет в adb devices
            elif state != "device":
                logger.warning(
                    f"ADB порт {port} в состоянии '{state}', переподключение"
                )
                await self.disconnect(port)
                await self.connect(port)

        # Отключить: порт не в running ИЛИ исчез из adb devices
        for port in (self._connected_ports - running_ports) | stale_ports:
            await self.disconnect(port)
            self._connected_ports.discard(port)

    async def connect(self, port: int) -> bool:
        """adb connect 127.0.0.1:<port>"""
        try:
            output = await self._adb("connect", f"127.0.0.1:{port}")
            if "connected" in output.lower() or "already connected" in output.lower():
                logger.info(f"ADB подключён: 127.0.0.1:{port}")
                return True
            logger.warning(f"ADB connect неудача port={port}: {output!r}")
            return False
        except Exception as exc:
            logger.warning(f"ADB connect ошибка port={port}: {exc!r}")
            return False

    async def disconnect(self, port: int) -> None:
        """adb disconnect 127.0.0.1:<port>"""
        try:
            await self._adb("disconnect", f"127.0.0.1:{port}")
            logger.info(f"ADB отключён: 127.0.0.1:{port}")
        except Exception as exc:
            logger.debug(f"ADB disconnect port={port}: {exc!r}")

    # ------------------------------------------------------------------
    # Device commands
    # ------------------------------------------------------------------

    async def shell(self, port: int, command: str) -> str:
        """
        Выполнить shell-команду на устройстве через ADB.
        Защита от shell injection — allowlist подход (не blocklist).
        """
        if _SHELL_INJECTION_RE.search(command):
            raise ValueError(
                f"Shell injection detected — запрещённые символы в команде. "
                f"Допустимы: буквы/цифры, пробелы, . - / = и одинарные кавычки."
            )
        if not all(c.isprintable() for c in command):
            raise ValueError("Непечатаемые символы в ADB-команде")

        serial = f"127.0.0.1:{port}"
        return await self._adb("-s", serial, "shell", command)

    async def install(self, port: int, apk_path: str) -> str:
        """adb install -r <apk_path>  (таймаут 120s для больших APK)."""
        serial = f"127.0.0.1:{port}"
        return await self._adb("-s", serial, "install", "-r", apk_path, timeout=120.0)

    async def push(self, port: int, local: str, remote: str) -> str:
        """adb push <local> <remote>"""
        serial = f"127.0.0.1:{port}"
        return await self._adb("-s", serial, "push", local, remote, timeout=60.0)

    async def pull(self, port: int, remote: str, local: str) -> str:
        """adb pull <remote> <local>"""
        serial = f"127.0.0.1:{port}"
        return await self._adb("-s", serial, "pull", remote, local, timeout=60.0)

    async def list_devices(self) -> list[dict]:
        """Парсит вывод `adb devices`, возвращает [{serial, state}]."""
        try:
            output = await self._adb("devices")
        except Exception as exc:
            logger.warning(f"adb devices ошибка: {exc!r}")
            return []

        devices: list[dict] = []
        for line in output.splitlines()[1:]:  # пропускаем "List of devices attached"
            if "\t" in line:
                serial, state = line.split("\t", 1)
                devices.append({"serial": serial.strip(), "state": state.strip()})
        return devices

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _adb(self, *args: str, timeout: float = 30.0) -> str:
        """Запустить adb.exe, вернуть stdout или бросить RuntimeError."""
        cmd = [config.adb_path, *args]
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
            raise TimeoutError(f"ADB timeout: {' '.join(str(a) for a in args[:3])}")

        output = stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"ADB ошибка {' '.join(str(a) for a in args[:2])}: {err or output}"
            )
        return output
