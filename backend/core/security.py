# backend/core/security.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-1. Полная реализация JWT + bcrypt.
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from backend.core.config import settings


def hash_password(password: str) -> str:
    """bcrypt хэш пароля (cost=12)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Безопасная проверка пароля через bcrypt."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_token(token: str) -> str:
    """SHA-256 хэш токена для хранения в БД."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token_hash(token: str, token_hash: str) -> bool:
    """Безопасное сравнение хэша токена (constant-time)."""
    return hmac.compare_digest(hash_token(token), token_hash)


def create_access_token(subject: str, org_id: str, role: str) -> tuple[str, str]:
    """
    Создать JWT access token.
    Возвращает (token, jti).
    subject = user_id (JWT claim 'sub').
    """
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "org_id": org_id,
        "role": role,
        "jti": jti,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def decode_access_token(token: str) -> dict:
    """
    Декодировать и проверить JWT access token.
    Поднимает jwt.ExpiredSignatureError или jwt.InvalidTokenError при ошибках.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["sub", "jti", "type", "exp"]},
    )


def decode_expired_access_token(token: str) -> dict:
    """
    FIX-1.4: Декодировать токен БЕЗ проверки срока действия.
    Используется ИСКЛЮЧИТЕЛЬНО для logout — пользователь с протухшим
    access token должен мочь удалить refresh cookie и отозвать токен.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False, "require": ["sub", "jti", "type"]},
    )


def create_refresh_token() -> str:
    """Opaque random refresh token — хранится в БД как SHA-256 хэш."""
    return secrets.token_urlsafe(64)


def generate_api_key(env: str = "prod") -> tuple[str, str, str]:
    """
    Генерировать API ключ формата sphr_{env}_{random_32_hex}.
    Возвращает (raw_key, key_hash, key_prefix).
    raw_key показать пользователю ОДИН раз.
    """
    random_part = secrets.token_hex(32)
    raw_key = f"sphr_{env}_{random_part}"
    key_hash = hash_token(raw_key)
    key_prefix = raw_key[:14]  # "sphr_prod_a1b2" — для отображения
    return raw_key, key_hash, key_prefix
