# backend/tasks/sync_device_status.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-3.
# Фоновая задача: синхронизирует live-статусы из Redis → PostgreSQL каждые 60s.
# Регистрируется при старте через lifespan_registry.
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import update

logger = logging.getLogger(__name__)


async def sync_device_status_to_db() -> None:
    """
    Читает live-статусы из DeviceStatusCache и обновляет last_status + last_seen_at
    в таблице devices. Вызывается раз в 60 секунд.

    Паттерн:
    - Обновляет статус устройств, которые есть в Redis-кэше.
    - Помечает OFFLINE устройства, у которых last_status=ONLINE в БД,
      но нет активной Redis-записи (защита от stale online-статусов).
    """
    from backend.database.engine import AsyncSessionLocal
    from backend.database.redis_client import redis_binary as _redis_bin
    from backend.models.device import Device
    from backend.services.device_status_cache import DeviceStatusCache

    if _redis_bin is None:
        return

    cache = DeviceStatusCache(_redis_bin)
    device_ids = await cache.get_all_tracked_device_ids()

    online_in_redis: set[str] = set()

    async with AsyncSessionLocal() as db:
        try:
            # 1. Обновляем устройства с Redis-записями
            if device_ids:
                statuses = await cache.bulk_get_status(device_ids)
                for device_id, live in statuses.items():
                    if live is None:
                        continue
                    try:
                        import uuid
                        dev_uuid = uuid.UUID(device_id)
                    except ValueError:
                        continue
                    await db.execute(
                        update(Device)
                        .where(Device.id == dev_uuid)
                        .values(
                            last_status=live.status,
                        )
                    )
                    if live.status == "online":
                        online_in_redis.add(device_id)

            # 2. Помечаем stale ONLINE → OFFLINE
            # Устройства с last_status=ONLINE в БД, но без online-записи в Redis
            from sqlalchemy import select as sa_select

            from backend.models.device import DeviceStatus
            stale_online = (await db.execute(
                sa_select(Device.id).where(
                    Device.last_status == DeviceStatus.ONLINE,
                )
            )).scalars().all()

            stale_count = 0
            for dev_id in stale_online:
                if str(dev_id) not in online_in_redis:
                    await db.execute(
                        update(Device)
                        .where(Device.id == dev_id)
                        .values(last_status="offline")
                    )
                    stale_count += 1

            await db.commit()
            if stale_count:
                logger.info("sync_device_status_to_db: fixed %d stale ONLINE devices", stale_count)
            logger.debug("sync_device_status_to_db: updated %d devices", len(device_ids))
        except Exception as exc:
            logger.error("sync_device_status_to_db failed: %s", exc)
            await db.rollback()


async def _run_periodic_sync(interval: int = 60) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await sync_device_status_to_db()
        except Exception as exc:
            logger.error("Periodic device status sync error: %s", exc)


def start_periodic_sync(interval: int = 60) -> asyncio.Task:
    """Schedule the background sync loop. Call from lifespan startup."""
    loop = asyncio.get_event_loop()
    return loop.create_task(_run_periodic_sync(interval))


# ── Авторегистрация через lifespan_registry ──────────────────────────────────
async def _startup_device_status_sync() -> None:
    """Запускает периодическую синхронизацию статусов устройств Redis → PostgreSQL."""
    start_periodic_sync(interval=60)
    logger.info("device_status_sync.started", extra={"interval_seconds": 60})


from backend.core.lifespan_registry import register_startup  # noqa: E402

register_startup("device_status_sync", _startup_device_status_sync)
