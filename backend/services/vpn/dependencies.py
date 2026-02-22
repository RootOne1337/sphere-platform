# backend/services/vpn/dependencies.py — TZ-06 SPLIT-1
# FastAPI Depends-фабрики для AWGConfigBuilder и Fernet cipher.
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from fastapi import HTTPException, status

from backend.core.config import settings
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
