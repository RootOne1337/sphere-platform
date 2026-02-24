# tests/test_services/test_audit_log_service.py
# TZ-01 SPLIT-5: Unit-тесты для AuditLogService.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.audit_log_service import AuditLogService


def _make_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


class TestAuditLogService:
    @pytest.mark.asyncio
    async def test_log_basic_event(self):
        db = _make_db()
        svc = AuditLogService(db)
        await svc.log("device.created", org_id=uuid.uuid4(), user_id=uuid.uuid4())
        db.add.assert_called_once()
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_with_all_fields(self):
        db = _make_db()
        svc = AuditLogService(db)
        await svc.log(
            "device.updated",
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            resource_type="device",
            resource_id=str(uuid.uuid4()),
            old_values={"name": "old"},
            new_values={"name": "new"},
            ip_address="127.0.0.1",
            user_agent="pytest/1.0",
            status="success",
            duration_ms=42,
        )
        entry = db.add.call_args[0][0]
        assert entry.action == "device.updated"
        assert entry.meta["duration_ms"] == 42
        assert entry.meta["status"] == "success"

    @pytest.mark.asyncio
    async def test_log_without_duration_omits_key(self):
        db = _make_db()
        svc = AuditLogService(db)
        await svc.log("auth.login")
        entry = db.add.call_args[0][0]
        assert "duration_ms" not in entry.meta

    @pytest.mark.asyncio
    async def test_log_db_exception_does_not_raise(self):
        """AuditLogService никогда не поднимает исключение — ошибки только в stderr."""
        db = AsyncMock()
        db.add = MagicMock(side_effect=Exception("DB is down"))
        db.flush = AsyncMock()

        svc = AuditLogService(db)
        # Должен выполниться без исключения
        await svc.log("device.deleted")

    @pytest.mark.asyncio
    async def test_log_resource_id_converted_to_str(self):
        db = _make_db()
        svc = AuditLogService(db)
        rid = uuid.uuid4()
        await svc.log("script.run", resource_id=rid)
        entry = db.add.call_args[0][0]
        assert entry.resource_id == str(rid)

    @pytest.mark.asyncio
    async def test_log_none_resource_id_stays_none(self):
        db = _make_db()
        svc = AuditLogService(db)
        await svc.log("org.updated", resource_id=None)
        entry = db.add.call_args[0][0]
        assert entry.resource_id is None
