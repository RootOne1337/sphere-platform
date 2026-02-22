# tests/vpn/conftest.py — TZ-06 SPLIT-1 фикстуры
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from backend.services.vpn.awg_config import AWGConfigBuilder


@pytest.fixture
def awg_builder() -> AWGConfigBuilder:
    """AWGConfigBuilder с тестовыми параметрами сервера."""
    return AWGConfigBuilder(
        server_public_key="dGVzdF9zZXJ2ZXJfcHVibGljX2tleV9iYXNlNjQ=",
        server_endpoint="vpn.test.local:51820",
        dns="1.1.1.1, 8.8.8.8",
        server_psk_enabled=True,
    )


@pytest.fixture
def fernet_key() -> str:
    """Валидный Fernet key для тестов шифрования."""
    return Fernet.generate_key().decode()


@pytest.fixture
def fernet_cipher(fernet_key: str) -> Fernet:
    """Fernet cipher для тестов."""
    return Fernet(fernet_key.encode())
