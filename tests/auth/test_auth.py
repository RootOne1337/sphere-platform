# tests/auth/test_auth.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-1/2/3/4/5. Тесты JWT login / refresh / logout / RBAC.
# Unit tests: чистые функции (security, rbac, services с mock-DB).
# Integration tests: HTTP endpoints через FastAPI TestClient с mocked services.
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

from backend.core.config import settings
from backend.core.security import create_access_token, hash_password, verify_password
from backend.database.redis_client import get_redis
from backend.main import app


# ── HTTP test client (no real DB — services are mocked) ─────────────────────

@pytest_asyncio.fixture
async def mock_auth_client(mock_redis: FakeRedis) -> AsyncClient:
    """
    HTTP клиент с FakeRedis для blacklist/rate-limit.
    Сервисный слой мокируется per-test через app.dependency_overrides.
    """
    async def _override_get_redis():
        return mock_redis

    app.dependency_overrides[get_redis] = _override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ── Unit tests: security functions ───────────────────────────────────────────

class TestSecurityFunctions:
    """Чистые unit-тесты без БД и Redis."""

    def test_hash_and_verify_password(self):
        """bcrypt hash и verify работают корректно."""
        raw = "SuperSecret42!"
        hashed = hash_password(raw)
        assert hashed != raw
        assert verify_password(raw, hashed)
        assert not verify_password("WrongPassword", hashed)

    def test_create_access_token_returns_tuple(self):
        """create_access_token возвращает кортеж (token, jti)."""
        token, jti = create_access_token(
            subject="user-uuid-123",
            org_id="org-uuid-456",
            role="viewer",
        )
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert len(jti) == 36  # UUID4

    def test_decode_access_token_claims(self):
        """Декодированный токен содержит корректные claims."""
        from backend.core.security import decode_access_token
        token, jti = create_access_token(
            subject="test-sub", org_id="test-org", role="admin"
        )
        payload = decode_access_token(token)
        assert payload["sub"] == "test-sub"
        assert payload["org_id"] == "test-org"
        assert payload["role"] == "admin"
        assert payload["jti"] == jti
        assert payload["type"] == "access"

    def test_expired_token_raises(self):
        """Просроченный токен → jwt.ExpiredSignatureError."""
        from backend.core.security import decode_access_token
        expired_payload = {
            "sub": "user-1",
            "jti": str(uuid.uuid4()),
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(
            expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(expired_token)

    def test_decode_expired_token_works(self):
        """decode_expired_access_token работает с протухшим токеном (FIX-1.4)."""
        from backend.core.security import decode_expired_access_token
        expired_payload = {
            "sub": "user-1",
            "jti": str(uuid.uuid4()),
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(
            expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        decoded = decode_expired_access_token(expired_token)
        assert decoded["sub"] == "user-1"

    def test_jwt_compact_form(self):
        """JWT — компактная JWS форма с 3 сегментами (header.payload.signature)."""
        token, _ = create_access_token(
            subject=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role="viewer"
        )
        assert len(token.split(".")) == 3, "JWT должен быть в compact JWS формате"

    def test_create_refresh_token_opaque(self):
        """Refresh token опаковый (URL-safe random string)."""
        from backend.core.security import create_refresh_token
        rt1 = create_refresh_token()
        rt2 = create_refresh_token()
        assert rt1 != rt2
        assert len(rt1) > 32

    def test_generate_api_key_format(self):
        """API ключ имеет формат sphr_{env}_{random}."""
        from backend.core.security import generate_api_key
        raw, key_hash, prefix = generate_api_key("prod")
        assert raw.startswith("sphr_prod_")
        assert len(key_hash) == 64  # SHA-256 hex
        assert raw.startswith(prefix)


# ── RBAC unit tests ───────────────────────────────────────────────────────────

class TestRBAC:
    """Тесты матрицы разрешений (SPLIT-3)."""

    def test_viewer_can_read_devices(self):
        from backend.core.rbac import has_permission
        assert has_permission("viewer", "device:read") is True

    def test_viewer_cannot_write_devices(self):
        from backend.core.rbac import has_permission
        assert has_permission("viewer", "device:write") is False

    def test_viewer_cannot_delete_devices(self):
        from backend.core.rbac import has_permission
        assert has_permission("viewer", "device:delete") is False

    def test_device_manager_can_write(self):
        from backend.core.rbac import has_permission
        assert has_permission("device_manager", "device:write") is True

    def test_device_manager_cannot_delete(self):
        from backend.core.rbac import has_permission
        assert has_permission("device_manager", "device:delete") is False

    def test_org_admin_can_delete_devices(self):
        from backend.core.rbac import has_permission
        assert has_permission("org_admin", "device:delete") is True

    def test_org_owner_can_change_user_role(self):
        from backend.core.rbac import has_permission
        assert has_permission("org_owner", "user:write") is True

    def test_org_admin_cannot_change_user_role(self):
        from backend.core.rbac import has_permission
        assert has_permission("org_admin", "user:write") is False

    def test_super_admin_has_all_permissions(self):
        from backend.core.rbac import PERMISSIONS, has_permission
        for perm in PERMISSIONS:
            assert has_permission("super_admin", perm) is True, (
                f"super_admin should have {perm}"
            )

    def test_unknown_role_has_no_permissions(self):
        from backend.core.rbac import has_permission
        assert has_permission("unknown_role", "device:read") is False

    def test_unknown_permission_returns_false(self):
        from backend.core.rbac import has_permission
        assert has_permission("org_owner", "nonexistent:action") is False

    def test_script_runner_can_execute_scripts(self):
        from backend.core.rbac import has_permission
        assert has_permission("script_runner", "script:execute") is True

    def test_script_runner_cannot_write_scripts(self):
        from backend.core.rbac import has_permission
        assert has_permission("script_runner", "script:write") is False

    def test_viewer_can_read_monitoring(self):
        from backend.core.rbac import has_permission
        assert has_permission("viewer", "monitoring:read") is True


# ── AuthService unit tests (mocked DB + Redis) ────────────────────────────────

class TestAuthService:
    """AuthService логика тестируется с mock DB и mock CacheService."""

    @pytest.mark.asyncio
    async def test_login_correct_credentials_issues_tokens(self):
        """Верные учётные данные → access_token + refresh_token в результате."""
        from backend.services.auth_service import AuthService

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.org_id = uuid.uuid4()
        mock_user.email = "user@test.com"
        mock_user.password_hash = hash_password("CorrectPass123!")
        mock_user.is_active = True
        mock_user.mfa_enabled = False
        mock_user.role = "viewer"

        mock_db = AsyncMock()
        mock_cache = AsyncMock()
        mock_cache.check_rate_limit = AsyncMock(return_value=(True, 1))

        svc = AuthService.__new__(AuthService)
        svc.db = mock_db
        svc.cache = mock_cache

        # FIX: mock _issue_tokens completely to avoid instantiating RefreshToken ORM object
        # (would trigger SQLAlchemy mapper config with TZ-02/04 unresolved stubs)
        _fake_tokens = {
            "access_token": "at.signed.token",
            "token_type": "bearer",
            "expires_in": 1800,
            "refresh_token": "raw-refresh-token",
        }
        with patch.object(svc, "_get_user_by_email", return_value=mock_user):
            with patch.object(svc, "_issue_tokens", new=AsyncMock(return_value=_fake_tokens)):
                result = await svc.login("user@test.com", "CorrectPass123!", "127.0.0.1")

        assert "access_token" in result
        assert "refresh_token" in result

    @pytest.mark.asyncio
    async def test_login_wrong_password_raises_invalid_credentials(self):
        """Неверный пароль → InvalidCredentialsError."""
        from backend.core.exceptions import InvalidCredentialsError
        from backend.services.auth_service import AuthService

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.mfa_enabled = False
        mock_user.password_hash = hash_password("RealPassword123!")

        mock_db = AsyncMock()
        mock_cache = AsyncMock()
        mock_cache.check_rate_limit = AsyncMock(return_value=(True, 1))

        svc = AuthService.__new__(AuthService)
        svc.db = mock_db
        svc.cache = mock_cache

        with patch.object(svc, "_get_user_by_email", return_value=mock_user):
            with pytest.raises(InvalidCredentialsError):
                await svc.login("user@test.com", "WrongPassword!", "127.0.0.1")

    @pytest.mark.asyncio
    async def test_login_rate_limit_exceeded_raises_too_many_attempts(self):
        """Превышен rate limit → TooManyAttemptsError."""
        from backend.core.exceptions import TooManyAttemptsError
        from backend.services.auth_service import AuthService

        mock_db = AsyncMock()
        mock_cache = AsyncMock()
        mock_cache.check_rate_limit = AsyncMock(return_value=(False, 6))

        svc = AuthService.__new__(AuthService)
        svc.db = mock_db
        svc.cache = mock_cache

        with pytest.raises(TooManyAttemptsError):
            await svc.login("user@test.com", "Pass123!", "1.2.3.4")

    @pytest.mark.asyncio
    async def test_login_mfa_enabled_returns_state_token(self):
        """MFA включён → возвращает mfa_required=True + state_token (FIX-1.1)."""
        from backend.services.auth_service import AuthService

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.is_active = True
        mock_user.mfa_enabled = True
        mock_user.password_hash = hash_password("Pass123!")

        mock_db = AsyncMock()
        mock_cache = AsyncMock()
        mock_cache.check_rate_limit = AsyncMock(return_value=(True, 1))
        mock_cache.set = AsyncMock()

        svc = AuthService.__new__(AuthService)
        svc.db = mock_db
        svc.cache = mock_cache

        with patch.object(svc, "_get_user_by_email", return_value=mock_user):
            result = await svc.login("user@test.com", "Pass123!", "127.0.0.1")

        assert result["mfa_required"] is True
        assert "state_token" in result
        # ВАЖНО: access_token НЕ должен быть в ответе при MFA (FIX-1.1)
        assert "access_token" not in result

    @pytest.mark.asyncio
    async def test_logout_blacklists_jti(self):
        """Logout добавляет JTI в Redis blacklist."""
        from backend.services.auth_service import AuthService

        mock_db = AsyncMock()
        mock_cache = AsyncMock()
        mock_cache.blacklist_token = AsyncMock()

        svc = AuthService.__new__(AuthService)
        svc.db = mock_db
        svc.cache = mock_cache

        future_exp = int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp())
        with patch.object(svc, "_get_refresh_token_by_hash", return_value=None):
            await svc.logout(jti="test-jti-123", token_exp=future_exp, refresh_token_raw=None)

        mock_cache.blacklist_token.assert_called_once()
        call_args = mock_cache.blacklist_token.call_args
        assert call_args[0][0] == "test-jti-123"
        assert call_args[1]["ttl_seconds"] > 0


# ── Integration tests: HTTP endpoints с mocked services ─────────────────────

class TestLoginEndpoint:
    """Тесты HTTP /auth/login с моком AuthService."""

    @pytest.mark.asyncio
    async def test_login_success_returns_token_and_cookie(
        self, mock_auth_client: AsyncClient
    ):
        """POST /auth/login → 200 + access_token в теле + refresh_token в HTTPOnly cookie."""
        from backend.core.dependencies import get_auth_service

        mock_svc = AsyncMock()
        mock_svc.login = AsyncMock(return_value={
            "access_token": "access.jwt.token",
            "token_type": "bearer",
            "expires_in": 1800,
            "refresh_token": "raw-refresh-opaque-token",
        })
        app.dependency_overrides[get_auth_service] = lambda: mock_svc

        resp = await mock_auth_client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.com", "password": "SecurePass123!"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        # Refresh token выставлен как HTTPOnly cookie (не в теле ответа)
        assert "refresh_token" in resp.cookies

        app.dependency_overrides.pop(get_auth_service, None)

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(
        self, mock_auth_client: AsyncClient
    ):
        """Неверный пароль → 401."""
        from backend.core.dependencies import get_auth_service
        from backend.core.exceptions import InvalidCredentialsError

        mock_svc = AsyncMock()
        mock_svc.login = AsyncMock(side_effect=InvalidCredentialsError())
        app.dependency_overrides[get_auth_service] = lambda: mock_svc

        resp = await mock_auth_client.post(
            "/api/v1/auth/login",
            json={"email": "x@test.com", "password": "Bad123456!"},
        )
        assert resp.status_code == 401

        app.dependency_overrides.pop(get_auth_service, None)

    @pytest.mark.asyncio
    async def test_login_rate_limit_returns_429(self, mock_auth_client: AsyncClient):
        """Rate limit exceeded → 429."""
        from backend.core.dependencies import get_auth_service
        from backend.core.exceptions import TooManyAttemptsError

        mock_svc = AsyncMock()
        mock_svc.login = AsyncMock(
            side_effect=TooManyAttemptsError("Too many login attempts. Try again in 60 seconds.")
        )
        app.dependency_overrides[get_auth_service] = lambda: mock_svc

        resp = await mock_auth_client.post(
            "/api/v1/auth/login",
            json={"email": "x@test.com", "password": "Pass123456!"},
        )
        assert resp.status_code == 429

        app.dependency_overrides.pop(get_auth_service, None)

    @pytest.mark.asyncio
    async def test_login_mfa_required_response(self, mock_auth_client: AsyncClient):
        """MFA включён → возвращает mfa_required=True вместо токена."""
        from backend.core.dependencies import get_auth_service

        mock_svc = AsyncMock()
        mock_svc.login = AsyncMock(return_value={
            "mfa_required": True,
            "state_token": "some-state-token-value",
        })
        app.dependency_overrides[get_auth_service] = lambda: mock_svc

        resp = await mock_auth_client.post(
            "/api/v1/auth/login",
            json={"email": "mfa@test.com", "password": "MFAPass123!"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mfa_required"] is True
        assert "state_token" in data
        assert "access_token" not in data

        app.dependency_overrides.pop(get_auth_service, None)


class TestLogoutEndpoint:
    @pytest.mark.asyncio
    async def test_logout_without_token_returns_204(self, mock_auth_client: AsyncClient):
        """Logout без токена → 204 (клиент всегда успешно разлогинивается)."""
        from backend.core.dependencies import get_auth_service

        mock_svc = AsyncMock()
        mock_svc.logout = AsyncMock()
        app.dependency_overrides[get_auth_service] = lambda: mock_svc

        resp = await mock_auth_client.post("/api/v1/auth/logout")
        assert resp.status_code == 204


class TestRefreshEndpoint:
    @pytest.mark.asyncio
    async def test_refresh_without_cookie_returns_401(self, mock_auth_client: AsyncClient):
        """Refresh без cookie → 401."""
        from backend.core.dependencies import get_auth_service

        mock_svc = AsyncMock()
        app.dependency_overrides[get_auth_service] = lambda: mock_svc

        resp = await mock_auth_client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401


class TestMeEndpoint:
    @pytest.mark.asyncio
    async def test_me_without_token_returns_401(self, mock_auth_client: AsyncClient):
        """GET /auth/me без токена → 401."""
        resp = await mock_auth_client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_blacklisted_token_returns_401(
        self, mock_auth_client: AsyncClient, mock_redis: FakeRedis
    ):
        """Blacklisted JWT → 401 с сообщением 'Token revoked'."""
        user_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())
        token, jti = create_access_token(subject=user_id, org_id=org_id, role="viewer")

        # Добавляем JTI в FakeRedis blacklist
        await mock_redis.set(f"jwt:blacklist:{jti}", "1", ex=3600)

        # FIX: patch cache_service.get_redis to return FakeRedis so CacheService uses it.
        # get_current_user instantiates CacheService() directly (not via DI), so
        # app.dependency_overrides[get_redis] does NOT affect CacheService method calls.
        async def _fake_get_redis():
            return mock_redis

        with patch("backend.services.cache_service.get_redis", _fake_get_redis):
            resp = await mock_auth_client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        assert "revoked" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_me_with_invalid_token_returns_401(self, mock_auth_client: AsyncClient):
        """Невалидный JWT → 401."""
        resp = await mock_auth_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer this.is.garbage"},
        )
        assert resp.status_code == 401
