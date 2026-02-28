# backend/services/auth_service.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-1. Login / Refresh / Logout logic.
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    TooManyAttemptsError,
)
from backend.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from backend.models.refresh_token import RefreshToken
from backend.models.user import User
from backend.services.cache_service import CacheService


class AuthService:
    def __init__(self, db: AsyncSession, cache: CacheService) -> None:
        self.db = db
        self.cache = cache

    # ── Login ────────────────────────────────────────────────────────────────

    async def login(self, email: str, password: str, ip: str) -> dict:
        """
        Аутентифицировать пользователя.
        Возвращает dict с access_token, refresh_token (и флагом mfa_required если MFA включён).

        Rate limit: 5 попыток с IP за 60 секунд.
        FIX-1.1: если MFA включён — токены НЕ выдаются; вместо этого возвращает mfa_required=True
                 + state_token для второго шага /auth/login/mfa.
        """
        allowed, _ = await self.cache.check_rate_limit(
            f"login:{ip}", window_seconds=60, max_requests=5
        )
        if not allowed:
            raise TooManyAttemptsError("Too many login attempts. Try again in 60 seconds.")

        user = await self._get_user_by_email(email)
        if not user or not user.is_active:
            raise InvalidCredentialsError()
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        # FIX-1.1: Проверка MFA ПЕРЕД выдачей токенов.
        if user.mfa_enabled:
            state_token = secrets.token_urlsafe(32)
            await self.cache.set(
                f"mfa:state:{state_token}",
                str(user.id),
                ttl=300,  # 5 минут на ввод TOTP
            )
            return {
                "mfa_required": True,
                "state_token": state_token,
            }

        return await self._issue_tokens(user)

    # ── Refresh ──────────────────────────────────────────────────────────────

    async def refresh(self, refresh_token_raw: str) -> dict:
        """
        Обновить пару токенов по refresh token.
        Rotation: старый refresh token отзывается, выпускается новый (SPLIT-1 security).
        """
        token_hash = hashlib.sha256(refresh_token_raw.encode()).hexdigest()

        rt = await self._get_refresh_token_by_hash(token_hash)
        if not rt:
            raise InvalidTokenError("Refresh token not found")
        if rt.revoked:
            raise InvalidTokenError("Refresh token already revoked")
        if rt.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError("Refresh token expired")

        user = await self.db.get(User, rt.user_id)
        if not user or not user.is_active:
            raise InvalidTokenError("User not found or inactive")

        # Rotate: отозвать старый, выпустить новый refresh token
        rt.revoked = True
        rt.revoked_at = datetime.now(timezone.utc)

        new_refresh_raw = create_refresh_token()
        new_refresh_hash = hashlib.sha256(new_refresh_raw.encode()).hexdigest()
        new_rt = RefreshToken(
            org_id=user.org_id,
            user_id=user.id,
            token_hash=new_refresh_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(
                days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
            ),
        )
        self.db.add(new_rt)

        access_token, _ = create_access_token(
            subject=str(user.id),
            org_id=str(user.org_id),
            role=user.role,
        )
        await self.db.commit()

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "refresh_token": new_refresh_raw,
            "user": user,
        }

    # ── Logout ───────────────────────────────────────────────────────────────

    async def logout(
        self,
        jti: str,
        token_exp: int,
        refresh_token_raw: str | None,
    ) -> None:
        """
        Инвалидировать access token (Redis blacklist) и refresh token (DB revoke).
        FIX-1.4: принимает jti/exp извлечённые через decode_expired_access_token,
                 чтобы пользователь с протухшим токеном мог выйти.
        """
        # Blacklist access token в Redis (до его истечения)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        remaining = token_exp - now_ts
        if remaining > 0:
            await self.cache.blacklist_token(jti, ttl_seconds=remaining)

        # Отозвать refresh token если передан
        if refresh_token_raw:
            token_hash = hashlib.sha256(refresh_token_raw.encode()).hexdigest()
            rt = await self._get_refresh_token_by_hash(token_hash)
            if rt and not rt.revoked:
                rt.revoked = True
                rt.revoked_at = datetime.now(timezone.utc)
                await self.db.commit()

    # ── MFA second-step login ────────────────────────────────────────────────

    async def complete_mfa_login(self, state_token: str, totp_code: str) -> dict:
        """
        Второй шаг MFA login.
        Проверяет TOTP-код из state_token (Redis) и выдаёт токены.
        """
        user_id_str = await self.cache.get(f"mfa:state:{state_token}")
        if not user_id_str:
            raise InvalidTokenError("MFA session expired or invalid")

        import uuid
        user = await self.db.get(User, uuid.UUID(user_id_str))
        if not user or not user.is_active:
            raise InvalidCredentialsError()

        from backend.services.mfa_service import MFAService
        mfa_svc = MFAService()
        if not mfa_svc.verify_totp(user.mfa_secret or "", totp_code):
            raise InvalidCredentialsError()

        # Очистить state и выдать токены
        await self.cache.delete(f"mfa:state:{state_token}")
        return await self._issue_tokens(user)

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _issue_tokens(self, user: User) -> dict:
        """Создать access + refresh токен для пользователя и сохранить RT в БД."""
        access_token, _ = create_access_token(
            subject=str(user.id),
            org_id=str(user.org_id),
            role=user.role,
        )
        refresh_token_raw = create_refresh_token()
        refresh_token_hash = hashlib.sha256(refresh_token_raw.encode()).hexdigest()

        rt = RefreshToken(
            org_id=user.org_id,
            user_id=user.id,
            token_hash=refresh_token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(
                days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
            ),
        )
        self.db.add(rt)

        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "refresh_token": refresh_token_raw,
            "user": user,
        }

    async def _get_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def _get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()
