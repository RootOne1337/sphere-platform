# backend/database/redis_client.py
import redis.asyncio as aioredis

from backend.core.config import settings
from backend.core.lifespan_registry import register_shutdown, register_startup

# Основной клиент (строки: JWT blacklist, rate-limit, статусы устройств)
redis: aioredis.Redis | None = None

# FIX: отдельный клиент без decode_responses для бинарных каналов (H.264 NAL units).
# Канал stream:{agent_id} передаёт бинарные данные — decode_responses=True вызовет UnicodeDecodeError.
# Используй redis_binary для Pub/Sub видеострима (TZ-05).
# Используй redis (с decode_responses=True) для всего остального.
redis_binary: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis | None:
    """FastAPI dependency для Redis (строки: JWT blacklist, rate-limit, статусы устройств)."""
    return redis


async def get_redis_binary() -> aioredis.Redis | None:
    """FastAPI dependency для бинарного Redis (Pub/Sub H.264 NAL units, video stream)."""
    return redis_binary


async def connect_redis() -> None:
    global redis, redis_binary

    redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    redis_binary = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=False,
        max_connections=20,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    # Проверяем соединение
    await redis.ping()  # type: ignore[misc]
    await redis_binary.ping()  # type: ignore[misc]


async def disconnect_redis() -> None:
    global redis, redis_binary
    if redis:
        await redis.aclose()  # type: ignore[misc]
    if redis_binary:
        await redis_binary.aclose()  # type: ignore[misc]


# Регистрируем хуки автоматически при импорте модуля
register_startup("redis", connect_redis)
register_shutdown("redis", disconnect_redis)
