# SPLIT-2 — LDPlayer Manager (ldconsole.exe Wrapper)

**ТЗ-родитель:** TZ-08-PC-Agent  
**Ветка:** `stage/8-pc-agent`  
**Задача:** `SPHERE-042`  
**Исполнитель:** Backend/Python  
**Оценка:** 1.5 дня  
**Блокирует:** TZ-08 SPLIT-4, SPLIT-5

---

## Цель Сплита

Асинхронный враппер над `ldconsole.exe`: создание/запуск/остановка/перезапуск экземпляров, получение списка, проверка состояния.

---

## Шаг 1 — LDPlayerInstance модель

```python
# agent/models.py
from enum import Enum
from pydantic import BaseModel

class InstanceStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    STARTING = "starting"
    ERROR = "error"

class LDPlayerInstance(BaseModel):
    index: int
    name: str
    status: InstanceStatus
    pid: int | None = None
    adb_port: int | None = None   # базовый + index*2
```

---

## Шаг 2 — LDPlayerManager

```python
# agent/ldplayer.py
import asyncio
import subprocess
from typing import Optional
from loguru import logger
from .config import config
from .models import LDPlayerInstance, InstanceStatus

class LDPlayerManager:
    BASE_ADB_PORT = 5554  # LDPlayer: 5554, 5556, 5558...
    
    async def _run(self, *args: str, timeout: float = 30.0) -> str:
        """Запустить ldconsole.exe с аргументами."""
        cmd = [config.ldconsole] + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"ldconsole timeout: {' '.join(args)}")
        
        output = stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ldconsole error (rc={proc.returncode}): {err or output}")
        return output
    
    async def list_instances(self) -> list[LDPlayerInstance]:
        """Получить список всех экземпляров."""
        output = await self._run("list2")
        instances = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            try:
                idx = int(parts[0])
                name = parts[1].strip()
                status_str = parts[4].strip() if len(parts) > 4 else "unknown"
                pid_str = parts[2].strip()
                
                status = InstanceStatus.RUNNING if status_str == "1" else InstanceStatus.STOPPED
                pid = int(pid_str) if pid_str.isdigit() and int(pid_str) > 0 else None
                
                instances.append(LDPlayerInstance(
                    index=idx,
                    name=name,
                    status=status,
                    pid=pid,
                    adb_port=self.BASE_ADB_PORT + idx * 2,
                ))
            except (ValueError, IndexError) as e:
                logger.debug(f"Cannot parse instance line: {line!r} — {e}")
        return instances
    
    async def get_instance(self, index: int) -> Optional[LDPlayerInstance]:
        instances = await self.list_instances()
        return next((i for i in instances if i.index == index), None)
    
    async def launch(self, index: int) -> None:
        logger.info(f"Launching LDPlayer instance {index}")
        await self._run("launch", "--index", str(index))
        # Ждём готовности (adb device появится)
        for _ in range(30):  # до 60 секунд
            await asyncio.sleep(2)
            inst = await self.get_instance(index)
            if inst and inst.status == InstanceStatus.RUNNING:
                logger.info(f"Instance {index} is running (pid={inst.pid})")
                return
        raise TimeoutError(f"Instance {index} did not start within 60s")
    
    async def quit(self, index: int) -> None:
        logger.info(f"Stopping LDPlayer instance {index}")
        await self._run("quit", "--index", str(index), timeout=15.0)
    
    async def reboot(self, index: int) -> None:
        logger.info(f"Rebooting LDPlayer instance {index}")
        await self.quit(index)
        await asyncio.sleep(2)
        await self.launch(index)
    
    async def create(self, name: str) -> int:
        """Создать новый экземпляр, вернуть его index."""
        await self._run("add", "--name", name)
        instances = await self.list_instances()
        created = next((i for i in instances if i.name == name), None)
        if not created:
            raise RuntimeError(f"Failed to create instance with name={name}")
        return created.index
    
    async def install_apk(self, index: int, apk_path: str) -> None:
        await self._run("installapp", "--index", str(index), "--filename", apk_path, timeout=120.0)
    
    async def run_app(self, index: int, package_name: str) -> None:
        await self._run("runapp", "--index", str(index), "--packagename", package_name)
    
    async def exec_command(self, index: int, command: str) -> str:
        """Выполнить ADB-команду через ldconsole (без прямого ADB)."""
        return await self._run("adb", "--index", str(index), "--command", command)
```

---

## Шаг 3 — CommandDispatcher (LDPlayer actions)

```python
# agent/dispatcher.py (фрагмент)
class CommandDispatcher:
    def __init__(self, ldplayer: LDPlayerManager, adb_bridge: AdbBridgeManager):
        self.ldplayer = ldplayer
        self.adb_bridge = adb_bridge
    
    async def dispatch(self, msg: dict):
        cmd_type = msg.get("type")
        payload = msg.get("payload", {})
        command_id = msg.get("command_id", "")
        
        try:
            result = await self._handle(cmd_type, payload)
            await self.ws_client.send({
                "command_id": command_id,
                "status": "completed",
                "result": result,
            })
        except Exception as e:
            logger.error(f"Command {cmd_type} failed: {e}")
            await self.ws_client.send({
                "command_id": command_id,
                "status": "failed",
                "error": str(e),
            })
    
    async def _handle(self, cmd_type: str, payload: dict):
        match cmd_type:
            case "ld_list":
                instances = await self.ldplayer.list_instances()
                return [i.model_dump() for i in instances]
            case "ld_launch":
                await self.ldplayer.launch(payload["index"])
                return {"launched": True}
            case "ld_quit":
                await self.ldplayer.quit(payload["index"])
                return {"stopped": True}
            case "ld_reboot":
                await self.ldplayer.reboot(payload["index"])
                return {"rebooted": True}
            case "ld_install_apk":
                await self.ldplayer.install_apk(payload["index"], payload["apk_path"])
                return {"installed": True}
            case _:
                logger.warning(f"Unknown command: {cmd_type}")
                return None
```

---

## Критерии готовности

- [ ] `list_instances()` парсит `ldconsole list2` вывод корректно для 0-99 инстансов
- [ ] `launch()` ждёт до 60 секунд до running state
- [ ] `install_apk()` таймаут 120 секунд (большой APK)
- [ ] Все async вызовы: не блокируют event loop (asyncio.create_subprocess_exec)
- [ ] `create()` возвращает правильный index нового инстанса
- [ ] ldconsole error код != 0 → RuntimeError с понятным сообщением
