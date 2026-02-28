# backend/services/device_status_cache.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-3. Redis-backed device status cache with msgpack serialization.
from __future__ import annotations

from typing import Any

import msgpack

from backend.schemas.device_status import DeviceLiveStatus


class DeviceStatusCache:
    """
    Кэш live-статусов устройств в Redis.

    Форматы ключей:
        device:status:{device_id}       — DeviceLiveStatus (msgpack)

    TTL:
        online  → 120s  (агент шлёт heartbeat каждые 30s)
        другой  → 3600s (хранить оффлайн статус 1 час)
    """

    KEY_PREFIX = "device:status:"
    TTL_ONLINE = 120
    TTL_OFFLINE = 3600

    def __init__(self, redis: Any) -> None:
        self.redis = redis

    def _key(self, device_id: str) -> str:
        return f"{self.KEY_PREFIX}{device_id}"

    # ── Single device ─────────────────────────────────────────────────────────

    async def set_status(self, device_id: str, status: DeviceLiveStatus) -> None:
        if self.redis is None:
            return
        key = self._key(device_id)
        data = msgpack.packb(status.model_dump(mode="json"), use_bin_type=True)
        ttl = self.TTL_ONLINE if status.status == "online" else self.TTL_OFFLINE
        await self.redis.set(key, data, ex=ttl)

    async def get_status(self, device_id: str) -> DeviceLiveStatus | None:
        if self.redis is None:
            return None
        raw = await self.redis.get(self._key(device_id))
        if raw is None:
            return None
        try:
            unpacked = msgpack.unpackb(raw, raw=False)
        except Exception:
            # Stale or corrupted Redis entry — treat as missing
            return None
        return DeviceLiveStatus.model_validate(unpacked)

    async def mark_offline(self, device_id: str) -> None:
        """Called on WebSocket disconnect (TZ-03 hook)."""
        existing = await self.get_status(device_id)
        if existing:
            existing.status = "offline"
            existing.adb_connected = False
            existing.ws_session_id = None
            await self.set_status(device_id, existing)
        else:
            await self.set_status(
                device_id, DeviceLiveStatus(device_id=device_id, status="offline")
            )

    # ── Bulk (MGET — single Redis round-trip) ────────────────────────────────

    async def bulk_get_status(
        self, device_ids: list[str]
    ) -> dict[str, DeviceLiveStatus | None]:
        """O(1) RTT — fetch N statuses with a single MGET."""
        if not device_ids:
            return {}
        if self.redis is None:
            return {did: None for did in device_ids}
        keys = [self._key(did) for did in device_ids]
        values = await self.redis.mget(*keys)
        result: dict[str, DeviceLiveStatus | None] = {}
        for device_id, raw in zip(device_ids, values):
            if raw is not None:
                try:
                    unpacked = msgpack.unpackb(raw, raw=False)
                    result[device_id] = DeviceLiveStatus.model_validate(unpacked)
                except Exception:
                    result[device_id] = None
            else:
                result[device_id] = None
        return result

    # ── Fleet aggregation ────────────────────────────────────────────────────

    async def get_fleet_summary(
        self, device_ids: list[str]
    ) -> dict:
        """Aggregate summary + per-device statuses for fleet dashboard."""
        statuses = await self.bulk_get_status(device_ids)
        online = sum(1 for s in statuses.values() if s and s.status == "online")
        busy = sum(1 for s in statuses.values() if s and s.status == "busy")
        return {
            "total": len(device_ids),
            "online": online,
            "busy": busy,
            "offline": len(device_ids) - online - busy,
            "devices": statuses,
        }

    async def get_all_tracked_device_ids(self) -> list[str]:
        """Return all device_ids tracked in Redis (for background sync)."""
        prefix = self.KEY_PREFIX
        result: list[str] = []
        async for key in self.redis.scan_iter(f"{prefix}*"):
            key_str = key.decode() if isinstance(key, bytes) else key
            result.append(key_str.removeprefix(prefix))
        return result


def get_status_cache_from_redis(redis: Any) -> DeviceStatusCache:
    return DeviceStatusCache(redis)
