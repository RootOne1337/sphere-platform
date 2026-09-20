"""Bounded ownership leases and atomic step checkpoints for pipeline execution.

An expired lease permits another owner to inspect durable state. It is not
permission to replay an arbitrary external effect.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import timedelta

import structlog
from sqlalchemy import or_, select, update

from backend.database.tenant import bind_tenant_context
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.task import Task, TaskStatus
from backend.services.orchestrator.pipeline_ownership import (
    Ownership,
    PipelineLeaseLost,
    current_ownership,
    database_now,
    fence_write,
)
from backend.services.orchestrator.pipeline_tenants import (
    discover_work,
    recovery_predicate,
    tenant_sessions,
)
from backend.services.orchestrator.step_handlers import StepHandlerRegistry, StepResult

logger = structlog.get_logger()
LEASE_SECONDS = 30
HEARTBEAT_SECONDS = 5
HEARTBEAT_TIMEOUT_SECONDS = 3
RECOVERABLE_STEPS = {"delay", "condition", "execute_script", "sub_pipeline"}
UNCONFIRMED_FAILURE_STEPS = {"action", "n8n_workflow", "loop", "parallel"}


def append_log(run: PipelineRun, entry: dict) -> None:
    run.step_logs = [*(run.step_logs or []), entry]


def require_review(run: PipelineRun, reason: str, now) -> None:
    run.status = PipelineRunStatus.PAUSED
    run.execution_phase = "unknown"
    run.execution_owner = None
    run.execution_lease_until = None
    run.context = {**(run.context or {}), "_recovery": {"required": True, "reason": reason}}
    append_log(run, {"event": "recovery_required", "step_id": run.current_step_id,
                     "reason": reason, "timestamp": now.isoformat()})


async def recover_expired(sessions, *, org_id: uuid.UUID | None = None) -> None:
    candidates = await discover_work(sessions, "recovery", org_id=org_id)
    grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
    for run_id, tenant_id in candidates:
        grouped.setdefault(tenant_id, []).append(run_id)
    for tenant_id, run_ids in grouped.items():
        async with tenant_sessions(sessions, tenant_id)() as db:
            now = await database_now(db)
            rows = list(await db.scalars(select(PipelineRun).where(
                PipelineRun.id.in_(run_ids), PipelineRun.org_id == tenant_id, recovery_predicate(now),
            ).order_by(PipelineRun.updated_at, PipelineRun.id).with_for_update(skip_locked=True)))
            for run in rows:
                step = next((s for s in run.steps_snapshot if s.get("id") == run.current_step_id), None)
                resumable = run.execution_phase == "ready" or (
                    run.execution_phase == "in_flight" and step and step.get("type") in RECOVERABLE_STEPS
                )
                run.execution_generation += 1
                run.execution_owner = None
                run.execution_lease_until = None
                if not resumable:
                    require_review(run, "worker_lost_with_unconfirmed_step_outcome", now)
                elif run.status in (PipelineRunStatus.RUNNING, PipelineRunStatus.WAITING):
                    run.status = PipelineRunStatus.QUEUED
                    append_log(run, {"event": "lease_recovered", "step_id": run.current_step_id,
                                     "generation": run.execution_generation, "timestamp": now.isoformat()})
            await db.commit()


async def renew_lease(sessions, ownership: Ownership) -> bool:
    async with sessions() as db:
        if ownership.org_id is not None:
            await bind_tenant_context(db, str(ownership.org_id))
        run = await db.get(PipelineRun, ownership.run_id, with_for_update=True)
        now = await database_now(db)
        if (run is None or run.execution_owner != ownership.owner
                or run.execution_generation != ownership.generation
                or run.execution_lease_until is None or run.execution_lease_until <= now
                or run.status not in (PipelineRunStatus.RUNNING, PipelineRunStatus.PAUSED)):
            return False
        run.execution_lease_until = now + timedelta(seconds=LEASE_SECONDS)
        await db.commit()
        return True


class OwnedPipelineRunner:
    def __init__(self, owner: uuid.UUID, sessions, generation: int | None = None):
        self.owner = owner
        self.sessions = sessions
        self.generation = generation

    async def _heartbeat(self, ownership: Ownership, worker: asyncio.Task) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                if await asyncio.wait_for(renew_lease(self.sessions, ownership), HEARTBEAT_TIMEOUT_SECONDS):
                    continue
            except Exception as exc:
                logger.warning("pipeline.lease_renewal_failed", run_id=str(ownership.run_id),
                               error_type=type(exc).__name__)
            worker.cancel()  # No FAILED write, no retry, and no claim to have stopped Android.
            return

    async def run(self, run_id: uuid.UUID) -> None:
        async with self.sessions() as db:
            run = await db.get(PipelineRun, run_id, with_for_update=True)
            if not run or run.status != PipelineRunStatus.RUNNING or run.cancel_requested_at is not None:
                return
            now = await database_now(db)
            # Direct invocation is useful to callers/tests with a fresh READY run.
            # An existing foreign owner or ambiguous legacy run is never adopted here.
            if self.generation is None and run.execution_owner is None and run.execution_phase == "ready":
                run.execution_owner = self.owner
                run.execution_generation += 1
                run.execution_lease_until = now + timedelta(seconds=LEASE_SECONDS)
            if run.execution_owner != self.owner or not run.execution_lease_until or run.execution_lease_until <= now:
                return
            if self.generation is not None and run.execution_generation != self.generation:
                return
            ownership = Ownership(run.id, self.owner, run.execution_generation, org_id=run.org_id)
            await db.commit()

        token = current_ownership.set(ownership)
        worker = asyncio.current_task()
        assert worker is not None
        heartbeat = asyncio.create_task(self._heartbeat(ownership, worker))
        try:
            await self._steps(run_id)
        except PipelineLeaseLost:
            logger.info("pipeline.owner_fenced", run_id=str(run_id), generation=ownership.generation)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            try:
                async with self.sessions() as db:
                    # Only a committed boundary/terminal record can relinquish its
                    # owner immediately. Interrupted in-flight work keeps its lease
                    # until recovery, preserving the evidence of an unknown outcome.
                    await db.execute(update(PipelineRun).where(
                        PipelineRun.id == run_id, PipelineRun.execution_owner == ownership.owner,
                        PipelineRun.execution_generation == ownership.generation,
                        or_(PipelineRun.execution_phase != "in_flight",
                            PipelineRun.status.in_([PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED,
                                                    PipelineRunStatus.CANCELLED, PipelineRunStatus.TIMED_OUT])),
                    ).values(execution_owner=None, execution_lease_until=None))
                    await db.commit()
            except Exception as exc:
                logger.warning("pipeline.lease_release_pending", run_id=str(run_id), error_type=type(exc).__name__)
            finally:
                current_ownership.reset(token)

    async def _active_child(self, db, run: PipelineRun) -> bool:
        if run.current_task_id:
            child = await db.scalar(select(Task).where(
                Task.id == run.current_task_id, Task.org_id == run.org_id, Task.device_id == run.device_id,
            ))
            if child is None or child.status in (TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING):
                return True
        if run.current_child_run_id:
            child_run = await db.scalar(select(PipelineRun).where(
                PipelineRun.id == run.current_child_run_id, PipelineRun.org_id == run.org_id,
                PipelineRun.device_id == run.device_id,
                PipelineRun.context["parent_run_id"].astext == str(run.id),
            ))
            if child_run is None or child_run.status in (
                PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING, PipelineRunStatus.PAUSED, PipelineRunStatus.WAITING,
            ):
                return True
        return False

    async def _steps(self, run_id: uuid.UUID) -> None:
        async with self.sessions() as db:
            run = await db.get(PipelineRun, run_id)
            assert run is not None
            while True:
                await fence_write(db, run)
                now = await database_now(db)
                if run.cancel_requested_at is not None or run.status == PipelineRunStatus.PAUSED:
                    await db.commit()
                    return
                if run.execution_phase == "unknown":
                    require_review(run, "unconfirmed_step_outcome", now)
                    await db.commit()
                    return
                steps = run.steps_snapshot
                if not steps:
                    run.status = PipelineRunStatus.COMPLETED
                    run.finished_at = now
                    await db.commit()
                    return
                step_id = run.current_step_id or steps[0]["id"]
                step = next((s for s in steps if s.get("id") == step_id), None)
                if step is None:
                    require_review(run, "checkpoint_step_missing", now)
                    await db.commit()
                    return
                pipeline = await db.get(Pipeline, run.pipeline_id)
                global_timeout = pipeline.global_timeout_ms if pipeline else 86_400_000
                started = run.started_at or now
                run.started_at = started
                if (now - started).total_seconds() * 1000 >= global_timeout:
                    if await self._active_child(db, run):
                        require_review(run, "global_timeout_with_unfinished_child", now)
                    else:
                        run.status = PipelineRunStatus.TIMED_OUT
                        run.finished_at = now
                        append_log(run, {"event": "global_timeout", "step_id": step_id, "timestamp": now.isoformat()})
                    await db.commit()
                    return

                run.current_step_id = step_id
                recovering = run.execution_phase == "in_flight"
                if recovering and step.get("type") not in RECOVERABLE_STEPS:
                    require_review(run, "step_not_safe_to_replay", now)
                    await db.commit()
                    return
                run.execution_phase = "in_flight"
                run.step_started_at = run.step_started_at or now
                elapsed_ms = max(0, (now - run.step_started_at).total_seconds() * 1000)
                remaining_ms = min(step.get("timeout_ms", 60_000) - elapsed_ms,
                                   global_timeout - (now - started).total_seconds() * 1000)
                call_step = {**step, "timeout_ms": max(1, remaining_ms)}
                delay_complete = False
                if step.get("type") == "delay":
                    delay_ms = max(100, min(step.get("params", {}).get("delay_ms", 1000), 300000))
                    remaining_delay = delay_ms - elapsed_ms
                    delay_complete = remaining_delay <= 0
                    call_step["params"] = {**step.get("params", {}), "delay_ms": max(100, remaining_delay)}
                await db.commit()

                began = time.monotonic()
                if remaining_ms <= 0:
                    outcome = StepResult(status="failure", error="Persisted step deadline expired", outcome_unknown=True)
                elif delay_complete:
                    outcome = StepResult()
                else:
                    outcome = await StepHandlerRegistry.execute(step=call_step, run=run, db=db)
                await fence_write(db, run)
                now = await database_now(db)
                if run.cancel_requested_at is not None:
                    await db.commit()
                    return
                if outcome.status != "success" and (
                    await self._active_child(db, run)
                    or step.get("type") in UNCONFIRMED_FAILURE_STEPS
                    or (outcome.outcome_unknown and step.get("type") not in ("delay", "condition"))
                    or outcome.error == "pipeline_child_identity_unavailable"
                ):
                    require_review(run, "step_failed_with_unconfirmed_effect", now)
                    await db.commit()
                    return

                append_log(run, {"step_id": step_id, "step_type": step.get("type"), "status": outcome.status,
                                 "duration_ms": int((time.monotonic() - began) * 1000), "output": outcome.output,
                                 "error": outcome.error, "timestamp": now.isoformat()})
                run.context = {**(run.context or {}), **outcome.context_updates}
                if outcome.status == "success":
                    next_step = step.get("on_success")
                elif outcome.status == "failure":
                    retry_key = f"_retry_{step_id}"
                    attempt = run.context.get(retry_key, 0)
                    if attempt < step.get("retries", 0):
                        run.context = {**run.context, retry_key: attempt + 1}
                        next_step = step_id
                    else:
                        next_step = step.get("on_failure")
                        if next_step is None:
                            run.status = PipelineRunStatus.FAILED
                else:
                    next_step = None
                    run.status = PipelineRunStatus.FAILED

                # Result, context, next position and child release are one commit.
                # There is no window where a completed child/action can be replayed
                # just because its identity was removed before the checkpoint.
                run.current_step_id = next_step
                run.current_task_id = None
                run.current_child_run_id = None
                run.execution_phase = "ready"
                run.step_started_at = None
                if next_step is None:
                    if run.status != PipelineRunStatus.FAILED:
                        run.status = PipelineRunStatus.COMPLETED
                    run.finished_at = now
                await db.commit()
                if next_step is None or run.status == PipelineRunStatus.PAUSED:
                    return
