# SPLIT-4 — Heartbeat & Timeout (Мониторинг здоровья соединений)

**ТЗ-родитель:** TZ-03-WebSocket-Layer  
**Ветка:** `stage/3-websocket`  
**Задача:** `SPHERE-019`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** TZ-03 SPLIT-5
**Интеграция при merge:** TZ-02 Device Status работает с mock heartbeat; при merge подключить реальный WS heartbeat

---

## Цель Сплита

Автоматическое обнаружение зависших WebSocket соединений. Heartbeat ping/pong каждые 30 секунд с принудительным закрытием по таймауту.

---

## Шаг 1 — Heartbeat Protocol

```python
# backend/websocket/heartbeat.py

# ─── MERGE-2: HEARTBEAT CONTRACT ────────────────────────────────────
# Эти константы — ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ для таймаутов.
# TZ-07 Android Agent (SPLIT-2) ОБЯЗАН использовать ИДЕНТИЧНЫЕ значения:
#   HEARTBEAT_INTERVAL = 30с → Android: pong timeout = 30 + 15 = 45с
#   HEARTBEAT_TIMEOUT  = 15с → Server закрывает WS через 45с без pong
#
# Нарушение контракта:
#   Server 30+15=45с, Android backoff 30с → OK
#   Server 30+15=45с, Android backoff 60с → Server закроет WS ложно!
#
# При merge: проверить что Android SPLIT-2 содержит:
#   private val PONG_TIMEOUT_MS = 45_000L  // 30с interval + 15с timeout
# ─────────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 30.0   # Секунды между ping
HEARTBEAT_TIMEOUT = 15.0    # Секунды ожидания pong

class HeartbeatManager:
    """
    Высокоуровневый heartbeat поверх WebSocket ping/pong.
    
    Протокол:
    Server → Agent: {"type": "ping", "ts": 1234567890.123}
    Agent → Server: {"type": "pong", "ts": 1234567890.123, "battery": 87, ...}
    """
    
    def __init__(self, ws: WebSocket, device_id: str, status_cache: DeviceStatusCache):
        self.ws = ws
        self.device_id = device_id
        self.status_cache = status_cache
        self._last_pong: float = time.monotonic()
        self._task: asyncio.Task | None = None
    
    async def start(self):
        self._task = asyncio.create_task(self._heartbeat_loop())
    
    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    async def _heartbeat_loop(self):
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                
                # Проверить когда был последний pong
                since_pong = time.monotonic() - self._last_pong
                if since_pong > (HEARTBEAT_INTERVAL + HEARTBEAT_TIMEOUT):
                    logger.warning(
                        "Agent heartbeat timeout", 
                        device_id=self.device_id,
                        since_pong_s=since_pong,
                    )
                    await self.ws.close(code=4008, reason="heartbeat_timeout")
                    return
                
                # Отправить ping
                await self.ws.send_json({
                    "type": "ping",
                    "ts": time.time(),
                    "server_ts": time.monotonic(),
                })
            except (WebSocketDisconnect, Exception):
                return
    
    async def handle_pong(self, msg: dict):
        """Вызвать при получении pong от агента."""
        self._last_pong = time.monotonic()
        
        # Обновить live статус из телеметрии в pong
        status_update: dict = {}
        if "battery" in msg:
            status_update["battery"] = msg["battery"]
        if "cpu" in msg:
            status_update["cpu_usage"] = msg["cpu"]
        if "ram_mb" in msg:
            status_update["ram_usage_mb"] = msg["ram_mb"]
        if "screen_on" in msg:
            status_update["screen_on"] = msg["screen_on"]
        if "vpn_active" in msg:
            status_update["vpn_active"] = msg["vpn_active"]
        
        if status_update:
            current = await self.status_cache.get_status(self.device_id)
            if current:
                for key, val in status_update.items():
                    setattr(current, key, val)
                current.last_heartbeat = datetime.now(timezone.utc)
                await self.status_cache.set_status(self.device_id, current)
```

---

## Шаг 2 — Интеграция в Android WS Endpoint

```python
# backend/api/ws/android.py (дополнение к SPLIT-1)

@router.websocket("/ws/android/{device_id}")
async def android_agent_ws(ws: WebSocket, device_id: str, ...):
    # ... auth, connect ...
    
    heartbeat = HeartbeatManager(ws, device_id, status_cache)
    await heartbeat.start()
    
    try:
        while True:
            data = await ws.receive()
            
            if "text" in data:
                msg = json.loads(data["text"])
                
                match msg.get("type"):
                    case "pong":
                        await heartbeat.handle_pong(msg)
                    case "telemetry":
                        await handle_telemetry(device_id, msg, status_cache)
                    case "command_result":
                        await handle_command_result(device_id, msg, publisher)
                    case "event":
                        await handle_device_event(device_id, msg, publisher)
                    case _:
                        logger.debug("Unknown message type", type=msg.get("type"))
            
            elif "bytes" in data:
                # Видеофрейм
                await stream_bridge.handle_agent_frame(device_id, data["bytes"])
    
    except WebSocketDisconnect:
        pass
    finally:
        await heartbeat.stop()
        await manager.disconnect(device_id)
        await status_cache.mark_offline(device_id)
```

---

## Шаг 3 — Android Agent: Heartbeat Response (Kotlin)

> [!IMPORTANT]
> Начиная с Android 14+, система агрессивно убивает фоновые сокеты в Doze mode. Для обеспечения надежного Heartbeat необходимо интегрировать `HeartbeatHandler` с `WorkManager` (PeriodicWorkRequest) или Foreground Service с wakelock, чтобы гарантировать отправку pong-ответов и предотвратить отключение сокета.

// Kotlin: AndroidAgent/websocket/HeartbeatHandler.kt
class HeartbeatHandler(
    private val deviceStatusProvider: DeviceStatusProvider,
    private val wsClient: SphereWebSocketClient,
) {
    fun handlePing(pingMsg: JsonObject) {
        val response = buildJsonObject {
            put("type", "pong")
            put("ts", pingMsg["ts"]?.jsonPrimitive?.doubleOrNull ?: 0.0)

            // Телеметрия в pong для экономии сообщений
            with(deviceStatusProvider) {
                put("battery", getBatteryLevel())
                put("cpu", getCpuUsage())
                put("ram_mb", getRamUsageMb())
                put("screen_on", isScreenOn())
                put("vpn_active", isVpnActive())
                put("storage_free_mb", getStorageFreeMb())
            }
        }
        wsClient.sendJson(response)
    }
}

```

---

## Критерии готовности

- [ ] Агент не отвечает 45+ секунд → соединение закрывается с кодом 4008
- [ ] Pong обновляет battery/cpu/ram в Redis (без записи в PG)
- [ ] HeartbeatManager останавливается в finally (нет утечки Task)
- [ ] Нормальный reconnect после разрыва: heartbeat timer стартует заново
- [ ] Latency метрика: `ping_ts` - `pong_ts` логируется для мониторинга
