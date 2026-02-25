# backend/tasks/vpn_health.py  TZ-06 SPLIT-3
# Background task: check VPN peer health every 60 seconds.
# Uses a distributed Redis lock (SET NX EX) so only one backend instance runs per cycle.
from __future__ import annotations

import asyncio
import uuid

import structlog

logger = structlog.get_logger()

HEALTH_LOCK_KEY = "vpn:health_loop:lock"
HEALTH_LOCK_TTL = 90  # seconds  slightly longer than the 60s interval


async def vpn_health_loop() -> None:
    """
    Infinite loop: check VPN health every 60 s.
    Acquires a distributed Redis lock to prevent duplicate work when
    multiple backend instances are running.
    """
    from backend.database.redis_client import redis as _redis

    while True:
        try:
            lock_value = str(uuid.uuid4())
            if _redis is None:
                await asyncio.sleep(60)
                continue
            acquired = await _redis.set(
                HEALTH_LOCK_KEY, lock_value, nx=True, ex=HEALTH_LOCK_TTL
            )
            if not acquired:
                await asyncio.sleep(60)
                continue

            try:
                await _run_health_checks()
            finally:
                current = await _redis.get(HEALTH_LOCK_KEY)
                if current:
                    val = current.decode() if isinstance(current, bytes) else current
                    if val == lock_value:
                        await _redis.delete(HEALTH_LOCK_KEY)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("VPN health loop error", exc=str(exc))

        await asyncio.sleep(60)


async def _run_health_checks() -> None:
    """Create DB session and run VPNHealthMonitor for every active org."""
    from sqlalchemy import select

    from backend.core.config import settings
    from backend.database.engine import get_db_session
    from backend.database.redis_client import redis as _redis
    from backend.models.organization import Organization
    from backend.services.vpn.dependencies import get_awg_config_builder, get_key_cipher
    from backend.services.vpn.event_publisher import EventPublisher
    from backend.services.vpn.health_monitor import VPNHealthMonitor
    from backend.services.vpn.ip_pool import IPPoolAllocator
    from backend.services.vpn.pool_service import VPNPoolService

    async with get_db_session() as db:
        result = await db.execute(select(Organization))
        orgs = list(result.scalars().all())

        config_builder = get_awg_config_builder()
        key_cipher = get_key_cipher()
        ip_pool = IPPoolAllocator(_redis, subnet=settings.VPN_POOL_SUBNET)
        pool_svc = VPNPoolService(
            db=db,
            ip_pool=ip_pool,
            config_builder=config_builder,
            key_cipher=key_cipher,
            wg_router_url=settings.WG_ROUTER_URL,
        )
        publisher = EventPublisher()
        monitor = VPNHealthMonitor(
            db=db,
            pool_service=pool_svc,
            publisher=publisher,
            wg_router_url=settings.WG_ROUTER_URL,
            redis=_redis,
        )
        try:
            for org in orgs:
                await monitor.check_all_peers(org.id)
        finally:
            await monitor.close()
            await pool_svc.close()
