# SPLIT-2 — Redis Pub/Sub (Горизонтальное масштабирование WS)

**ТЗ-родитель:** TZ-03-WebSocket-Layer  
**Ветка:** `stage/3-websocket`  
**Задача:** `SPHERE-017`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-03 SPLIT-3, SPLIT-4
**Интеграция при merge:** TZ-06 VPN работает с прямым Redis Pub/Sub; при merge унифицировать каналы

---

## Цель Сплита

Маршрутизация WebSocket сообщений через Redis Pub/Sub между несколькими воркерами FastAPI.

---

## Шаг 1 — Channel Naming Convention

```python
# backend/websocket/channels.py
class ChannelPattern:
    """
    Стандартные паттерны Redis каналов.
    
    MERGE-4: REDIS KEYSPACE MAP — полная карта всех Redis ключей проекта.
    При merge ОБЯЗАТЕЛЬНО проверить что нет коллизий:
    
    | Префикс              | TZ      | Тип      | Назначение                    |
    |----------------------|---------|----------|-------------------------------|
    | sphere:agent:cmd:*   | TZ-03   | PubSub   | Команды к агенту              |
    | sphere:org:events:*  | TZ-03   | PubSub   | Broadcast событий организации |
    | sphere:stream:video:*| TZ-03   | PubSub   | Видеопоток от агента          |
    | sphere:agent:result:*| TZ-03   | PubSub   | Ответы на команды             |
    | device:status:*      | TZ-02   | Key/Val  | Live статус устройства (msgpack) |
    | task:queue:*         | TZ-04   | ZSet     | Очередь задач для dispatch    |
    | vpn:pool:*           | TZ-06   | Hash     | VPN конфигурации пула         |
    | session:*            | TZ-01   | Key/Val  | Refresh token sessions        |
    
    ПРАВИЛО: sphere:* = PubSub каналы (TZ-03), остальные = data keys.
    Коллизий НЕТ при соблюдении префиксов.
    """
    
    # MED-5: префикс "sphere:" — избегает коллизий в shared Redis (TZ-06 тоже использует Redis)
    # Команды к конкретному агенту
    AGENT_CMD = "sphere:agent:cmd:{device_id}"
    
    # Broadcast событий организации (статусы, алерты)
    ORG_EVENTS = "sphere:org:events:{org_id}"
    
    # Видеопоток (от агента к API воркеру)
    VIDEO_STREAM = "sphere:stream:video:{device_id}"
    
    # Ответы на команды
    AGENT_RESULT = "sphere:agent:result:{device_id}:{command_id}"
    
    @staticmethod
    def agent_cmd(device_id: str) -> str:
        return f"sphere:agent:cmd:{device_id}"
    
    @staticmethod
    def org_events(org_id: str) -> str:
        return f"sphere:org:events:{org_id}"
    
    @staticmethod
    def video_stream(device_id: str) -> str:
        return f"sphere:stream:video:{device_id}"
    
    @staticmethod
    def agent_result_pattern(device_id: str) -> str:
        return f"sphere:agent:result:{device_id}:*"
```

---

## Шаг 2 — Redis Pub/Sub Router

```python
# backend/websocket/pubsub_router.py
import asyncio
import json
import structlog

logger = structlog.get_logger()

class PubSubRouter:
    """
    Мост между Redis PubSub и локальным ConnectionManager.
    Один экземпляр на воркер, подписывается на нужные каналы.
    """
    
    def __init__(self, redis, connection_manager: ConnectionManager):
        self.redis = redis
        self.manager = connection_manager
        self._subscribed_channels: set[str] = set()
        self._pubsub = None
        self._task: asyncio.Task | None = None
    
    async def start(self):
        """Запустить прослушивание в фоне."""
        self._pubsub = self.redis.pubsub()
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("PubSub router started")
    
    async def stop(self):
        if self._task:
            self._task.cancel()
        if self._pubsub:
            await self._pubsub.close()
    
    async def subscribe_device(self, device_id: str, org_id: str):
        """Подписаться на командный канал устройства при подключении агента."""
        cmd_channel = ChannelPattern.agent_cmd(device_id)
        if cmd_channel not in self._subscribed_channels:
            await self._pubsub.subscribe(cmd_channel)
            self._subscribed_channels.add(cmd_channel)
        
        org_channel = ChannelPattern.org_events(org_id)
        if org_channel not in self._subscribed_channels:
            await self._pubsub.subscribe(org_channel)
            self._subscribed_channels.add(org_channel)
    
    async def unsubscribe_device(self, device_id: str):
        cmd_channel = ChannelPattern.agent_cmd(device_id)
        if cmd_channel in self._subscribed_channels:
            await self._pubsub.unsubscribe(cmd_channel)
            self._subscribed_channels.discard(cmd_channel)
    
    async def _listen_loop(self):
        """Основной цикл прослушивания Redis."""
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                
                channel: str = message["channel"]
                data = message["data"]
                
                try:
                    await self._route_message(channel, data)
                except Exception as e:
                    logger.error("PubSub route error", channel=channel, error=str(e))
        except asyncio.CancelledError:
            pass
    
    async def _route_message(self, channel: str, data: bytes):
        # MED-7: removeprefix() вместо split(":")[-1] — безопасно для device_id вида "192.168.1.1:5555"
        if channel.startswith("sphere:agent:cmd:"):
            device_id = channel.removeprefix("sphere:agent:cmd:")
            msg = json.loads(data)
            await self.manager.send_to_device(device_id, msg)
        
        elif channel.startswith("sphere:org:events:"):
            org_id = channel.removeprefix("sphere:org:events:")
            msg = json.loads(data)
            await self.manager.broadcast_to_org(org_id, msg)
        
        elif channel.startswith("sphere:stream:video:"):
            device_id = channel.removeprefix("sphere:stream:video:")
            # Бинарные данные — переслать viewer WebSocket
            await self._forward_video_to_viewers(device_id, data)


class PubSubPublisher:
    """
    Публикатор — отправляет команды через Redis PubSub.
    Используется API endpoint'ами для отправки команд агентам.
    """
    
    def __init__(self, redis):
        self.redis = redis
    
    async def send_command_to_device(
        self,
        device_id: str,
        command: dict,
    ) -> bool:
        """
        Отправить команду агенту через Redis PubSub.
        Команда будет доставлена воркеру, у которого есть подключение.
        """
        channel = ChannelPattern.agent_cmd(device_id)
        payload = json.dumps(command)
        subscribers = await self.redis.publish(channel, payload)
        return subscribers > 0
    
    async def broadcast_org_event(self, org_id: str, event: dict) -> int:
        channel = ChannelPattern.org_events(org_id)
        payload = json.dumps(event)
        return await self.redis.publish(channel, payload)
    
    async def send_command_wait_result(
        self,
        device_id: str,
        command: dict,
        timeout: float = 30.0,
    ) -> dict:
        """
        Отправить команду и ждать ответ.
        Использует временный канал агент:result:{device_id}:{command_id}.
        """
        command_id = command.setdefault("id", secrets.token_hex(8))
        result_channel = f"agent:result:{device_id}:{command_id}"
        
        # Подписаться ДО публикации во избежание race condition
        async with self.redis.pubsub() as ps:
            await ps.subscribe(result_channel)
            
            sent = await self.send_command_to_device(device_id, command)
            if not sent:
                raise HTTPException(503, f"Device '{device_id}' is offline")
            
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout
                async for msg in ps.listen():
                    if msg["type"] == "message":
                        return json.loads(msg["data"])
                    if loop.time() > deadline:
                        raise asyncio.TimeoutError()
            except asyncio.TimeoutError:
                raise HTTPException(504, f"Command timeout after {timeout}s")
```

---

## Шаг 3 — Lifespan Integration

```python
# backend/websocket/pubsub_router.py — в конце файла (CRIT-3: не трогаем frozen main.py)
# Регистрация хуков через lifespan_registry (TZ-00 SPLIT-1 Шаг 4)
from backend.core.lifespan_registry import register_startup, register_shutdown

# PubSubRouter должен быть singleton — хранится в app.state или модульной переменной
_pubsub_router_instance: PubSubRouter | None = None

def get_pubsub_router_instance() -> PubSubRouter:
    """Вернуть singleton PubSubRouter. Создаётся при первом вызове."""
    global _pubsub_router_instance
    if _pubsub_router_instance is None:
        from backend.websocket.connection_manager import get_connection_manager
        from backend.core.redis import get_redis
        _pubsub_router_instance = PubSubRouter(get_redis(), get_connection_manager())
    return _pubsub_router_instance

register_startup("pubsub_router", get_pubsub_router_instance().start)
register_shutdown("pubsub_router", get_pubsub_router_instance().stop)
```

---

## Критерии готовности

- [ ] Команда через PubSub доставляется агенту на другом воркере (проверить с 2 uvicorn воркерами)
- [ ] `send_command_wait_result()` — ответ получен в течение timeout
- [ ] Timeout → 504 (не зависает)
- [ ] Агент оффлайн → `publish` вернул 0 → 503 немедленно
- [ ] Org broadcast: получают только агенты нужной org
- [ ] Нет утечки подписок при disconnect (unsubscribe вызывается)
