# backend/core/security.py
# ВЛАДЕЛЕЦ: TZ-01 (auth). Этот файл создаётся здесь как stub для TZ-00.
# Полная реализация (bcrypt, JWT, TOTP) — TZ-01 SPLIT-1.
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from backend.core.config import settings


def hash_token(token: str) -> str:
    """SHA-256 хэш токена для хранения в БД."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token_hash(token: str, token_hash: str) -> bool:
    """Безопасное сравнение хэша токена."""
    return hmac.compare_digest(hash_token(token), token_hash)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Создать JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Декодировать и проверить JWT access token."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def generate_api_key() -> tuple[str, str]:
    """
    Генерировать API ключ.
    Возвращает (raw_key, key_hash) — raw_key показать пользователю ОДИН раз.
    """
    raw = f"sphr_{secrets.token_urlsafe(32)}"
    return raw, hash_token(raw)
