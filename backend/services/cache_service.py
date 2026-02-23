# backend/services/cache_service.py
# Redis-based cache/state service.
# TZ-03 WebSocket Layer и TZ-02 Device Registry расширяют этот модуль.
from __future__ import annotations

from backend.database.redis_client import get_redis


class CacheService:
    """
    Сервис для работы с Redis: статусы устройств, JWT blacklist, rate limiting.

    Ключевые префиксы:
      device:status:{org_id}:{device_id}   — DeviceStatus (TTL = DEVICE_STATUS_TTL сек)
      jwt:blacklist:{jti}                  — флаг отозванного токена
      ratelimit:{org_id}:{user_id}:{win}   — счётчик rate limiting (TTL = window_seconds)
    """

    DEVICE_STATUS_PREFIX = "device:status"
    JWT_BLACKLIST_PREFIX = "jwt:blacklist"
    RATE_LIMIT_PREFIX = "ratelimit"

    async def set_device_status(
        self,
        org_id: str,
        device_id: str,
        status: str,
        ttl: int = 90,
    ) -> None:
        """Записать статус устройства с TTL. Source of truth — Redis."""
        key = f"{self.DEVICE_STATUS_PREFIX}:{org_id}:{device_id}"
        redis = await get_redis()
        await redis.set(key, status, ex=ttl)

    async def get_device_status(self, org_id: str, device_id: str) -> str | None:
        """Получить статус одного устройства. None если TTL истёк (offline)."""
        key = f"{self.DEVICE_STATUS_PREFIX}:{org_id}:{device_id}"
        redis = await get_redis()
        return await redis.get(key)

    async def get_all_device_statuses(self, org_id: str, device_ids: list[str]) -> dict[str, str | None]:
        """
        Массовый MGET статусов. O(N) — одна RTT до Redis вместо N.
        Returns dict {device_id: status_or_None}.
        """
        if not device_ids:
            return {}
        redis = await get_redis()
        keys = [f"{self.DEVICE_STATUS_PREFIX}:{org_id}:{d}" for d in device_ids]
        values = await redis.mget(*keys)
        return dict(zip(device_ids, values))

    async def blacklist_token(self, jti: str, ttl_seconds: int) -> None:
        """
        Добавить JTI в blacklist.
        TTL = оставшееся время жизни access-токена (exp - now).
        """
        key = f"{self.JWT_BLACKLIST_PREFIX}:{jti}"
        redis = await get_redis()
        await redis.set(key, "1", ex=ttl_seconds)

    async def is_token_blacklisted(self, jti: str) -> bool:
        """Проверить, отозван ли токен по JTI."""
        key = f"{self.JWT_BLACKLIST_PREFIX}:{jti}"
        redis = await get_redis()
        return bool(await redis.exists(key))

    async def check_rate_limit(
        self,
        identifier: str,
        window_seconds: int = 60,
        max_requests: int = 100,
    ) -> tuple[bool, int]:
        """
        Sliding window rate limiting (incrementing counter with TTL).
        Returns (allowed: bool, current_count: int).
        """
        key = f"{self.RATE_LIMIT_PREFIX}:{identifier}"
        redis = await get_redis()

        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

        current = results[0]
        allowed = current <= max_requests
        return allowed, current


    async def set(self, key: str, value: str, ttl: int) -> None:
        """Универсальный SET с TTL. Используется для MFA state tokens и прочего."""
        redis = await get_redis()
        await redis.set(key, value, ex=ttl)

    async def get(self, key: str) -> str | None:
        """Универсальный GET."""
        redis = await get_redis()
        return await redis.get(key)

    async def delete(self, key: str) -> None:
        """Удалить ключ."""
        redis = await get_redis()
        await redis.delete(key)


cache_service = CacheService()
