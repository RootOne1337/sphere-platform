# backend/services/auth_service.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-1. Login / Refresh / Logout logic.
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
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
from backend.database.credential_lookup import bind_credential_tenant, bind_user_login_tenant
from backend.database.tenant import bind_tenant_context
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
                f"mfa:state:v2:{state_token}",
                json.dumps({"user_id": str(user.id), "org_id": str(user.org_id)}),
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

        user = await self.db.get(User, rt.user_id, populate_existing=True)
        if not user or not user.is_active or user.org_id != rt.org_id:
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
        # Only server-written v2 state can carry the pre-auth tenant. Legacy
        # challenges require a new password step; no unscoped user lookup fallback.
        state_raw = await self.cache.get(f"mfa:state:v2:{state_token}")
        if not state_raw:
            raise InvalidTokenError("MFA session expired or invalid")
        try:
            state = json.loads(state_raw)
            if not isinstance(state, dict) or not all(isinstance(state.get(k), str) for k in ("user_id", "org_id")):
                raise ValueError("Invalid MFA identity")
            user_id, org_id = uuid.UUID(state["user_id"]), uuid.UUID(state["org_id"])
        except (ValueError, TypeError):
            raise InvalidTokenError("MFA session expired or invalid")
        await bind_tenant_context(self.db, str(org_id))
        user = await self.db.get(User, user_id, populate_existing=True)
        if not user or not user.is_active or not user.mfa_enabled or user.org_id != org_id:
            raise InvalidCredentialsError()

        from backend.services.mfa_service import MFAService
        mfa_svc = MFAService()
        if not mfa_svc.verify_totp(user.mfa_secret or "", totp_code):
            raise InvalidCredentialsError()

        # Issue only for the request that actually consumes the live challenge.
        # Another valid submission or TTL expiry may have removed it after GET.
        if await self.cache.delete(f"mfa:state:v2:{state_token}") != 1:
            raise InvalidTokenError("MFA session expired or already consumed")
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
        org_id = await bind_user_login_tenant(self.db, email)
        if org_id is None:
            return None
        result = await self.db.execute(
            select(User).where(User.email == email, User.org_id == org_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def _get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        org_id = await bind_credential_tenant(self.db, "user_refresh", token_hash)
        if org_id is None:
            return None
        # Refresh and logout consume the same row. Validate only after its owner
        # commits, and replace any preloaded ORM snapshot while acquiring the lock.
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash, RefreshToken.org_id == org_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
