# tests/orchestrator/test_pipeline_toggle.py
# Тесты для PipelineService.toggle().
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.orchestrator.pipeline_service import PipelineService


def _make_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_pipeline(is_active: bool = True) -> MagicMock:
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    pipeline.org_id = uuid.uuid4()
    pipeline.is_active = is_active
    pipeline.version = 1
    return pipeline


class TestPipelineToggle:
    @pytest.mark.asyncio
    async def test_toggle_activate(self):
        """toggle(active=True) должен установить is_active=True."""
        db = _make_db()
        svc = PipelineService(db)
        pipeline = _make_pipeline(is_active=False)
        svc.get = AsyncMock(return_value=pipeline)

        result = await svc.toggle(pipeline.id, pipeline.org_id, active=True)

        assert result.is_active is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_deactivate(self):
        """toggle(active=False) должен установить is_active=False."""
        db = _make_db()
        svc = PipelineService(db)
        pipeline = _make_pipeline(is_active=True)
        svc.get = AsyncMock(return_value=pipeline)

        result = await svc.toggle(pipeline.id, pipeline.org_id, active=False)

        assert result.is_active is False
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_idempotent(self):
        """Повторный toggle(active=True) на уже активном pipeline — не падает."""
        db = _make_db()
        svc = PipelineService(db)
        pipeline = _make_pipeline(is_active=True)
        svc.get = AsyncMock(return_value=pipeline)

        result = await svc.toggle(pipeline.id, pipeline.org_id, active=True)

        assert result.is_active is True
