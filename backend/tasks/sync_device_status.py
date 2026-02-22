# backend/tasks/sync_device_status.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-3.
# Фоновая задача: синхронизирует live-статусы из Redis → PostgreSQL каждые 60s.
# Регистрируется при старте через lifespan_registry.
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import update

logger = logging.getLogger(__name__)


async def sync_device_status_to_db() -> None:
    """
    Читает live-статусы из DeviceStatusCache и обновляет last_status + last_seen_at
    в таблице devices. Вызывается раз в 60 секунд.

    Паттерн: не трогаем устройства, у которых нет записи в Redis
    (чтобы не затирать их статус при перезапуске кэша).
    """
    from backend.database.engine import async_session_factory
    from backend.database.redis_client import redis as _redis
    from backend.models.device import Device
    from backend.services.device_status_cache import DeviceStatusCache

    if _redis is None:
        return

    cache = DeviceStatusCache(_redis)
    device_ids = await cache.get_all_tracked_device_ids()
    if not device_ids:
        return

    statuses = await cache.bulk_get_status(device_ids)
    now = datetime.now(timezone.utc)

    async with async_session_factory() as db:
        try:
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
            await db.commit()
            logger.debug("sync_device_status_to_db: updated %d devices", len(statuses))
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
