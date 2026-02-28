# backend/services/orchestrator/pipeline_executor.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. Движок исполнения pipeline (фоновый loop).
#
# Цикл работы:
#   1. SELECT ... WHERE status = 'queued' ORDER BY created_at FOR UPDATE SKIP LOCKED
#   2. Переводим в RUNNING, исполняем шаги последовательно
#   3. Каждый шаг → StepHandler → результат → обновление context / step_logs
#   4. Финальный статус: COMPLETED / FAILED / TIMED_OUT
#
# Важно: executor работает с собственной DB-сессией (не endpoint).
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import AsyncSessionLocal
from backend.models.pipeline import PipelineRun, PipelineRunStatus
from backend.models.task import Task, TaskStatus
from backend.services.orchestrator.step_handlers import StepHandlerRegistry

logger = structlog.get_logger()

# Интервал опроса очереди QUEUED runs
_POLL_INTERVAL_SECONDS = 2.0

# Максимум параллельных pipeline runs одновременно
_MAX_CONCURRENT_RUNS = 10


class PipelineExecutor:
    """
    Фоновый движок исполнения pipeline.

    Поллит БД на наличие QUEUED pipeline_runs,
    берёт записи через FOR UPDATE SKIP LOCKED (безопасно для multi-instance),
    исполняет шаги, обновляет статусы.
    """

    def __init__(self) -> None:
        self._running = False
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RUNS)
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Запуск фонового loop."""
        self._running = True
        logger.info("pipeline_executor.started")
        while self._running:
            try:
                await self._poll_and_dispatch()
            except Exception as exc:
                logger.error("pipeline_executor.poll_error", error=str(exc))
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Остановка executor."""
        self._running = False
        # Дождаться завершения активных задач (с таймаутом)
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=30)
        logger.info("pipeline_executor.stopped")

    async def _poll_and_dispatch(self) -> None:
        """Выбрать QUEUED runs и запустить в параллель (с ограничением _MAX_CONCURRENT_RUNS)."""
        async with AsyncSessionLocal() as db:
            # FOR UPDATE SKIP LOCKED — безопасно для нескольких инстансов бэкенда
            result = await db.execute(
                select(PipelineRun)
                .where(PipelineRun.status == PipelineRunStatus.QUEUED)
                .order_by(PipelineRun.created_at)
                .limit(_MAX_CONCURRENT_RUNS)
                .with_for_update(skip_locked=True)
            )
            runs = result.scalars().all()

            for run in runs:
                run.status = PipelineRunStatus.RUNNING
                run.started_at = datetime.now(timezone.utc)
            await db.commit()

        # Запустить каждый run в отдельной задаче
        for run in runs:
            task = asyncio.create_task(self._execute_run_safe(run.id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _execute_run_safe(self, run_id: uuid.UUID) -> None:
        """Обёртка: исполнение с семафором и обработкой ошибок."""
        async with self._semaphore:
            try:
                await self._execute_run(run_id)
            except Exception as exc:
                logger.error(
                    "pipeline_executor.run_failed",
                    run_id=str(run_id),
                    error=str(exc),
                )
                # Пометить как FAILED
                async with AsyncSessionLocal() as db:
                    run = await db.get(PipelineRun, run_id)
                    if run and run.status == PipelineRunStatus.RUNNING:
                        run.status = PipelineRunStatus.FAILED
                        run.finished_at = datetime.now(timezone.utc)
                        _append_step_log(run, {
                            "event": "executor_error",
                            "error": str(exc),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        await db.commit()

    async def _execute_run(self, run_id: uuid.UUID) -> None:
        """
        Последовательное исполнение шагов pipeline run.

        Алгоритм:
        1. Загрузить run из БД
        2. Определить текущий шаг (steps_snapshot[0] или current_step_id для resume)
        3. Для каждого шага: вызвать handler → получить StepResult
        4. При on_success → следующий шаг, при on_failure → обработка ошибки
        5. Финальный статус: COMPLETED / FAILED
        """
        async with AsyncSessionLocal() as db:
            run = await db.get(PipelineRun, run_id)
            if not run or run.status != PipelineRunStatus.RUNNING:
                return

            steps = run.steps_snapshot
            if not steps:
                run.status = PipelineRunStatus.COMPLETED
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return

            # Строим индекс шагов по ID
            step_index: dict[str, dict] = {s["id"]: s for s in steps}

            # Определить стартовый шаг (resume или первый)
            current_step_id = run.current_step_id or steps[0]["id"]

            while current_step_id:
                # Проверка на паузу / отмену
                await db.refresh(run)
                if run.status == PipelineRunStatus.PAUSED:
                    run.current_step_id = current_step_id
                    await db.commit()
                    logger.info("pipeline_run.paused_at_step", run_id=str(run_id), step=current_step_id)
                    return
                if run.status in (PipelineRunStatus.CANCELLED, PipelineRunStatus.TIMED_OUT):
                    await db.commit()
                    return

                step = step_index.get(current_step_id)
                if not step:
                    run.status = PipelineRunStatus.FAILED
                    run.finished_at = datetime.now(timezone.utc)
                    _append_step_log(run, {
                        "step_id": current_step_id,
                        "event": "step_not_found",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    await db.commit()
                    return

                # Обновить позицию
                run.current_step_id = current_step_id
                await db.commit()

                # Проверка глобального таймаута
                if run.started_at:
                    elapsed_ms = (datetime.now(timezone.utc) - run.started_at).total_seconds() * 1000
                    pipeline = await db.get(
                        __import__('backend.models.pipeline', fromlist=['Pipeline']).Pipeline,
                        run.pipeline_id,
                    )
                    timeout_ms = pipeline.global_timeout_ms if pipeline else 86_400_000
                    if elapsed_ms > timeout_ms:
                        run.status = PipelineRunStatus.TIMED_OUT
                        run.finished_at = datetime.now(timezone.utc)
                        _append_step_log(run, {
                            "step_id": current_step_id,
                            "event": "global_timeout",
                            "elapsed_ms": int(elapsed_ms),
                            "timeout_ms": timeout_ms,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        await db.commit()
                        logger.warning("pipeline_run.timeout", run_id=str(run_id))
                        return

                # Исполнить шаг
                step_start = time.monotonic()
                step_result = await StepHandlerRegistry.execute(
                    step=step,
                    run=run,
                    db=db,
                )
                step_duration_ms = int((time.monotonic() - step_start) * 1000)

                # Записать лог шага
                log_entry = {
                    "step_id": current_step_id,
                    "step_type": step.get("type"),
                    "status": step_result.status,
                    "duration_ms": step_duration_ms,
                    "output": step_result.output,
                    "error": step_result.error,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                _append_step_log(run, log_entry)

                # Обновить контекст
                if step_result.context_updates:
                    ctx = dict(run.context)
                    ctx.update(step_result.context_updates)
                    run.context = ctx

                await db.commit()

                # Определить следующий шаг
                if step_result.status == "success":
                    current_step_id = step.get("on_success")
                elif step_result.status == "failure":
                    # Ретрай на уровне шага
                    retries = step.get("retries", 0)
                    retry_key = f"_retry_{current_step_id}"
                    ctx = dict(run.context)
                    current_retry = ctx.get(retry_key, 0)
                    if current_retry < retries:
                        ctx[retry_key] = current_retry + 1
                        run.context = ctx
                        await db.commit()
                        logger.info(
                            "pipeline_run.step_retry",
                            run_id=str(run_id),
                            step=current_step_id,
                            attempt=current_retry + 1,
                        )
                        continue  # Повторить тот же шаг
                    else:
                        next_on_fail = step.get("on_failure")
                        if next_on_fail:
                            current_step_id = next_on_fail
                        else:
                            # Нет обработчика ошибки — pipeline failed
                            run.status = PipelineRunStatus.FAILED
                            run.finished_at = datetime.now(timezone.utc)
                            await db.commit()
                            logger.warning(
                                "pipeline_run.step_failed",
                                run_id=str(run_id),
                                step=current_step_id,
                            )
                            return
                else:
                    # Неизвестный статус — fail
                    run.status = PipelineRunStatus.FAILED
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()
                    return

            # Все шаги пройдены — pipeline завершён
            await db.refresh(run)
            if run.status == PipelineRunStatus.RUNNING:
                run.status = PipelineRunStatus.COMPLETED
                run.finished_at = datetime.now(timezone.utc)
                run.current_step_id = None
                await db.commit()
                logger.info("pipeline_run.completed", run_id=str(run_id))


# ── Вспомогательные ──────────────────────────────────────────────────────────


def _append_step_log(run: PipelineRun, entry: dict) -> None:
    """
    Атомарное добавление записи в step_logs (JSONB).

    SQLAlchemy не детектирует мутацию JSONB in-place, поэтому
    создаём новый список + присваиваем — это корректно триггерит dirty.
    """
    logs = list(run.step_logs) if run.step_logs else []
    logs.append(entry)
    run.step_logs = logs
