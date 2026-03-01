# SPLIT-5 — Events WebSocket (Real-Time Fleet Events)

**ТЗ-родитель:** TZ-03-WebSocket-Layer  
**Ветка:** `stage/3-websocket`  
**Задача:** `SPHERE-020`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** —
**Интеграция при merge:** TZ-10 Frontend Dashboard работает с mock WS events; при merge подключить реальные события

---

## Цель Сплита

WebSocket endpoint для браузерного клиента (веб-дашборд) — получение событий fleet в реальном времени.

---

## Шаг 1 — Event Types Schema

```python
# backend/schemas/events.py
from datetime import datetime, timezone  # MED-6: timezone необходим для datetime.now(timezone.utc)
from enum import Enum
from pydantic import BaseModel, Field

class EventType(str, Enum):
    DEVICE_ONLINE = "device.online"
    DEVICE_OFFLINE = "device.offline"
    DEVICE_STATUS_CHANGE = "device.status_change"
    COMMAND_STARTED = "command.started"
    COMMAND_COMPLETED = "command.completed"
    COMMAND_FAILED = "command.failed"
    TASK_PROGRESS = "task.progress"
    VPN_ASSIGNED = "vpn.assigned"
    VPN_FAILED = "vpn.failed"
    ALERT_TRIGGERED = "alert.triggered"
    STREAM_STARTED = "stream.started"
    STREAM_STOPPED = "stream.stopped"

class FleetEvent(BaseModel):
    event_type: EventType
    device_id: str | None = None
    org_id: str
    payload: dict = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))  # MED-6+LOW-2: datetime.utcnow() deprecated since Python 3.12
```

---

## Шаг 2 — Fleet Events WebSocket (для браузера)

```python
# backend/api/ws/events/router.py  — HIGH-4: выделен в подпакет (events/router.py, не events.py)
# Это освобождает пространство имён для events/__init__.py и events/schemas.py
router = APIRouter()

class FrontendConnection:
    def __init__(self, ws: WebSocket, org_id: str, filters: set[str]):
        self.ws = ws
        self.org_id = org_id
        self.filters = filters  # EventType фильтры, {} = все события

class EventsManager:
    """Менеджер WebSocket подключений браузерных клиентов."""
    
    def __init__(self):
        self._clients: dict[str, list[FrontendConnection]] = {}  # org_id → list
    
    async def add_client(self, org_id: str, conn: FrontendConnection):
        if org_id not in self._clients:
            self._clients[org_id] = []
        self._clients[org_id].append(conn)
    
    async def remove_client(self, org_id: str, conn: FrontendConnection):
        clients = self._clients.get(org_id, [])
        if conn in clients:
            clients.remove(conn)
    
    async def publish_event(self, event: FleetEvent):
        """Разослать событие всем браузерным клиентам организации."""
        clients = self._clients.get(event.org_id, [])
        if not clients:
            return
        
        payload = event.model_dump(mode="json")
        dead = []
        
        for conn in clients:
            # Применить фильтры клиента
            if conn.filters and event.event_type not in conn.filters:
                continue
            try:
                await conn.ws.send_json(payload)
            except Exception:
                dead.append(conn)
        
        for conn in dead:
            await self.remove_client(event.org_id, conn)

@router.websocket("/ws/events")
async def fleet_events_ws(
    ws: WebSocket,
    db: AsyncSession = Depends(get_db),
    events_manager: EventsManager = Depends(get_events_manager),
):
    await ws.accept()
    
    # First-message auth
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        await ws.close(code=4003, reason="auth_timeout")
        return
    
    try:
        user = await authenticate_ws_token(first.get("token", ""), db)
    except HTTPException:
        await ws.close(code=4001, reason="invalid_token")
        return
    
    # Опциональные фильтры событий
    filters: set[str] = set(first.get("filter", []))
    
    conn = FrontendConnection(ws, str(user.org_id), filters)
    await events_manager.add_client(str(user.org_id), conn)
    
    # Отправить текущий снапшот fleet при подключении
    fleet_snap = await get_fleet_snapshot(user.org_id)
    await ws.send_json({"type": "snapshot", "data": fleet_snap})
    
    try:
        while True:
            data = await ws.receive_json()
            # Клиент может обновить фильтры в runtime
            if data.get("type") == "set_filter":
                conn.filters = set(data.get("events", []))
            elif data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await events_manager.remove_client(str(user.org_id), conn)
```

---

## Шаг 3 — Event Publisher (используется по всему бэкенду)

```python
# backend/websocket/event_publisher.py
class EventPublisher:
    """
    Фасад для публикации событий fleet.
    Публикует одновременно в Redis PubSub (для других воркеров) и локально.
    """
    
    def __init__(self, pubsub: PubSubPublisher, events_manager: EventsManager):
        self.pubsub = pubsub
        self.events_manager = events_manager
    
    async def emit(self, event: FleetEvent):
        # Опубликовать в Redis → другие воркеры получат и доставят своим клиентам
        await self.pubsub.broadcast_org_event(event.org_id, event.model_dump(mode="json"))
        # Доставить локальным клиентам напрямую
        await self.events_manager.publish_event(event)
    
    async def device_online(self, device_id: str, org_id: str):
        await self.emit(FleetEvent(
            event_type=EventType.DEVICE_ONLINE,
            device_id=device_id,
            org_id=org_id,
            payload={"status": "online"}
        ))
    
    async def command_completed(self, device_id: str, org_id: str, command_id: str, result: dict):
        await self.emit(FleetEvent(
            event_type=EventType.COMMAND_COMPLETED,
            device_id=device_id,
            org_id=org_id,
            payload={"command_id": command_id, "result": result}
        ))
```

---

## Критерии готовности

- [ ] Подключение браузера → получает снапшот fleet сразу
- [ ] Агент появляется онлайн → все браузеры org получают `device.online` < 1s
- [ ] Клиент с фильтром `["device.online"]` не получает `command.completed`
- [ ] Мёртвые WebSocket соединения очищаются автоматически
- [ ] Events Manager работает на уровне org изоляции (no cross-org leaks)
