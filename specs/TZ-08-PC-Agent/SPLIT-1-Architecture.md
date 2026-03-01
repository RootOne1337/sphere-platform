# SPLIT-1 — PC Agent Architecture (asyncio WS daemon)

**ТЗ-родитель:** TZ-08-PC-Agent  
**Ветка:** `stage/8-pc-agent`  
**Задача:** `SPHERE-041`  
**Исполнитель:** Backend/Python  
**Оценка:** 1 день  
**Блокирует:** TZ-08 SPLIT-2, SPLIT-3, SPLIT-4

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-8` — НЕ в `sphere-platform`.
> Ветка `stage/8-pc-agent` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-8
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/8-pc-agent
pwd                          # ОБЯЗАНА содержать: sphere-stage-8
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-8 stage/8-pc-agent
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/8-pc-agent` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/8-pc-agent` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `pc-agent/core/` | `backend/main.py` 🔴 |
| `pc-agent/ldplayer/` | `backend/core/` 🔴 |
| `pc-agent/adb/` (кроме `adb_discovery.py` — он в TZ-02) | `backend/api/` 🔴 |
| `pc-agent/telemetry/` | `backend/models/` 🔴 |
| `pc-agent/ws/` | `android/` 🔴 |
| `tests/test_pc_agent*` | `docker-compose*.yml` 🔴 |

---

## Цель Сплита

Python-демон на хост-машинах (воркстанции с LDPlayer). Подключается к бэкенду по WebSocket, регистрирует себя, принимает команды, управляет экземплярами LDPlayer.

---

## Шаг 1 — Структура проекта

```
pc-agent/
├── agent/
│   ├── __init__.py
│   ├── main.py           # точка входа
│   ├── config.py         # Pydantic Settings
│   ├── client.py         # WS-клиент с reconnect
│   ├── dispatcher.py     # маршрутизатор команд
│   ├── ldplayer.py       # управление LDPlayer (SPLIT-2)
│   ├── telemetry.py      # psutil метрики (SPLIT-3)
│   ├── adb_bridge.py     # ADB forward (SPLIT-4)
│   └── topology.py       # реестр инстансов (SPLIT-5)
├── requirements.txt
├── Dockerfile            # для упаковки
└── install.bat           # Windows auto-start (NSSM)
```

```python
# requirements.txt
websockets==12.0
pydantic-settings==2.2
psutil==5.9.8
aiofiles==23.2
httpx==0.27
loguru==0.7
```

---

## Шаг 2 — Config

```python
# agent/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class AgentConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPHERE_")
    
    server_url: str             # wss://api.sphere.local
    agent_token: str            # токен агента (не пользовательский JWT)
    workstation_id: str         # уникальный ID хоста
    ldplayer_path: str = r"C:\LDPlayer\LDPlayer9"
    ldconsole: str = r"C:\LDPlayer\LDPlayer9\ldconsole.exe"
    adb_path: str = r"C:\LDPlayer\LDPlayer9\adb.exe"
    
    reconnect_initial_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    reconnect_backoff_factor: float = 2.0
    
    telemetry_interval: int = 30  # секунды
    
config = AgentConfig()
```

---

## Шаг 3 — WS Client с Reconnect

```python
# agent/client.py
import asyncio
import json
from typing import Callable, Optional
import websockets
from loguru import logger
from .config import config

class AgentWebSocketClient:
    def __init__(self, on_message: Callable):
        self.on_message = on_message
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._stop_event = asyncio.Event()
        # FIX 8.2: Исходящая очередь для предотвращения ConcurrentMessageError
        # websockets v12+ запрещает concurrent await ws.send()
        self._send_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
        # FIX ARCH-5: Сохраняем references на background tasks — защита от GC
        self._bg_tasks: set[asyncio.Task] = set()
        # FIX ARCH-6: Circuit breaker (аналогично Android Agent)
        self._consecutive_failures = 0
        self._CIRCUIT_THRESHOLD = 10
        self._circuit_open_until = 0.0
        self._CIRCUIT_COOLDOWN = 300.0  # 5 минут
    
    async def run(self):
        delay = config.reconnect_initial_delay
        
        while not self._stop_event.is_set():
            # FIX ARCH-6: Circuit breaker check
            now = asyncio.get_event_loop().time()
            if now < self._circuit_open_until:
                wait = self._circuit_open_until - now
                logger.warning(f"Circuit open, ждём {wait:.0f}с")
                await asyncio.sleep(wait)
                self._consecutive_failures = 0
            
            try:
                await self._connect_once()
                delay = config.reconnect_initial_delay
                self._consecutive_failures = 0  # сброс при успехе
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._CIRCUIT_THRESHOLD:
                    self._circuit_open_until = asyncio.get_event_loop().time() + self._CIRCUIT_COOLDOWN
                    logger.error(f"Circuit breaker OPEN после {self._consecutive_failures} ошибок")
                logger.warning(f"WS disconnected: {e}, reconnect через {delay:.1f}с")
                await asyncio.sleep(delay)
                delay = min(delay * config.reconnect_backoff_factor, config.reconnect_max_delay)
    
    async def _connect_once(self):
        ws_url = (
            config.server_url.replace("http", "ws", 1)
            + f"/ws/agent/{config.workstation_id}"
        )
        logger.info(f"Connecting to {ws_url}")
        
        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            self._connected = True
            
            # First-message auth
            await ws.send(json.dumps({"token": config.agent_token}))
            logger.info("Подключено и аутентифицировано")
            
            # FIX 8.2: Запустить _send_loop для сериализации исходящих сообщений
            send_task = asyncio.create_task(self._send_loop(ws))
            
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        # FIX ARCH-5: Сохраняем reference на task — защита от GC
                        t = asyncio.create_task(self.on_message(msg))
                        self._bg_tasks.add(t)
                        t.add_done_callback(self._bg_tasks.discard)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON: {raw[:200]}")
            finally:
                send_task.cancel()
                try:
                    await send_task
                except asyncio.CancelledError:
                    pass
    
    async def _send_loop(self, ws):
        """
        FIX 8.2: Сериализация исходящих WS-сообщений через очередь.
        websockets v12+ бросает ConcurrentMessageError при
        одновременном await ws.send() из разных корутин.
        """
        while True:
            data = await self._send_queue.get()
            try:
                await ws.send(json.dumps(data))
            except Exception as e:
                logger.warning(f"Send ошибка: {e}")
                break
    
    async def send(self, data: dict):
        """FIX 8.2: Отправка через очередь, не напрямую."""
        if self._connected:
            try:
                self._send_queue.put_nowait(data)
            except asyncio.QueueFull:
                logger.warning("Очередь отправки переполнена, сообщение отброшено")
    
    async def stop(self):
        self._stop_event.set()
        if self._ws:
            await self._ws.close()
```

---

## Шаг 4 — Main Entrypoint

```python
# agent/main.py
import asyncio
import sys
import signal
from loguru import logger
from .client import AgentWebSocketClient
from .dispatcher import CommandDispatcher
from .telemetry import TelemetryReporter
from .ldplayer import LDPlayerManager
from .adb_bridge import AdbBridgeManager

async def main():
    logger.info("Sphere Platform PC Agent starting...")
    
    ldplayer_mgr = LDPlayerManager()
    adb_bridge = AdbBridgeManager(ldplayer_mgr)
    
    dispatcher = CommandDispatcher(ldplayer_mgr, adb_bridge)
    ws_client = AgentWebSocketClient(on_message=dispatcher.dispatch)
    telemetry = TelemetryReporter(ws_client)
    
    stop_event = asyncio.Event()

    # asyncio.add_signal_handler работает ТОЛЬКО на Unix/macOS.
    # На Windows SIGTERM не поддерживается в asyncio — используем signal.signal().
    if sys.platform == "win32":
        # Windows: SIGBREAK (не SIGTERM) + SIGINT
        def _win_stop_handler(signum, frame):
            logger.info(f"Signal {signum} received, scheduling shutdown")
            asyncio.get_event_loop().call_soon_threadsafe(stop_event.set)

        signal.signal(signal.SIGINT,  _win_stop_handler)
        try:
            signal.signal(signal.SIGBREAK, _win_stop_handler)   # Ctrl+Break
        except AttributeError:
            pass  # SIGBREAK есть не на всех Windows-сборках
    else:
        # Unix: полноценная поддержка
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)
    
    tasks = [
        asyncio.create_task(ws_client.run(), name="ws_client"),
        asyncio.create_task(telemetry.run(), name="telemetry"),
    ]
    
    await stop_event.wait()
    logger.info("Shutdown signal received")
    
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await ws_client.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Критерии готовности

- [ ] Запускается через `python -m agent.main` на Windows
- [ ] First-message auth аналогично Android Agent
- [ ] Exponential backoff: 1 → 2 → 4 → ... → 30 секунд
- [ ] Graceful shutdown по Ctrl+C: все задачи отменяются
- [ ] `config.agent_token` из `.env` файла (не в коде)
- [ ] `install.bat` создаёт Windows Service через NSSM
