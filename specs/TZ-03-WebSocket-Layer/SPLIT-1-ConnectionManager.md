# SPLIT-1 — ConnectionManager (WebSocket Registry)

**ТЗ-родитель:** TZ-03-WebSocket-Layer  
**Ветка:** `stage/3-websocket`  
**Задача:** `SPHERE-016`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-03 SPLIT-2, SPLIT-3, SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-05 и TZ-07 работают с собственным WS-клиентом; при merge подключить ConnectionManager

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-3` — НЕ в `sphere-platform`.
> Ветка `stage/3-websocket` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**
```
C:\Users\dimas\Documents\sphere-stage-3
```
*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**
```bash
git branch --show-current   # ОБЯЗАН показать: stage/3-websocket
pwd                          # ОБЯЗАНА содержать: sphere-stage-3
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:
```bash
git worktree add ../sphere-stage-3 stage/3-websocket
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/3-websocket` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/3-websocket` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**
| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `backend/api/ws/` | `backend/main.py` 🔴 |
| `backend/websocket/` | `backend/core/` 🔴 |
| `backend/schemas/events*`, `backend/schemas/device_status*` | `backend/models/` (только TZ-00 создаёт!) 🔴 |
| `tests/test_ws*`, `tests/test_heartbeat*` | `backend/database/` 🔴 |
| | `backend/api/v1/` (TZ-01/02!) 🔴 |
| | `docker-compose*.yml` 🔴 |

---

## Цель Сплита

Потокобезопасный реестр WebSocket соединений. Маршрутизация команд к конкретному агенту по device_id.

---

## Предусловия

- TZ-00 SPLIT-3: Redis клиент настроен
- TZ-01 SPLIT-1: JWT `get_current_user` dependency
- FastAPI 0.109+ с встроенным WebSocket

---

## Шаг 1 — ConnectionManager (in-memory, single process)

```python
# backend/websocket/connection_manager.py
import asyncio
import structlog
from fastapi import WebSocket

logger = structlog.get_logger()

class ConnectionInfo:
    __slots__ = ("ws", "device_id", "agent_type", "org_id", "connected_at", "session_id")
    
    def __init__(self, ws, device_id, agent_type, org_id, session_id):
        self.ws = ws
        self.device_id = device_id
        self.agent_type = agent_type   # "android" | "pc"
        self.org_id = org_id
        self.connected_at = datetime.now(timezone.utc)
        self.session_id = session_id

class ConnectionManager:
    """
    Потокобезопасный реестр in-process.
    Для горизонтального масштабирования — используй Redis PubSub (SPLIT-2).
    """
    
    def __init__(self):
        self._lock = asyncio.Lock()
        # device_id → ConnectionInfo
        self._connections: dict[str, ConnectionInfo] = {}
        # org_id → set[device_id] (для broadcast по org)
        self._org_index: dict[str, set[str]] = {}
    
    async def connect(
        self,
        ws: WebSocket,
        device_id: str,
        agent_type: str,
        org_id: str,
    ) -> str:
        session_id = secrets.token_hex(16)
        async with self._lock:
            # Если устройство уже подключено — принудительно закрыть старое соединение
            if device_id in self._connections:
                old = self._connections[device_id]
                logger.info("Evicting old connection", device_id=device_id, old_session=old.session_id)
                try:
                    await old.ws.close(code=4001, reason="replaced_by_new_connection")
                except Exception:
                    pass
            
            info = ConnectionInfo(ws, device_id, agent_type, org_id, session_id)
            self._connections[device_id] = info
            
            if org_id not in self._org_index:
                self._org_index[org_id] = set()
            self._org_index[org_id].add(device_id)
        
        logger.info("Agent connected", device_id=device_id, agent_type=agent_type, session=session_id)
        return session_id
    
    async def disconnect(self, device_id: str) -> ConnectionInfo | None:
        async with self._lock:
            info = self._connections.pop(device_id, None)
            if info:
                self._org_index.get(info.org_id, set()).discard(device_id)
        if info:
            logger.info("Agent disconnected", device_id=device_id, session=info.session_id)
        return info
    
    async def send_to_device(self, device_id: str, message: dict) -> bool:
        """Отправить JSON сообщение конкретному агенту. Returns True если отправлено."""
        info = self._connections.get(device_id)
        if not info:
            return False
        try:
            await info.ws.send_json(message)
            return True
        except Exception as e:
            logger.warning("Send failed", device_id=device_id, error=str(e))
            await self.disconnect(device_id)
            return False
    
    async def send_bytes_to_device(self, device_id: str, data: bytes) -> bool:
        """Отправить бинарные данные (видеофрейм и т.п.)"""
        info = self._connections.get(device_id)
        if not info:
            return False
        try:
            await info.ws.send_bytes(data)
            return True
        except Exception as e:
            await self.disconnect(device_id)
            return False
    
    async def broadcast_to_org(self, org_id: str, message: dict) -> int:
        """Broadcast JSON сообщение всем агентам организации. Returns кол-во отправленных."""
        device_ids = list(self._org_index.get(org_id, set()))
        if not device_ids:
            return 0
        
        tasks = [self.send_to_device(did, message) for did in device_ids]
        results = await asyncio.gather(*tasks)
        return sum(1 for r in results if r)
    
    def get_connected_devices(self, org_id: str) -> list[str]:
        return list(self._org_index.get(org_id, set()))
    
    def is_connected(self, device_id: str) -> bool:
        return device_id in self._connections
    
    @property
    def total_connections(self) -> int:
        return len(self._connections)

# Синглтон — один на процесс
_manager: ConnectionManager | None = None

def get_connection_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager
```

---

## Шаг 2 — Android Agent WebSocket Endpoint

```python
# backend/api/ws/android/router.py   ← ОБЯЗАТЕЛЬНО ПАПКА, не файл!
# Без этого main.py авто-дискавери не найдёт роутер:
#   backend/api/ws/android/router.py  ← OK
#   backend/api/ws/android.py         ← router.py нет → роутер не подключится!
# PC Agent аналогично: backend/api/ws/agent/router.py (TZ-08)
router = APIRouter()

@router.websocket("/ws/android/{device_id}")
async def android_agent_ws(
    ws: WebSocket,
    device_id: str,
    db: AsyncSession = Depends(get_db),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    await ws.accept()
    
    # Шаг 1: First-message auth (НЕ JWT в URL!)
    try:
        first_msg = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        await ws.close(code=4003, reason="auth_timeout")
        return
    
    token = first_msg.get("token")
    if not token:
        await ws.close(code=4001, reason="no_token")
        return
    
    # Валидация JWT
    try:
        user = await authenticate_ws_token(token, db)
    except HTTPException:
        await ws.close(code=4001, reason="invalid_token")
        return
    
    # Проверить что device принадлежит организации
    device = await db.get(Device, device_id)
    if not device or device.org_id != user.org_id:
        await ws.close(code=4004, reason="device_not_found")
        return
    
    session_id = await manager.connect(ws, device_id, "android", str(user.org_id))
    await status_cache.set_status(device_id, DeviceLiveStatus(
        device_id=device_id, status="online", ws_session_id=session_id
    ))
    
    try:
        while True:
            data = await ws.receive()
            if "text" in data:
                msg = json.loads(data["text"])
                await handle_agent_message(device_id, msg, manager, status_cache)
            elif "bytes" in data:
                await handle_agent_binary(device_id, data["bytes"], manager)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(device_id)
        await status_cache.mark_offline(device_id)
```

---

## Шаг 3 — PC Agent WebSocket Endpoint (agent_token auth)

> **PC Agent (TZ-08) использует `agent_token`, а не JWT пользователя.**
> `agent_token` — долгоживущий API-ключ, хранится в `.env` на хост-машине.
> Для PC Agent нужен отдельный endpoint `/ws/agent/{workstation_id}` с отдельной проверкой.

```python
# backend/api/ws/agent/router.py   ← папка, не файл (аналогично android/router.py)
# (TZ-08 создаёт этот файл)
import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database.engine import get_db
from backend.websocket.connection_manager import ConnectionManager, get_connection_manager
from backend.models.device import Device
from backend.models.user import APIKey

router = APIRouter()


async def authenticate_agent_token(token: str, db: AsyncSession) -> APIKey:
    """
    Проверяет agent_token из first-message.
    agent_token = sha256(raw_key) хранится в таблице api_keys с type='agent'.
    Отличие от JWT: не истекает через 15 мин, не нужен refresh-цикл.
    """
    import hashlib
    from sqlalchemy import select
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True,
            APIKey.type == "agent",   # отличаем от пользовательских API-ключей
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise ValueError("Invalid or inactive agent token")
    return api_key


@router.websocket("/ws/agent/{workstation_id}")
async def pc_agent_ws(
    ws: WebSocket,
    workstation_id: str,
    db: AsyncSession = Depends(get_db),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    await ws.accept()

    try:
        first_msg = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        await ws.close(code=4003, reason="auth_timeout")
        return

    token = first_msg.get("token")
    if not token:
        await ws.close(code=4001, reason="no_token")
        return

    try:
        api_key = await authenticate_agent_token(token, db)
    except ValueError:
        await ws.close(code=4001, reason="invalid_agent_token")
        return

    session_id = await manager.connect(ws, workstation_id, "pc", str(api_key.org_id))

    try:
        while True:
            data = await ws.receive()
            if "text" in data:
                msg = json.loads(data["text"])
                await handle_agent_message(workstation_id, msg, manager)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(workstation_id)
```

---

## Критерии готовности

- [ ] 1000 одновременных WS соединений без утечек памяти (профилировать через tracemalloc)
- [ ] Повторное подключение с тем же device_id → старое соединение закрывается (код 4001)
- [ ] First-message auth timeout 10s → закрытие (код 4003)
- [ ] JWT в URL path запрещён (нет `?token=`)
- [ ] Disconnect → `mark_offline()` вызывается всегда (finally блок)
- [ ] `get_connection_manager()` возвращает один синглтон (проверить через id())
- [ ] `/ws/android/{device_id}` — auth через JWT, `/ws/agent/{workstation_id}` — auth через agent_token
- [ ] android/router.py и agent/router.py оба являются папками, не файлами (auto-discovery подхватит)
