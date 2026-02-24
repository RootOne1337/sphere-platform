# tests/test_ws/test_sync_device_status.py
# Tests for sync_device_status_to_db background task.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tasks.sync_device_status import sync_device_status_to_db


class TestSyncDeviceStatusEarlyReturn:

    @pytest.mark.asyncio
    async def test_returns_early_when_redis_is_none(self):
        with patch("backend.database.redis_client.redis_binary", None):
            # Should return without error
            await sync_device_status_to_db()

    @pytest.mark.asyncio
    async def test_returns_early_when_no_device_ids(self):
        mock_redis = AsyncMock()

        async def _empty_scan(*args, **kwargs):
            return
            yield  # make it an async generator

        mock_redis.scan_iter = _empty_scan

        with patch("backend.database.redis_client.redis_binary", mock_redis):
            await sync_device_status_to_db()


class TestSyncDeviceStatusFull:

    @pytest.mark.asyncio
    async def test_updates_device_status_for_valid_ids(self):
        device_id = str(uuid.uuid4())
        mock_redis = AsyncMock()

        # scan_iter yields one key
        async def _scan(*args, **kwargs):
            yield f"device:status:{device_id}"

        mock_redis.scan_iter = _scan

        # mget returns msgpack-encoded status for the device
        import msgpack
        from backend.schemas.device_status import DeviceLiveStatus
        live = DeviceLiveStatus(device_id=device_id, status="online")
        mock_redis.mget = AsyncMock(
            return_value=[msgpack.packb(live.model_dump(mode="json"), use_bin_type=True)]
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_session_local = MagicMock(return_value=mock_db)

        with patch("backend.database.redis_client.redis_binary", mock_redis), \
             patch("backend.database.engine.AsyncSessionLocal", mock_session_local):
            await sync_device_status_to_db()

        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_invalid_uuid_device_ids(self):
        mock_redis = AsyncMock()

        # scan_iter yields a non-UUID key
        async def _scan(*args, **kwargs):
            yield "device:status:not-a-valid-uuid"

        mock_redis.scan_iter = _scan

        import msgpack
        from backend.schemas.device_status import DeviceLiveStatus
        live = DeviceLiveStatus(device_id="not-valid", status="offline")
        mock_redis.mget = AsyncMock(
            return_value=[msgpack.packb(live.model_dump(mode="json"), use_bin_type=True)]
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_session_local = MagicMock(return_value=mock_db)

        with patch("backend.database.redis_client.redis_binary", mock_redis), \
             patch("backend.database.engine.AsyncSessionLocal", mock_session_local):
            await sync_device_status_to_db()

    @pytest.mark.asyncio
    async def test_rolls_back_on_db_exception(self):
        device_id = str(uuid.uuid4())
        mock_redis = AsyncMock()

        async def _scan(*args, **kwargs):
            yield f"device:status:{device_id}"

        mock_redis.scan_iter = _scan

        import msgpack
        from backend.schemas.device_status import DeviceLiveStatus
        live = DeviceLiveStatus(device_id=device_id, status="online")
        mock_redis.mget = AsyncMock(
            return_value=[msgpack.packb(live.model_dump(mode="json"), use_bin_type=True)]
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_db.rollback = AsyncMock()

        mock_session_local = MagicMock(return_value=mock_db)

        with patch("backend.database.redis_client.redis_binary", mock_redis), \
             patch("backend.database.engine.AsyncSessionLocal", mock_session_local):
            # Should not raise — exceptions are caught internally
            await sync_device_status_to_db()

        mock_db.rollback.assert_called_once()
