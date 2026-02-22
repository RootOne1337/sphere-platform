# SPLIT-4 — ADB Bridge (Port Forwarding per Instance)

**ТЗ-родитель:** TZ-08-PC-Agent  
**Ветка:** `stage/8-pc-agent`  
**Задача:** `SPHERE-044`  
**Исполнитель:** Backend/Python  
**Оценка:** 1 день  
**Блокирует:** TZ-08 SPLIT-5

---

## Цель Сплита

Поддерживать локальный ADB-сервер, автоматически подключать все запущенные инстансы LDPlayer по их портам, пробрасывать ADB-команды от сервера к нужному устройству.

---

## Шаг 1 — AdbBridgeManager

```python
# agent/adb_bridge.py
import asyncio
import shlex
from typing import Optional
from loguru import logger
from .config import config
from .ldplayer import LDPlayerManager

class AdbBridgeManager:
    """
    Управляет ADB-соединениями с экземплярами LDPlayer.
    LDPlayer использует порты: 5554, 5556, 5558, ...
    (BASE_PORT + index * 2)
    """
    BASE_PORT = 5554
    
    def __init__(self, ldplayer: LDPlayerManager):
        self.ldplayer = ldplayer
        self._connected_ports: set[int] = set()
    
    async def sync_connections(self) -> None:
        """Синхронизировать ADB-соединения с запущенными инстансами."""
        instances = await self.ldplayer.list_instances()
        running_ports = {
            self.BASE_PORT + inst.index * 2
            for inst in instances
            if inst.status.value == "running"
        }
        
        # Подключить новые
        for port in running_ports - self._connected_ports:
            success = await self.connect(port)
            if success:
                self._connected_ports.add(port)
        
        # FIX 8.3: БЫЛО — просто отключали порты, которых нет в running_ports
        # → Эмулятор перезагружен = порт тот же, но ADB-сессия мёртвая (offline)
        # СТАЛО — проверяем реальный статус каждого подключённого устройства
        stale_ports = set()
        for port in self._connected_ports:
            devices = await self.list_devices()
            serial = f"127.0.0.1:{port}"
            dev = next((d for d in devices if d["serial"] == serial), None)
            if dev and dev["state"] != "device":
                logger.warning(f"ADB порт {port} в статусе '{dev['state']}', переподключение")
                await self.disconnect(port)
                await self.connect(port)
            elif serial not in {d["serial"] for d in devices}:
                stale_ports.add(port)
        
        # Отключить остановленные (порт не в running_ports И не в adb devices)
        for port in (self._connected_ports - running_ports) | stale_ports:
            await self.disconnect(port)
            self._connected_ports.discard(port)
    
    async def connect(self, port: int) -> bool:
        """adb connect 127.0.0.1:<port>"""
        output = await self._adb("connect", f"127.0.0.1:{port}")
        if "connected" in output.lower() or "already connected" in output.lower():
            logger.info(f"ADB connected: 127.0.0.1:{port}")
            return True
        logger.warning(f"ADB connect failed port={port}: {output}")
        return False
    
    async def disconnect(self, port: int) -> None:
        await self._adb("disconnect", f"127.0.0.1:{port}")
        logger.info(f"ADB disconnected: 127.0.0.1:{port}")
    
    async def shell(self, port: int, command: str) -> str:
        """Выполнить shell-команду на устройстве через ADB."""
        serial = f"127.0.0.1:{port}"
        # Санитизация — allowlist подход для предотвращения shell injection
        # Запрещаем: ; | & $ ` ( ) { } < > \ ! # ~ и переводы строк
        import re
        SHELL_INJECTION_PATTERN = re.compile(r'[;|&$`(){}\\<>!\n\r#~]')
        if SHELL_INJECTION_PATTERN.search(command):
            raise ValueError(
                f"Shell injection detected: forbidden characters in command. "
                f"Allowed: alphanumeric, spaces, dots, dashes, slashes, equals, quotes."
            )
        if not all(c.isprintable() for c in command):
            raise ValueError("Non-printable characters in ADB command")
        return await self._adb("-s", serial, "shell", command)
    
    async def install(self, port: int, apk_path: str) -> str:
        serial = f"127.0.0.1:{port}"
        return await self._adb("-s", serial, "install", "-r", apk_path, timeout=120.0)
    
    async def push(self, port: int, local: str, remote: str) -> str:
        serial = f"127.0.0.1:{port}"
        return await self._adb("-s", serial, "push", local, remote, timeout=60.0)
    
    async def pull(self, port: int, remote: str, local: str) -> str:
        serial = f"127.0.0.1:{port}"
        return await self._adb("-s", serial, "pull", remote, local, timeout=60.0)
    
    async def list_devices(self) -> list[dict]:
        output = await self._adb("devices")
        devices = []
        for line in output.splitlines()[1:]:  # Skip "List of devices attached"
            if "\t" in line:
                serial, state = line.split("\t", 1)
                devices.append({"serial": serial.strip(), "state": state.strip()})
        return devices
    
    async def _adb(self, *args: str, timeout: float = 30.0) -> str:
        cmd = [config.adb_path] + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"ADB timeout: {' '.join(args[:3])}")
        
        output = stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ADB error {' '.join(args[:2])}: {err or output}")
        return output
```

---

## Шаг 2 — Периодическая синхронизация в main

```python
# agent/main.py (добавить task)
async def adb_sync_loop(adb_bridge: AdbBridgeManager):
    """Каждые 15 секунд синхронизировать ADB-соединения."""
    while True:
        try:
            await asyncio.sleep(15)
            await adb_bridge.sync_connections()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"ADB sync error: {e}")

# В main():
tasks.append(asyncio.create_task(adb_sync_loop(adb_bridge), name="adb_sync"))
```

---

## Шаг 3 — CommandDispatcher (ADB commands)

```python
# В dispatcher._handle() добавить:
case "adb_devices":
    devices = await self.adb_bridge.list_devices()
    return {"devices": devices}

case "adb_shell":
    port = payload["port"]
    command = payload["command"]
    output = await self.adb_bridge.shell(port, command)
    return {"output": output}

case "adb_install":
    port = payload["port"]
    apk_path = payload["apk_path"]
    result = await self.adb_bridge.install(port, apk_path)
    return {"result": result}

case "adb_sync":
    await self.adb_bridge.sync_connections()
    return {"connected": list(self.adb_bridge._connected_ports)}
```

---

## Критерии готовности

- [ ] `sync_connections()` только подключает новые / отключает остановленные (идемпотентно)
- [ ] ADB shell sanitization: `;|&$\`(){}\\<>!#~` и non-printable → ValueError (allowlist, не blocklist)
- [ ] `_adb()` использует asyncio.create_subprocess_exec (не blocking)
- [ ] Таймаут `install` 120 секунд, `shell` 30 секунд
- [ ] `adb_sync_loop` не падает при ошибке LDPlayer (except Exception)
- [ ] `list_devices()` корректно парсит `adb devices` output
