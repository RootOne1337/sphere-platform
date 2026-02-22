# backend/services/vpn/dependencies.py — TZ-06 SPLIT-1..4
# FastAPI Depends-фабрики для VPN сервисов.
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.services.vpn.awg_config import AWGConfigBuilder


@lru_cache(maxsize=1)
def get_awg_config_builder() -> AWGConfigBuilder:
    """DI: singleton AWGConfigBuilder с параметрами из settings."""
    return AWGConfigBuilder(
        server_public_key=settings.WG_SERVER_PUBLIC_KEY,
        server_endpoint=settings.WG_SERVER_ENDPOINT,
        server_psk_enabled=settings.WG_PSK_ENABLED,
    )


@lru_cache(maxsize=1)
def get_key_cipher() -> Fernet:
    """
    DI: singleton Fernet cipher для шифрования private key перед хранением в БД.
    VPN_KEY_ENCRYPTION_KEY должен быть Fernet key (Fernet.generate_key()).
    """
    key = settings.VPN_KEY_ENCRYPTION_KEY
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VPN_KEY_ENCRYPTION_KEY not configured",
        )
    return Fernet(key.encode())


def encrypt_private_key(private_key: str, cipher: Fernet) -> bytes:
    """Зашифровать private_key (строка base64) → bytes (Fernet token)."""
    return cipher.encrypt(private_key.encode())


def decrypt_private_key(encrypted: bytes, cipher: Fernet) -> str:
    """Расшифровать Fernet token → private_key строка."""
    return cipher.decrypt(encrypted).decode()


# ── Pool Service DI ──────────────────────────────────────────────────────────

async def get_ip_pool_allocator(redis=Depends(get_redis)):
    """DI: IPPoolAllocator с Redis клиентом и настройками подсети."""
    from backend.services.vpn.ip_pool import IPPoolAllocator
    return IPPoolAllocator(redis, subnet=settings.VPN_POOL_SUBNET)


async def get_vpn_pool_service(
    db: AsyncSession = Depends(get_db),
    ip_pool=Depends(get_ip_pool_allocator),
    builder: AWGConfigBuilder = Depends(get_awg_config_builder),
):
    """DI: VPNPoolService — yield для корректного закрытия httpx.AsyncClient."""
    from backend.services.vpn.pool_service import VPNPoolService
    service = VPNPoolService(
        db=db,
        ip_pool=ip_pool,
        config_builder=builder,
        key_cipher=get_key_cipher(),
        wg_router_url=settings.WG_ROUTER_URL,
        wg_router_api_key=settings.WG_ROUTER_API_KEY,
    )
    try:
        yield service
    finally:
        await service.aclose()


# ── Kill Switch DI ───────────────────────────────────────────────────────────

async def get_killswitch_service():
    """DI: KillSwitchService (использует NoopCommandPublisher до TZ-03 merge)."""
    from backend.services.vpn.health_monitor import NoopCommandPublisher
    from backend.services.vpn.killswitch_service import KillSwitchService
    return KillSwitchService(publisher=NoopCommandPublisher())
