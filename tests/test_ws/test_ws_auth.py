# tests/test_ws/test_ws_auth.py
"""
Unit-тесты для authenticate_ws_token — WS авторизация по JWT и API-ключу.

Покрывает критический кейс: устройства получают JWT с role="device"
и sub=device_id (не user_id). Функция должна корректно искать
в таблице devices, а не users.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.api.ws.android.router import authenticate_ws_token
from backend.core.security import create_access_token

# Мокаем CacheService.is_token_blacklisted — в тестах нет реального Redis
_BLACKLIST_PATCH = "backend.services.cache_service.CacheService.is_token_blacklisted"


# ---------------------------------------------------------------------------
# Тест: JWT с role="device" → устройство найдено → возвращает принципал с org_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(_BLACKLIST_PATCH, new_callable=AsyncMock, return_value=False)
async def test_device_jwt_returns_device_principal(
    _mock_bl, db_session, test_device, test_org,
):
    """JWT с role='device' и sub=device_id должен вернуть принципал с org_id устройства."""
    token, _ = create_access_token(
        subject=str(test_device.id),
        org_id=str(test_org.id),
        role="device",
    )
    principal = await authenticate_ws_token(token, db_session)

    assert hasattr(principal, "org_id")
    assert str(principal.org_id) == str(test_org.id)


# ---------------------------------------------------------------------------
# Тест: JWT с role="device" → устройства нет в БД → HTTPException 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(_BLACKLIST_PATCH, new_callable=AsyncMock, return_value=False)
async def test_device_jwt_unknown_device_raises(_mock_bl, db_session, test_org):
    """JWT с role='device' и несуществующим sub должен вернуть 401."""
    fake_device_id = str(uuid.uuid4())
    token, _ = create_access_token(
        subject=fake_device_id,
        org_id=str(test_org.id),
        role="device",
    )
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_ws_token(token, db_session)

    assert exc_info.value.status_code == 401
    assert "Device not found" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Тест: JWT с role="admin" (обычный пользователь) → User lookup → ok
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(_BLACKLIST_PATCH, new_callable=AsyncMock, return_value=False)
async def test_user_jwt_returns_user(_mock_bl, db_session, test_user, test_org):
    """Обычный JWT (role='admin') должен искать в users и вернуть User объект."""
    token, _ = create_access_token(
        subject=str(test_user.id),
        org_id=str(test_org.id),
        role="admin",
    )
    principal = await authenticate_ws_token(token, db_session)

    assert hasattr(principal, "org_id")
    assert str(principal.org_id) == str(test_org.id)


# ---------------------------------------------------------------------------
# Тест: невалидный JWT → HTTPException 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_jwt_raises(db_session):
    """Мусорный JWT должен вернуть 401."""
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_ws_token("not.a.valid.jwt", db_session)

    assert exc_info.value.status_code == 401
