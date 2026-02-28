# backend/api/v1/auth/router.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-1/2/4. Auth endpoints: login, refresh, logout, me, MFA, API keys.
from __future__ import annotations

import uuid
from typing import Union

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_auth_service, get_current_user
from backend.core.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    TooManyAttemptsError,
)
from backend.core.security import decode_expired_access_token
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.auth import (
    APIKeyCreatedResponse,
    APIKeyResponse,
    CreateAPIKeyRequest,
    LoginRequest,
    MFALoginRequest,
    MFARequiredResponse,
    MFASetupResponse,
    MFAVerifySetupRequest,
    TokenResponse,
    UserResponse,
)
from backend.services.auth_service import AuthService
from backend.services.cache_service import CacheService
from backend.services.mfa_service import MFAService

router = APIRouter(prefix="/auth", tags=["auth"])

bearer_scheme = HTTPBearer(auto_error=False)


REFRESH_COOKIE_NAME = "refresh_token"


def _cookie_settings() -> dict:
    """Cookie настройки с учётом окружения (Secure через config)."""
    return {
        "httponly": True,
        "secure": True, # Force True for Serveo HTTPS tunnel
        "samesite": "none", # Required for cross-site cookies over HTTPS tunnel
        "path": "/",
        "max_age": 7 * 24 * 3600,  # 7 дней
    }

mfa_service = MFAService()


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=Union[TokenResponse, MFARequiredResponse],
    summary="Login: получить access token + refresh cookie",
)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
):
    """
    Аутентификация пользователя.
    - Если MFA отключён: возвращает access_token + устанавливает HTTPOnly refresh_token cookie.
    - Если MFA включён: возвращает mfa_required=True + state_token (не выдаёт JWT до подтверждения).
    Rate limit: 5 попыток с IP за 60 секунд → 429.
    """
    ip = request.client.host if request.client else "unknown"
    try:
        result = await auth_svc.login(body.email, body.password, ip)
    except TooManyAttemptsError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if result.get("mfa_required"):
        return MFARequiredResponse(state_token=result["state_token"])

    # Refresh token — cookie + тело ответа (dual mode для tunnel/proxy совместимости)
    response.set_cookie(REFRESH_COOKIE_NAME, result["refresh_token"], **_cookie_settings())
    user_resp = None
    if result.get("user"):
        from backend.schemas.auth import UserResponse
        user_resp = UserResponse.model_validate(result["user"])
    return TokenResponse(
        access_token=result["access_token"],
        token_type="bearer",
        expires_in=result["expires_in"],
        refresh_token=result["refresh_token"],
        user=user_resp,
    )


@router.post(
    "/login/mfa",
    response_model=TokenResponse,
    summary="Второй шаг MFA login: подтвердить TOTP-код",
)
async def login_mfa(
    body: MFALoginRequest,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
):
    """
    Второй шаг MFA: принимает state_token (из /login) и 6-значный TOTP-код.
    При успехе выдаёт access_token + refresh_token cookie.
    """
    try:
        result = await auth_svc.complete_mfa_login(body.state_token, body.code)
    except (InvalidTokenError, InvalidCredentialsError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc) or "Invalid MFA code or session expired",
        )

    response.set_cookie(REFRESH_COOKIE_NAME, result["refresh_token"], **_cookie_settings())
    user_resp = None
    if result.get("user"):
        from backend.schemas.auth import UserResponse
        user_resp = UserResponse.model_validate(result["user"])
    return TokenResponse(
        access_token=result["access_token"],
        token_type="bearer",
        expires_in=result["expires_in"],
        refresh_token=result["refresh_token"],
        user=user_resp,
    )


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновить access token по refresh cookie или header",
)
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    auth_svc: AuthService = Depends(get_auth_service),
):
    """
    Обновить access token.
    Источники refresh_token (приоритет):
    1. HTTPOnly cookie (стандартный путь)
    2. Header X-Refresh-Token (fallback для tunnel/proxy)
    3. JSON body {"refresh_token": "..."} (fallback)
    Ротация: старый refresh token инвалидируется, выпускается новый.
    """
    token = refresh_token

    # Fallback 1: header X-Refresh-Token
    if not token:
        token = request.headers.get("x-refresh-token")

    # Fallback 2: JSON body
    if not token:
        try:
            body = await request.json()
            token = body.get("refresh_token") if isinstance(body, dict) else None
        except Exception:
            pass

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token provided",
        )
    try:
        result = await auth_svc.refresh(token)
    except InvalidTokenError as exc:
        response.delete_cookie(REFRESH_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    response.set_cookie(REFRESH_COOKIE_NAME, result["refresh_token"], **_cookie_settings())
    user_resp = None
    if result.get("user"):
        from backend.schemas.auth import UserResponse
        user_resp = UserResponse.model_validate(result["user"])
    return TokenResponse(
        access_token=result["access_token"],
        token_type="bearer",
        expires_in=result["expires_in"],
        refresh_token=result["refresh_token"],
        user=user_resp,
    )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    response_model=None,
    summary="Logout: инвалидировать токены",
)
async def logout(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    auth_svc: AuthService = Depends(get_auth_service),
):
    """
    Logout: помещает access token в Redis blacklist + отзывает refresh token в БД.
    FIX-1.4: использует decode_expired_access_token — работает даже с просроченным токеном.
    Всегда удаляет refresh_token cookie независимо от результата.
    """
    if credentials:
        try:
            payload = decode_expired_access_token(credentials.credentials)
            await auth_svc.logout(
                jti=payload["jti"],
                token_exp=payload["exp"],
                refresh_token_raw=refresh_token,
            )
        except (jwt.InvalidTokenError, KeyError):
            # Невалидный токен — продолжаем удалять cookie
            pass

    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Информация о текущем пользователе",
)
async def me(current_user: User = Depends(get_current_user)):
    """Получить профиль текущего аутентифицированного пользователя."""
    return current_user


# ── MFA Setup (SPLIT-2) ───────────────────────────────────────────────────────

@router.post(
    "/mfa/setup",
    response_model=MFASetupResponse,
    summary="SPLIT-2: Шаг 1 — Сгенерировать TOTP QR-код",
)
async def mfa_setup(
    current_user: User = Depends(get_current_user),
):
    """
    Шаг 1 MFA setup: сгенерировать TOTP секрет и QR-код.
    Секрет временно сохраняется в Redis (5 минут) — до подтверждения через /mfa/verify-setup.
    """
    cache = CacheService()
    secret = mfa_service.generate_totp_secret()
    uri = mfa_service.get_totp_uri(secret, current_user.email)
    qr_base64 = mfa_service.generate_qr_code(uri)

    # Временно сохранить pending секрет в Redis
    await cache.set(f"mfa:pending:{current_user.id}", secret, ttl=300)

    return MFASetupResponse(qr_code=qr_base64, secret=secret)


@router.post(
    "/mfa/verify-setup",
    summary="SPLIT-2: Шаг 2 — Подтвердить TOTP-код и включить MFA",
)
async def mfa_verify_setup(
    body: MFAVerifySetupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Шаг 2 MFA setup: проверить отсканированный QR-код и активировать MFA.
    Без этого подтверждения MFA не включается — QR-код может быть неверно отсканирован.
    """
    cache = CacheService()
    pending_secret = await cache.get(f"mfa:pending:{current_user.id}")
    if not pending_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup session expired. Please restart setup.",
        )

    if not mfa_service.verify_totp(pending_secret, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )

    # Активировать MFA
    current_user.mfa_secret = pending_secret
    current_user.mfa_enabled = True
    await cache.delete(f"mfa:pending:{current_user.id}")
    await db.commit()

    return {"message": "MFA enabled successfully"}


@router.delete(
    "/mfa",
    response_model=None,
    summary="SPLIT-2: Отключить MFA",
)
async def mfa_disable(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отключить TOTP MFA для текущего пользователя."""
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── API Keys (SPLIT-4) ────────────────────────────────────────────────────────

@router.post(
    "/api-keys",
    response_model=APIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="SPLIT-4: Создать API ключ",
)
async def create_api_key(
    body: CreateAPIKeyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Создать новый API ключ для машинных интеграций.
    raw_key показывается ОДИН РАЗ в ответе — после этого получить его невозможно.
    """
    from backend.services.api_key_service import APIKeyService
    svc = APIKeyService(db)
    api_key, raw_key = await svc.create_api_key(
        org_id=current_user.org_id,
        name=body.name,
        permissions=body.permissions,
        created_by=current_user.id,
        expires_at=body.expires_at,
        key_type=body.key_type,
    )
    await db.commit()

    return APIKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        raw_key=raw_key,
        permissions=api_key.permissions,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


@router.get(
    "/api-keys",
    response_model=list[APIKeyResponse],
    summary="SPLIT-4: Список API ключей",
)
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список активных API ключей для org текущего пользователя."""
    from backend.services.api_key_service import APIKeyService
    svc = APIKeyService(db)
    keys = await svc.list_for_org(current_user.org_id)
    return keys


@router.delete(
    "/api-keys/{key_id}",
    response_model=None,
    summary="SPLIT-4: Отозвать API ключ",
)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отозвать (деактивировать) API ключ."""
    from backend.services.api_key_service import APIKeyService
    svc = APIKeyService(db)
    revoked = await svc.revoke(key_id, current_user.org_id)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
