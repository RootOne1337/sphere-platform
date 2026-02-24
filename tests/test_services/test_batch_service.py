# tests/test_services/test_batch_service.py
# TZ-04 SPLIT-4: Unit-тесты для BatchService (start_batch, get_batch, cancel_batch).
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.services.batch_service import BatchService


def _make_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.scalar = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_session_maker():
    """Фиктивная async_sessionmaker для фоновых задач."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    maker = MagicMock(return_value=ctx)
    return maker, session


def _make_request(
    device_ids: list | None = None,
    wave_size: int = 5,
    wave_delay_ms: int = 1000,
    jitter_ms: int = 0,
    priority: int = 5,
    stagger_by_workstation: bool = False,
    webhook_url: str | None = None,
) -> MagicMock:
    req = MagicMock()
    req.script_id = uuid.uuid4()
    req.device_ids = device_ids or [uuid.uuid4()]
    req.wave_size = wave_size
    req.wave_delay_ms = wave_delay_ms
    req.jitter_ms = jitter_ms
    req.priority = priority
    req.stagger_by_workstation = stagger_by_workstation
    req.webhook_url = webhook_url
    req.name = "test-batch"
    return req


class TestStartBatch:
    @pytest.mark.asyncio
    async def test_script_not_found_raises_404(self):
        db = _make_db()
        db.scalar.return_value = None
        maker, _ = _make_session_maker()
        svc = BatchService(db, maker)

        with pytest.raises(HTTPException) as exc_info:
            await svc.start_batch(_make_request(), uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_script_no_version_raises_400(self):
        db = _make_db()
        script = MagicMock()
        script.current_version_id = None
        db.scalar.return_value = script
        maker, _ = _make_session_maker()
        svc = BatchService(db, maker)

        with pytest.raises(HTTPException) as exc_info:
            await svc.start_batch(_make_request(), uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_start_batch_returns_batch_object(self):
        db = _make_db()
        script = MagicMock()
        script.current_version_id = uuid.uuid4()
        db.scalar.return_value = script
        maker, _ = _make_session_maker()
        svc = BatchService(db, maker)

        # Мокаем WorkstationMappingService.create_waves и asyncio.create_task
        with patch(
            "backend.services.batch_service.WorkstationMappingService.create_waves",
            AsyncMock(return_value=[[uuid.uuid4()]]),
        ), patch("asyncio.create_task") as mock_create_task:
            mock_task = MagicMock()
            mock_task.add_done_callback = MagicMock()
            mock_create_task.return_value = mock_task

            batch = await svc.start_batch(
                _make_request([uuid.uuid4()]), uuid.uuid4(), uuid.uuid4()
            )

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert batch is not None


class TestGetBatch:
    @pytest.mark.asyncio
    async def test_get_batch_not_found_raises_404(self):
        db = _make_db()
        db.scalar.return_value = None
        maker, _ = _make_session_maker()
        svc = BatchService(db, maker)

        with pytest.raises(HTTPException) as exc_info:
            await svc.get_batch(uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_batch_returns_batch(self):
        db = _make_db()
        fake_batch = MagicMock()
        db.scalar.return_value = fake_batch
        maker, _ = _make_session_maker()
        svc = BatchService(db, maker)

        result = await svc.get_batch(uuid.uuid4(), uuid.uuid4())
        assert result is fake_batch


class TestCancelBatch:
    @pytest.mark.asyncio
    async def test_cancel_already_completed_raises_409(self):
        db = _make_db()
        from backend.models.task_batch import TaskBatchStatus
        fake_batch = MagicMock()
        fake_batch.status = TaskBatchStatus.COMPLETED
        db.scalar.return_value = fake_batch
        maker, _ = _make_session_maker()
        svc = BatchService(db, maker)

        with pytest.raises(HTTPException) as exc_info:
            await svc.cancel_batch(uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_running_batch_sets_cancelled(self):
        db = _make_db()
        from backend.models.task_batch import TaskBatchStatus

        fake_batch = MagicMock()
        fake_batch.status = TaskBatchStatus.RUNNING
        db.scalar.return_value = fake_batch

        # Нет задач → пустой список
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=[])
        result_mock.scalars = MagicMock(return_value=scalars_mock)
        db.execute.return_value = result_mock

        maker, _ = _make_session_maker()
        svc = BatchService(db, maker)

        with patch("backend.services.task_queue.TaskQueue") as MockQueue, \
             patch("backend.database.redis_client.redis", MagicMock()):
            mock_queue = AsyncMock()
            mock_queue.cancel_task = AsyncMock()
            MockQueue.return_value = mock_queue
            await svc.cancel_batch(uuid.uuid4(), uuid.uuid4())

        assert fake_batch.status == TaskBatchStatus.CANCELLED


class TestSendBatchCompleteWebhook:
    @pytest.mark.asyncio
    async def test_send_webhook_on_completion(self):
        """_send_batch_complete_webhook вызывает WebhookService.deliver."""
        db = _make_db()
        maker, _ = _make_session_maker()
        svc = BatchService(db, maker)

        batch_id = uuid.uuid4()
        with patch("backend.services.webhook_service.WebhookService.deliver", AsyncMock()) as mock_deliver:
            await svc._send_batch_complete_webhook(batch_id, "https://hook.example.com", 10, 2)
            mock_deliver.assert_called_once()
            call_args = mock_deliver.call_args
            assert call_args[0][0] == "https://hook.example.com"
            payload = call_args[0][1]
            assert payload["event_type"] == "batch.completed"
            assert payload["succeeded"] == 10
            assert payload["failed"] == 2
