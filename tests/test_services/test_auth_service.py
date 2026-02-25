# tests/test_services/test_auth_service.py
# TZ-01 SPLIT-1: Unit-тесты для AuthService (login, refresh, logout, MFA).
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    TooManyAttemptsError,
)
from backend.services.auth_service import AuthService
from backend.services.cache_service import CacheService


def _make_user(
    *,
    active: bool = True,
    mfa_enabled: bool = False,
    password_hash: str = "hashed_pw",
    role: str = "admin",
) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.org_id = uuid.uuid4()
    user.email = "user@example.com"
    user.is_active = active
    user.mfa_enabled = mfa_enabled
    user.mfa_secret = "JBSWY3DPEHPK3PXP" if mfa_enabled else None
    user.password_hash = password_hash
    user.role = role
    user.last_login_at = None
    return user


def _make_rt(*, revoked: bool = False, expired: bool = False) -> MagicMock:
    rt = MagicMock()
    rt.user_id = uuid.uuid4()
    rt.revoked = revoked
    rt.revoked_at = None
    rt.expires_at = (
        datetime.now(timezone.utc) - timedelta(days=1)
        if expired
        else datetime.now(timezone.utc) + timedelta(days=30)
    )
    return rt


def _make_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.get = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_cache():
    cache = AsyncMock(spec=CacheService)
    cache.check_rate_limit = AsyncMock(return_value=(True, 1))
    cache.set = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.delete = AsyncMock()
    cache.blacklist_token = AsyncMock()
    return cache


class TestLogin:
    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises(self):
        db = _make_db()
        cache = _make_cache()
        cache.check_rate_limit.return_value = (False, 10)
        svc = AuthService(db, cache)

        with pytest.raises(TooManyAttemptsError):
            await svc.login("user@example.com", "pw", "1.2.3.4")

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        db = _make_db()
        cache = _make_cache()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        svc = AuthService(db, cache)

        with pytest.raises(InvalidCredentialsError):
            await svc.login("no@one.com", "pw", "1.2.3.4")

    @pytest.mark.asyncio
    async def test_inactive_user_raises(self):
        db = _make_db()
        cache = _make_cache()
        user = _make_user(active=False)
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=user)
        svc = AuthService(db, cache)

        with pytest.raises(InvalidCredentialsError):
            await svc.login("user@example.com", "pw", "1.2.3.4")

    @pytest.mark.asyncio
    async def test_wrong_password_raises(self):
        db = _make_db()
        cache = _make_cache()
        user = _make_user(password_hash="hashed")
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=user)
        svc = AuthService(db, cache)

        with patch("backend.services.auth_service.verify_password", return_value=False):
            with pytest.raises(InvalidCredentialsError):
                await svc.login("user@example.com", "wrong", "1.2.3.4")

    @pytest.mark.asyncio
    async def test_successful_login_returns_tokens(self):
        db = _make_db()
        cache = _make_cache()
        user = _make_user()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=user)
        svc = AuthService(db, cache)

        with patch("backend.services.auth_service.verify_password", return_value=True):
            result = await svc.login("user@example.com", "correct", "1.2.3.4")

        assert "access_token" in result
        assert result["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_mfa_enabled_returns_state_token(self):
        db = _make_db()
        cache = _make_cache()
        user = _make_user(mfa_enabled=True)
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=user)
        svc = AuthService(db, cache)

        with patch("backend.services.auth_service.verify_password", return_value=True):
            result = await svc.login("user@example.com", "correct", "1.2.3.4")

        assert result.get("mfa_required") is True
        assert "state_token" in result
        cache.set.assert_called_once()


class TestRefresh:
    @pytest.mark.asyncio
    async def test_token_not_found_raises(self):
        db = _make_db()
        cache = _make_cache()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        svc = AuthService(db, cache)

        with pytest.raises(InvalidTokenError):
            await svc.refresh("nonexistent_raw_token")

    @pytest.mark.asyncio
    async def test_revoked_token_raises(self):
        db = _make_db()
        cache = _make_cache()
        rt = _make_rt(revoked=True)
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=rt)
        svc = AuthService(db, cache)

        with pytest.raises(InvalidTokenError, match="revoked"):
            await svc.refresh("some_token")

    @pytest.mark.asyncio
    async def test_expired_token_raises(self):
        db = _make_db()
        cache = _make_cache()
        rt = _make_rt(expired=True)
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=rt)
        svc = AuthService(db, cache)

        with pytest.raises(InvalidTokenError, match="expired"):
            await svc.refresh("some_token")

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        db = _make_db()
        cache = _make_cache()
        rt = _make_rt()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=rt)
        db.get.return_value = None
        svc = AuthService(db, cache)

        with pytest.raises(InvalidTokenError, match="User not found"):
            await svc.refresh("some_token")

    @pytest.mark.asyncio
    async def test_successful_refresh_returns_new_tokens(self):
        db = _make_db()
        cache = _make_cache()
        rt = _make_rt()
        user = _make_user()
        rt.user_id = user.id

        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=rt)
        db.get.return_value = user
        svc = AuthService(db, cache)

        result = await svc.refresh("raw_rt_value")
        assert "access_token" in result
        assert "refresh_token" in result
        assert rt.revoked is True


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_blacklists_access_token(self):
        db = _make_db()
        cache = _make_cache()
        svc = AuthService(db, cache)

        future_exp = int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp())
        await svc.logout(jti="some-jti", token_exp=future_exp, refresh_token_raw=None)
        cache.blacklist_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_logout_with_expired_access_skips_blacklist(self):
        """Если токен уже истёк, remaining <= 0 — не добавляем в blacklist."""
        db = _make_db()
        cache = _make_cache()
        svc = AuthService(db, cache)

        past_exp = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())
        await svc.logout(jti="jti", token_exp=past_exp, refresh_token_raw=None)
        cache.blacklist_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_logout_revokes_refresh_token(self):
        db = _make_db()
        cache = _make_cache()
        rt = _make_rt(revoked=False)
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=rt)
        svc = AuthService(db, cache)

        future_exp = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())
        await svc.logout(jti="jti", token_exp=future_exp, refresh_token_raw="raw_refresh")
        assert rt.revoked is True
        db.commit.assert_called()


class TestCompleteMfaLogin:
    @pytest.mark.asyncio
    async def test_invalid_state_raises(self):
        db = _make_db()
        cache = _make_cache()
        cache.get.return_value = None
        svc = AuthService(db, cache)

        with pytest.raises(InvalidTokenError, match="MFA session"):
            await svc.complete_mfa_login("bad_token", "123456")

    @pytest.mark.asyncio
    async def test_invalid_totp_raises(self):
        db = _make_db()
        cache = _make_cache()
        user = _make_user(mfa_enabled=True)
        cache.get.return_value = str(user.id)
        db.get.return_value = user
        svc = AuthService(db, cache)

        with patch("backend.services.mfa_service.MFAService.verify_totp", return_value=False):
            with pytest.raises(InvalidCredentialsError):
                await svc.complete_mfa_login("valid_state", "000000")

    @pytest.mark.asyncio
    async def test_valid_totp_returns_tokens(self):
        db = _make_db()
        cache = _make_cache()
        user = _make_user(mfa_enabled=True)
        cache.get.return_value = str(user.id)
        db.get.return_value = user
        svc = AuthService(db, cache)

        with patch("backend.services.mfa_service.MFAService.verify_totp", return_value=True):
            result = await svc.complete_mfa_login("valid_state", "123456")

        assert "access_token" in result
        cache.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_mfa_user_not_found_raises(self):
        """complete_mfa_login: user_id в Redis есть, но User не найден в DB."""
        db = _make_db()
        cache = _make_cache()
        cache.get.return_value = str(uuid.uuid4())
        db.get.return_value = None
        svc = AuthService(db, cache)

        with pytest.raises(InvalidCredentialsError):
            await svc.complete_mfa_login("valid_state", "123456")
