# tests/orchestrator/test_pipeline_service.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. Unit-тесты PipelineService + PipelineExecutor.
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.pipeline import Pipeline, PipelineBatch, PipelineRun, PipelineRunStatus


# ── Фикстуры ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_pipeline(db_session: AsyncSession, test_org, test_user) -> Pipeline:
    """Тестовый pipeline с двумя шагами."""
    pipeline = Pipeline(
        org_id=test_org.id,
        name="Тестовый Pipeline",
        description="Pipeline для unit-тестов",
        steps=[
            {
                "id": "step_1",
                "name": "Задержка",
                "type": "delay",
                "params": {"delay_ms": 100},
                "on_success": "step_2",
                "on_failure": None,
                "timeout_ms": 5000,
                "retries": 0,
            },
            {
                "id": "step_2",
                "name": "Финальная задержка",
                "type": "delay",
                "params": {"delay_ms": 100},
                "on_success": None,
                "on_failure": None,
                "timeout_ms": 5000,
                "retries": 0,
            },
        ],
        input_schema={},
        global_timeout_ms=300_000,
        max_retries=0,
        tags=["test", "auto"],
        created_by_id=test_user.id,
    )
    db_session.add(pipeline)
    await db_session.flush()
    return pipeline


# ── Тесты PipelineService ────────────────────────────────────────────────────


class TestPipelineService:
    """Unit-тесты CRUD-операций PipelineService."""

    @pytest.mark.asyncio
    async def test_create_pipeline(self, db_session: AsyncSession, test_org, test_user):
        """Создание pipeline — проверяем все поля."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        pipeline = await svc.create(
            org_id=test_org.id,
            created_by_id=test_user.id,
            name="Новый Pipeline",
            description="Описание",
            steps=[{"id": "s1", "name": "step", "type": "delay", "params": {"delay_ms": 100}}],
            tags=["test"],
        )
        await db_session.flush()

        assert pipeline.id is not None
        assert pipeline.name == "Новый Pipeline"
        assert pipeline.org_id == test_org.id
        assert pipeline.version == 1
        assert pipeline.is_active is True
        assert len(pipeline.steps) == 1
        assert pipeline.tags == ["test"]

    @pytest.mark.asyncio
    async def test_get_pipeline(self, db_session: AsyncSession, test_org, test_pipeline):
        """Получение pipeline по ID."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        fetched = await svc.get(test_pipeline.id, test_org.id)
        assert fetched.id == test_pipeline.id
        assert fetched.name == "Тестовый Pipeline"

    @pytest.mark.asyncio
    async def test_get_pipeline_wrong_org(self, db_session: AsyncSession, test_pipeline):
        """Попытка получить pipeline чужой организации → 404."""
        from fastapi import HTTPException

        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await svc.get(test_pipeline.id, uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_pipelines(self, db_session: AsyncSession, test_org, test_pipeline):
        """Список pipeline — должен вернуть хотя бы один."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        items, total = await svc.list_pipelines(test_org.id)
        assert total >= 1
        assert any(p.id == test_pipeline.id for p in items)

    @pytest.mark.asyncio
    async def test_update_pipeline_bumps_version(self, db_session: AsyncSession, test_org, test_pipeline):
        """Обновление steps увеличивает version."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        original_version = test_pipeline.version
        await svc.update(
            test_pipeline.id,
            test_org.id,
            steps=[{"id": "new", "name": "new", "type": "delay", "params": {}}],
        )
        await db_session.flush()
        assert test_pipeline.version == original_version + 1

    @pytest.mark.asyncio
    async def test_delete_pipeline_deactivates(self, db_session: AsyncSession, test_org, test_pipeline):
        """Удаление (деактивация) ставит is_active=False."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        await svc.delete(test_pipeline.id, test_org.id)
        await db_session.flush()
        assert test_pipeline.is_active is False

    @pytest.mark.asyncio
    async def test_run_pipeline_creates_run(
        self, db_session: AsyncSession, test_org, test_pipeline, test_device,
    ):
        """Запуск pipeline создаёт PipelineRun со статусом QUEUED."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        run = await svc.run(
            pipeline_id=test_pipeline.id,
            device_id=test_device.id,
            org_id=test_org.id,
            input_params={"game_id": "test"},
        )
        await db_session.flush()

        assert run.id is not None
        assert run.status == PipelineRunStatus.QUEUED
        assert run.pipeline_id == test_pipeline.id
        assert run.device_id == test_device.id
        assert run.input_params == {"game_id": "test"}
        assert len(run.steps_snapshot) == 2  # скопированы шаги

    @pytest.mark.asyncio
    async def test_cancel_run(
        self, db_session: AsyncSession, test_org, test_pipeline, test_device,
    ):
        """Отмена pipeline run."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        run = await svc.run(
            pipeline_id=test_pipeline.id,
            device_id=test_device.id,
            org_id=test_org.id,
        )
        await db_session.flush()

        cancelled = await svc.cancel_run(run.id, test_org.id)
        assert cancelled.status == PipelineRunStatus.CANCELLED
        assert cancelled.finished_at is not None

    @pytest.mark.asyncio
    async def test_run_batch_creates_batch_and_runs(
        self, db_session: AsyncSession, test_org, test_pipeline, test_device, test_user,
    ):
        """Массовый запуск создаёт batch + N runs."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        svc = PipelineService(db_session)
        batch = await svc.run_batch(
            pipeline_id=test_pipeline.id,
            org_id=test_org.id,
            created_by_id=test_user.id,
            device_ids=[test_device.id],
        )
        await db_session.flush()

        assert batch.id is not None
        assert batch.total == 1
        assert batch.status == "running"


# ── Тесты StepHandlers ───────────────────────────────────────────────────────


class TestStepHandlers:
    """Unit-тесты обработчиков шагов pipeline."""

    @pytest.mark.asyncio
    async def test_delay_handler(self, db_session: AsyncSession, test_org, test_pipeline, test_device):
        """Шаг delay: ожидание N мс."""
        from backend.services.orchestrator.step_handlers import StepHandlerRegistry

        run = PipelineRun(
            org_id=test_org.id,
            pipeline_id=test_pipeline.id,
            device_id=test_device.id,
            status=PipelineRunStatus.RUNNING,
            input_params={},
            steps_snapshot=[],
            context={},
            step_logs=[],
        )
        db_session.add(run)
        await db_session.flush()

        step = {"id": "s1", "type": "delay", "params": {"delay_ms": 100}, "timeout_ms": 5000}
        result = await StepHandlerRegistry.execute(step=step, run=run, db=db_session)
        assert result.status == "success"
        assert result.output["delayed_ms"] == 100

    @pytest.mark.asyncio
    async def test_condition_eq_true(self, db_session: AsyncSession, test_org, test_pipeline, test_device):
        """Шаг condition: operator=eq, совпадение."""
        from backend.services.orchestrator.step_handlers import StepHandlerRegistry

        run = PipelineRun(
            org_id=test_org.id,
            pipeline_id=test_pipeline.id,
            device_id=test_device.id,
            status=PipelineRunStatus.RUNNING,
            input_params={},
            steps_snapshot=[],
            context={"login_status": "success"},
            step_logs=[],
        )
        db_session.add(run)
        await db_session.flush()

        step = {
            "id": "cond1",
            "type": "condition",
            "params": {"context_key": "login_status", "operator": "eq", "expected_value": "success"},
            "timeout_ms": 5000,
        }
        result = await StepHandlerRegistry.execute(step=step, run=run, db=db_session)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_condition_eq_false(self, db_session: AsyncSession, test_org, test_pipeline, test_device):
        """Шаг condition: operator=eq, несовпадение."""
        from backend.services.orchestrator.step_handlers import StepHandlerRegistry

        run = PipelineRun(
            org_id=test_org.id,
            pipeline_id=test_pipeline.id,
            device_id=test_device.id,
            status=PipelineRunStatus.RUNNING,
            input_params={},
            steps_snapshot=[],
            context={"login_status": "failed"},
            step_logs=[],
        )
        db_session.add(run)
        await db_session.flush()

        step = {
            "id": "cond1",
            "type": "condition",
            "params": {"context_key": "login_status", "operator": "eq", "expected_value": "success"},
            "timeout_ms": 5000,
        }
        result = await StepHandlerRegistry.execute(step=step, run=run, db=db_session)
        assert result.status == "failure"

    @pytest.mark.asyncio
    async def test_unknown_step_type(self, db_session: AsyncSession, test_org, test_pipeline, test_device):
        """Неизвестный тип шага → failure."""
        from backend.services.orchestrator.step_handlers import StepHandlerRegistry

        run = PipelineRun(
            org_id=test_org.id,
            pipeline_id=test_pipeline.id,
            device_id=test_device.id,
            status=PipelineRunStatus.RUNNING,
            input_params={},
            steps_snapshot=[],
            context={},
            step_logs=[],
        )
        db_session.add(run)
        await db_session.flush()

        step = {"id": "s1", "type": "unknown_type", "params": {}, "timeout_ms": 5000}
        result = await StepHandlerRegistry.execute(step=step, run=run, db=db_session)
        assert result.status == "failure"
        assert "Неизвестный тип шага" in result.error
