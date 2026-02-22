# backend/database/redis_client.py
import redis.asyncio as aioredis

from backend.core.config import settings
from backend.core.lifespan_registry import register_startup, register_shutdown

# Основной клиент (строки: JWT blacklist, rate-limit, статусы устройств)
redis: aioredis.Redis | None = None

# FIX: отдельный клиент без decode_responses для бинарных каналов (H.264 NAL units).
# Канал stream:{agent_id} передаёт бинарные данные — decode_responses=True вызовет UnicodeDecodeError.
# Используй redis_binary для Pub/Sub видеострима (TZ-05).
# Используй redis (с decode_responses=True) для всего остального.
redis_binary: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """FastAPI dependency для Redis (строки: JWT blacklist, rate-limit, статусы устройств)."""
    return redis


async def get_redis_binary() -> aioredis.Redis:
    """FastAPI dependency для бинарного Redis (Pub/Sub H.264 NAL units, video stream)."""
    return redis_binary


async def connect_redis() -> None:
    global redis, redis_binary

    redis_kwargs = {
        "encoding": "utf-8" if not settings.REDIS_PASSWORD else None,
    }

    redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    redis_binary = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=False,
        max_connections=20,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    # Проверяем соединение
    await redis.ping()
    await redis_binary.ping()


async def disconnect_redis() -> None:
    global redis, redis_binary
    if redis:
        await redis.aclose()
    if redis_binary:
        await redis_binary.aclose()


# Регистрируем хуки автоматически при импорте модуля
register_startup("redis", connect_redis)
register_shutdown("redis", disconnect_redis)
