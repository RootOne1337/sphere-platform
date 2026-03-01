# SPLIT-3 — Device Status в Redis (Real-Time Cache)

**ТЗ-родитель:** TZ-02-Device-Registry  
**Ветка:** `stage/2-device-registry`  
**Задача:** `SPHERE-013`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** TZ-02 SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-03 и TZ-10 работают с mock device status; при merge подключить Redis-кэш

---

## Цель Сплита

Кеш реального статуса устройств в Redis с агрегацией через MGET для fleet dashboard.

---

## Шаг 1 — DeviceStatus Schema

```python
# backend/schemas/device_status.py
class DeviceLiveStatus(BaseModel):
    device_id: str
    status: Literal["online", "offline", "busy", "error", "connecting"]
    adb_connected: bool = False
    battery: int | None = None      # 0-100
    cpu_usage: float | None = None  # 0.0-100.0
    ram_usage_mb: int | None = None
    screen_on: bool | None = None
    vpn_active: bool | None = None
    android_version: str | None = None
    last_heartbeat: datetime | None = None
    ws_session_id: str | None = None   # ID WebSocket сессии агента
    current_task_id: uuid.UUID | None = None
```

---

## Шаг 2 — Redis Status Service

```python
# backend/services/device_status_cache.py
import msgpack

class DeviceStatusCache:
    KEY_PREFIX = "device:status:"
    TTL_ONLINE = 120      # 2 минуты — агент должен слать heartbeat каждые 30s
    TTL_OFFLINE = 3600    # Хранить оффлайн статус 1 час
    
    def __init__(self, redis: Redis):
        self.redis = redis
    
    async def set_status(self, device_id: str, status: DeviceLiveStatus):
        key = f"{self.KEY_PREFIX}{device_id}"
        data = msgpack.packb(status.model_dump(mode="json"), use_bin_type=True)
        ttl = self.TTL_ONLINE if status.status == "online" else self.TTL_OFFLINE
        await self.redis.set(key, data, ex=ttl)
    
    async def get_status(self, device_id: str) -> DeviceLiveStatus | None:
        key = f"{self.KEY_PREFIX}{device_id}"
        data = await self.redis.get(key)
        if data is None:
            return None
        raw = msgpack.unpackb(data, raw=False)
        return DeviceLiveStatus.model_validate(raw)
    
    async def bulk_get_status(self, device_ids: list[str]) -> dict[str, DeviceLiveStatus | None]:
        """Получить статусы для N устройств одним MGET (O(1) для Redis)."""
        if not device_ids:
            return {}
        
        keys = [f"{self.KEY_PREFIX}{did}" for did in device_ids]
        values = await self.redis.mget(*keys)
        
        result = {}
        for device_id, raw in zip(device_ids, values):
            if raw is not None:
                unpacked = msgpack.unpackb(raw, raw=False)
                result[device_id] = DeviceLiveStatus.model_validate(unpacked)
            else:
                result[device_id] = None
        return result
    
    async def mark_offline(self, device_id: str):
        """Вызывается при disconnect WebSocket — статус оффлайн."""
        existing = await self.get_status(device_id)
        if existing:
            existing.status = "offline"
            existing.adb_connected = False
            existing.ws_session_id = None
            await self.set_status(device_id, existing)
        else:
            await self.set_status(device_id, DeviceLiveStatus(
                device_id=device_id,
                status="offline",
            ))
    
    async def get_all_tracked_device_ids(self) -> list[str]:
        """Вернуть все device_id, для которых есть запись в Redis (для фоновой синхронизации)."""
        pattern = f"{self.KEY_PREFIX}*"
        keys = []
        async for key in self.redis.scan_iter(pattern):
            device_id = key.decode() if isinstance(key, bytes) else key
            keys.append(device_id.removeprefix(self.KEY_PREFIX))
        return keys
    
    async def get_fleet_summary(self, org_id: uuid.UUID, device_ids: list[str]) -> dict:
        """Агрегация для fleet dashboard."""
        statuses = await self.bulk_get_status(device_ids)
        
        online = sum(1 for s in statuses.values() if s and s.status == "online")
        busy = sum(1 for s in statuses.values() if s and s.status == "busy")
        offline = len(device_ids) - online - busy
        
        return {
            "total": len(device_ids),
            "online": online,
            "busy": busy,
            "offline": offline,
            "devices": statuses,
        }
```

---

## Шаг 3 — Fleet Status Endpoint

```python
# backend/api/v1/devices.py (добавить)

@router.post("/status/bulk", response_model=FleetStatusResponse)
async def get_fleet_status(
    body: BulkStatusRequest,  # {device_ids: list[str]}
    current_user: User = require_permission("device:read"),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
    svc: DeviceService = Depends(get_device_service),
):
    """Получить live статус для списка устройств (для Dashboard)."""
    # Убедиться что все device_ids принадлежат этой org
    owned_ids = await svc.filter_owned(body.device_ids, current_user.org_id)
    
    return await status_cache.get_fleet_summary(current_user.org_id, owned_ids)

@router.get("/status/fleet", response_model=FleetSummaryResponse)
async def get_all_fleet_status(
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
):
    """Весь fleet организации для Dashboard."""
    all_ids = await svc.get_all_device_ids(current_user.org_id)
    return await status_cache.get_fleet_summary(current_user.org_id, all_ids)
```

---

## Шаг 4 — DB Status Sync (background task)

```python
# backend/tasks/sync_device_status.py
async def sync_device_status_to_db(db: AsyncSession, status_cache: DeviceStatusCache):
    """
    Фоновая задача каждые 60 секунд:
    читает из Redis, обновляет last_seen_at и status в PostgreSQL.
    Это позволяет не писать в PG при каждом heartbeat.
    """
    device_ids = await status_cache.get_all_tracked_device_ids()
    statuses = await status_cache.bulk_get_status(device_ids)
    
    now = datetime.now(timezone.utc)
    for device_id, live in statuses.items():
        if live is None:
            continue
        await db.execute(
            update(Device)
            .where(Device.id == device_id)
            .values(
                status=live.status,
                last_seen_at=live.last_heartbeat or now,
            )
        )
    await db.commit()
```

---

## Критерии готовности

- [ ] MGET для 500 устройств занимает < 5ms
- [ ] Heartbeat каждые 30s → TTL обновляется, статус online
- [ ] WebSocket disconnect → `mark_offline()` вызывается автоматически (см. TZ-03)
- [ ] Фоновая задача синхронизирует Redis → PostgreSQL раз в 60s
- [ ] `/status/fleet` возвращает total/online/busy/offline агрегацию
- [ ] msgpack для сериализации (в ~5x меньше JSON)
