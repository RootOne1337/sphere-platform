# tests/test_services/test_api_key_service.py
# TZ-01 SPLIT-4: Unit-тесты для APIKeyService.
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.api_key_service import APIKeyService


def _make_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.get = AsyncMock()
    db.execute = AsyncMock()
    return db


class TestCreateApiKey:
    @pytest.mark.asyncio
    async def test_create_returns_tuple_key_and_raw(self):
        db = _make_db()
        svc = APIKeyService(db)
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        api_key, raw = await svc.create_api_key(
            org_id=org_id,
            name="test-key",
            permissions=["device:read"],
            created_by=user_id,
        )
        assert raw.startswith("sphr_")
        db.add.assert_called_once()
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_expiry(self):
        db = _make_db()
        svc = APIKeyService(db)
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        api_key, raw = await svc.create_api_key(
            org_id=uuid.uuid4(),
            name="exp-key",
            permissions=["device:write"],
            created_by=uuid.uuid4(),
            expires_at=expires,
        )
        assert raw.startswith("sphr_")

    @pytest.mark.asyncio
    async def test_create_with_custom_key_type(self):
        db = _make_db()
        svc = APIKeyService(db)
        api_key, raw = await svc.create_api_key(
            org_id=uuid.uuid4(),
            name="n8n-key",
            permissions=["script:run"],
            created_by=uuid.uuid4(),
            key_type="service",
        )
        assert api_key.type == "service"


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_invalid_prefix_returns_none(self):
        db = _make_db()
        svc = APIKeyService(db)
        result = await svc.authenticate("invalid_key_without_prefix")
        assert result is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_key_found_in_db(self):
        db = _make_db()
        fake_key = MagicMock()
        fake_key.id = uuid.uuid4()
        # scalar_one_or_none returns the fake key
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=fake_key)

        svc = APIKeyService(db)
        result = await svc.authenticate("sphr_test_some_key_value")
        # execute called twice: SELECT + UPDATE last_used_at
        assert db.execute.call_count == 2
        assert result is fake_key

    @pytest.mark.asyncio
    async def test_key_not_found_returns_none(self):
        db = _make_db()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        svc = APIKeyService(db)
        result = await svc.authenticate("sphr_nonexistent")
        assert result is None
        # No UPDATE call when key not found
        assert db.execute.call_count == 1


class TestRevoke:
    @pytest.mark.asyncio
    async def test_revoke_not_found_returns_false(self):
        db = _make_db()
        db.get.return_value = None
        svc = APIKeyService(db)
        result = await svc.revoke(uuid.uuid4(), uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_wrong_org_returns_false(self):
        db = _make_db()
        fake_key = MagicMock()
        fake_key.org_id = uuid.uuid4()   # чужая org
        db.get.return_value = fake_key

        svc = APIKeyService(db)
        result = await svc.revoke(uuid.uuid4(), uuid.uuid4())  # другой org_id
        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_success(self):
        db = _make_db()
        org_id = uuid.uuid4()
        key_id = uuid.uuid4()

        fake_key = MagicMock()
        fake_key.org_id = org_id
        fake_key.is_active = True
        db.get.return_value = fake_key

        svc = APIKeyService(db)
        result = await svc.revoke(key_id, org_id)
        assert result is True
        assert fake_key.is_active is False
        db.commit.assert_called_once()


class TestListForOrg:
    @pytest.mark.asyncio
    async def test_list_returns_keys(self):
        db = _make_db()
        fake_keys = [MagicMock(), MagicMock()]
        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=fake_keys)
        db.execute.return_value.scalars = MagicMock(return_value=scalars_mock)

        svc = APIKeyService(db)
        result = await svc.list_for_org(uuid.uuid4())
        assert result == fake_keys
