# backend/services/orchestrator/pipeline_service.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. CRUD + запуск pipeline.
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device, device_group_members
from backend.models.device_group import DeviceGroup
from backend.models.pipeline import (
    Pipeline,
    PipelineBatch,
    PipelineRun,
    PipelineRunStatus,
)

logger = structlog.get_logger()


class PipelineService:
    """
    Сервис управления pipeline: CRUD, запуск на устройство, массовый запуск.

    Не содержит бизнес-логику исполнения шагов — за это отвечает PipelineExecutor.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def create(
        self,
        org_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
        *,
        name: str,
        description: str | None = None,
        steps: list[dict[str, Any]],
        input_schema: dict[str, Any] | None = None,
        global_timeout_ms: int = 86_400_000,
        max_retries: int = 0,
        tags: list[str] | None = None,
    ) -> Pipeline:
        """Создать новый pipeline-шаблон."""
        pipeline = Pipeline(
            org_id=org_id,
            name=name,
            description=description,
            steps=steps,
            input_schema=input_schema or {},
            global_timeout_ms=global_timeout_ms,
            max_retries=max_retries,
            tags=tags or [],
            created_by_id=created_by_id,
        )
        self.db.add(pipeline)
        await self.db.flush()
        logger.info("pipeline.created", pipeline_id=str(pipeline.id), name=name)
        return pipeline

    async def get(self, pipeline_id: uuid.UUID, org_id: uuid.UUID) -> Pipeline:
        """Получить pipeline по ID с проверкой принадлежности к организации."""
        pipeline = await self.db.scalar(
            select(Pipeline).where(
                Pipeline.id == pipeline_id,
                Pipeline.org_id == org_id,
            )
        )
        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline не найден")
        return pipeline

    async def list_pipelines(
        self,
        org_id: uuid.UUID,
        *,
        is_active: bool | None = None,
        tag: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Pipeline], int]:
        """Список pipeline с фильтрацией и пагинацией."""
        base = select(Pipeline).where(Pipeline.org_id == org_id)
        count_q = select(func.count()).select_from(Pipeline).where(Pipeline.org_id == org_id)

        if is_active is not None:
            base = base.where(Pipeline.is_active == is_active)
            count_q = count_q.where(Pipeline.is_active == is_active)
        if tag is not None:
            # JSONB contains: tags @> '["tag"]'
            base = base.where(Pipeline.tags.contains([tag]))
            count_q = count_q.where(Pipeline.tags.contains([tag]))

        total = await self.db.scalar(count_q) or 0
        items = (
            await self.db.scalars(
                base.order_by(Pipeline.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
        return list(items), total

    async def update(
        self,
        pipeline_id: uuid.UUID,
        org_id: uuid.UUID,
        **fields: Any,
    ) -> Pipeline:
        """Обновить pipeline. Increment version при изменении steps."""
        pipeline = await self.get(pipeline_id, org_id)
        bump_version = False
        for key, value in fields.items():
            if value is not None and hasattr(pipeline, key):
                if key == "steps":
                    bump_version = True
                setattr(pipeline, key, value)
        if bump_version:
            pipeline.version += 1
        await self.db.flush()
        logger.info("pipeline.updated", pipeline_id=str(pipeline_id), version=pipeline.version)
        return pipeline

    async def delete(self, pipeline_id: uuid.UUID, org_id: uuid.UUID) -> None:
        """Мягкое удаление — деактивация pipeline."""
        pipeline = await self.get(pipeline_id, org_id)
        pipeline.is_active = False
        await self.db.flush()
        logger.info("pipeline.deactivated", pipeline_id=str(pipeline_id))

    async def toggle(
        self,
        pipeline_id: uuid.UUID,
        org_id: uuid.UUID,
        active: bool,
    ) -> Pipeline:
        """Включить / выключить pipeline. Сохраняется в БД, переживает рестарт."""
        pipeline = await self.get(pipeline_id, org_id)
        pipeline.is_active = active
        await self.db.flush()
        logger.info(
            "pipeline.toggled",
            pipeline_id=str(pipeline_id),
            is_active=active,
        )
        return pipeline

    # ── Запуск ───────────────────────────────────────────────────────────────

    async def run(
        self,
        pipeline_id: uuid.UUID,
        device_id: uuid.UUID,
        org_id: uuid.UUID,
        *,
        input_params: dict[str, Any] | None = None,
    ) -> PipelineRun:
        """
        Создать PipelineRun — запустить pipeline на одном устройстве.

        Создаёт запись со status=QUEUED. Фактическое исполнение —
        PipelineExecutor берёт QUEUED записи из очереди.
        """
        pipeline = await self.get(pipeline_id, org_id)
        if not pipeline.is_active:
            raise HTTPException(status_code=400, detail="Pipeline деактивирован")

        # Проверить что устройство принадлежит организации
        device = await self.db.scalar(
            select(Device).where(Device.id == device_id, Device.org_id == org_id)
        )
        if not device:
            raise HTTPException(status_code=404, detail="Устройство не найдено")

        run = PipelineRun(
            org_id=org_id,
            pipeline_id=pipeline_id,
            device_id=device_id,
            status=PipelineRunStatus.QUEUED,
            input_params=input_params or {},
            steps_snapshot=pipeline.steps,  # иммутабельный снимок
            context={},
            step_logs=[],
        )
        self.db.add(run)
        await self.db.flush()
        logger.info(
            "pipeline_run.created",
            run_id=str(run.id),
            pipeline_id=str(pipeline_id),
            device_id=str(device_id),
        )
        return run

    async def run_batch(
        self,
        pipeline_id: uuid.UUID,
        org_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
        *,
        device_ids: list[uuid.UUID] | None = None,
        group_id: uuid.UUID | None = None,
        device_tags: list[str] | None = None,
        input_params: dict[str, Any] | None = None,
        wave_size: int = 0,
        wave_delay_seconds: int = 30,
    ) -> PipelineBatch:
        """
        Массовый запуск pipeline.

        Резолвит устройства из device_ids / group_id / device_tags,
        создаёт PipelineBatch + PipelineRun для каждого устройства.
        """
        pipeline = await self.get(pipeline_id, org_id)
        if not pipeline.is_active:
            raise HTTPException(status_code=400, detail="Pipeline деактивирован")

        # Резолвинг списка устройств
        resolved_device_ids = await self._resolve_devices(
            org_id, device_ids=device_ids, group_id=group_id, device_tags=device_tags,
        )
        if not resolved_device_ids:
            raise HTTPException(status_code=400, detail="Нет подходящих устройств")

        # Создать batch
        batch = PipelineBatch(
            org_id=org_id,
            pipeline_id=pipeline_id,
            status="running",
            total=len(resolved_device_ids),
            wave_config={
                "wave_size": wave_size,
                "wave_delay_seconds": wave_delay_seconds,
            },
            created_by_id=created_by_id,
        )
        self.db.add(batch)
        await self.db.flush()

        # Создать PipelineRun для каждого устройства
        for did in resolved_device_ids:
            run = PipelineRun(
                org_id=org_id,
                pipeline_id=pipeline_id,
                device_id=did,
                status=PipelineRunStatus.QUEUED,
                input_params=input_params or {},
                steps_snapshot=pipeline.steps,
                context={"batch_id": str(batch.id)},
                step_logs=[],
            )
            self.db.add(run)

        await self.db.flush()
        logger.info(
            "pipeline_batch.created",
            batch_id=str(batch.id),
            pipeline_id=str(pipeline_id),
            total=len(resolved_device_ids),
        )
        return batch

    # ── Pipeline Run management ──────────────────────────────────────────────

    async def get_run(self, run_id: uuid.UUID, org_id: uuid.UUID, *, for_update: bool = False) -> PipelineRun:
        """Получить pipeline run."""
        query = select(PipelineRun).where(PipelineRun.id == run_id, PipelineRun.org_id == org_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        run = await self.db.scalar(query)
        if not run:
            raise HTTPException(status_code=404, detail="Pipeline run не найден")
        return run

    async def list_runs(
        self,
        org_id: uuid.UUID,
        *,
        pipeline_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        status: PipelineRunStatus | None = None,
        active_only: bool = False,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[PipelineRun], int]:
        """Список pipeline runs с фильтрацией."""
        base = select(PipelineRun).where(PipelineRun.org_id == org_id)
        count_q = select(func.count()).select_from(PipelineRun).where(PipelineRun.org_id == org_id)

        if pipeline_id:
            base = base.where(PipelineRun.pipeline_id == pipeline_id)
            count_q = count_q.where(PipelineRun.pipeline_id == pipeline_id)
        if device_id:
            base = base.where(PipelineRun.device_id == device_id)
            count_q = count_q.where(PipelineRun.device_id == device_id)
        if status:
            base = base.where(PipelineRun.status == status)
            count_q = count_q.where(PipelineRun.status == status)
        if active_only:
            active = PipelineRun.status.in_([
                PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING,
                PipelineRunStatus.WAITING, PipelineRunStatus.PAUSED,
            ])
            base = base.where(active)
            count_q = count_q.where(active)

        total = await self.db.scalar(count_q) or 0
        items = (
            await self.db.scalars(
                base.order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
        return list(items), total

    async def cancel_run(self, run_id: uuid.UUID, org_id: uuid.UUID) -> PipelineRun:
        """Persist cancellation of run and current child without publishing controls.

        Lock Task before PipelineRun, consistently with result/scheduler writers.
        If admission changed the child while waiting, reject before mutation.
        """
        from backend.models.task import Task, TaskStatus
        from backend.services.task_service import TaskService

        initial_run = await self.get_run(run_id, org_id)
        child_id = initial_run.current_task_id
        child = None
        if child_id:
            child = await self.db.scalar(select(Task).where(
                Task.id == child_id, Task.org_id == org_id,
            ).with_for_update().execution_options(populate_existing=True))
        run = await self.db.scalar(select(PipelineRun).where(
            PipelineRun.id == run_id, PipelineRun.org_id == org_id,
        ).with_for_update().execution_options(populate_existing=True))
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run не найден")
        if run.current_task_id != child_id:
            raise HTTPException(status_code=409, detail="Pipeline child changed; refresh before retrying cancellation")
        if child_id is not None and child is None:
            raise HTTPException(status_code=409, detail="Pipeline child unavailable; cannot confirm cancellation")
        terminal_statuses = {
            PipelineRunStatus.COMPLETED,
            PipelineRunStatus.FAILED,
            PipelineRunStatus.CANCELLED,
            PipelineRunStatus.TIMED_OUT,
        }
        if run.status in terminal_statuses:
            raise HTTPException(status_code=400, detail=f"Нельзя отменить run в статусе {run.status}")
        if run.cancel_requested_at is None:
            run.cancel_requested_at = datetime.now(timezone.utc)
        active_child = False
        if child is not None and child.status in (TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING):
            await TaskService(self.db)._request_cancellation(child)
            active_child = child.status in (TaskStatus.ASSIGNED, TaskStatus.RUNNING)
        # Nested runs carry a durable parent link. Parent cancellation is not
        # terminal until their cancellations/results have been reconciled too.
        active_nested = await self.db.scalar(select(PipelineRun.id).where(
            PipelineRun.org_id == org_id,
            PipelineRun.context["parent_run_id"].astext == str(run.id),
            PipelineRun.status.in_([PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING,
                                   PipelineRunStatus.WAITING, PipelineRunStatus.PAUSED]),
        ).limit(1))
        run.updated_at = datetime.now(timezone.utc)
        if not active_child and active_nested is None:
            run.status = PipelineRunStatus.CANCELLED
            run.finished_at = datetime.now(timezone.utc)
        await self.db.flush()
        logger.info("pipeline_run.cancelled", run_id=str(run_id))
        return run

    async def pause_run(self, run_id: uuid.UUID, org_id: uuid.UUID) -> PipelineRun:
        """Приостановить pipeline run."""
        run = await self.get_run(run_id, org_id, for_update=True)
        if run.status != PipelineRunStatus.RUNNING or run.cancel_requested_at is not None:
            raise HTTPException(status_code=400, detail="Можно приостановить только RUNNING run")
        run.status = PipelineRunStatus.PAUSED
        await self.db.flush()
        logger.info("pipeline_run.paused", run_id=str(run_id))
        return run

    async def resume_run(self, run_id: uuid.UUID, org_id: uuid.UUID) -> PipelineRun:
        """Возобновить pipeline run."""
        run = await self.get_run(run_id, org_id, for_update=True)
        if run.status != PipelineRunStatus.PAUSED or run.cancel_requested_at is not None:
            raise HTTPException(status_code=400, detail="Можно возобновить только PAUSED run")
        run.status = PipelineRunStatus.QUEUED
        await self.db.flush()
        logger.info("pipeline_run.resumed", run_id=str(run_id))
        return run

    # ── Вспомогательные ──────────────────────────────────────────────────────

    async def _resolve_devices(
        self,
        org_id: uuid.UUID,
        *,
        device_ids: list[uuid.UUID] | None = None,
        group_id: uuid.UUID | None = None,
        device_tags: list[str] | None = None,
    ) -> list[uuid.UUID]:
        """
        Резолвинг устройств: объединяет device_ids + group_id + device_tags.
        Возвращает дедуплицированный список UUID.
        """
        result: set[uuid.UUID] = set()

        # Конкретные устройства
        if device_ids:
            rows = await self.db.scalars(
                select(Device.id).where(
                    Device.id.in_(device_ids),
                    Device.org_id == org_id,
                    Device.is_active.is_(True),
                )
            )
            result.update(rows.all())

        # По группе
        if group_id:
            group = await self.db.scalar(
                select(DeviceGroup).where(
                    DeviceGroup.id == group_id,
                    DeviceGroup.org_id == org_id,
                )
            )
            if group:
                from sqlalchemy import select as sa_select
                member_ids = await self.db.scalars(
                    sa_select(device_group_members.c.device_id).where(
                        device_group_members.c.group_id == group_id,
                    )
                )
                result.update(member_ids.all())

        # По тегам
        if device_tags:
            for tag in device_tags:
                tagged = await self.db.scalars(
                    select(Device.id).where(
                        Device.org_id == org_id,
                        Device.is_active.is_(True),
                        Device.tags.contains([tag]),
                    )
                )
                result.update(tagged.all())

        return list(result)
