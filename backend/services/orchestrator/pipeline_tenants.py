"""Bounded worker discovery followed by one trusted tenant per SQL session."""

import uuid
from contextlib import asynccontextmanager

from sqlalchemy import and_, or_, select, text

from backend.database.tenant import bind_tenant_context
from backend.models.pipeline import PipelineRun, PipelineRunStatus
from backend.services.orchestrator.pipeline_ownership import database_now


def tenant_sessions(sessions, org_id: uuid.UUID):
    @asynccontextmanager
    async def factory():
        async with sessions() as db:
            await bind_tenant_context(db, str(org_id))
            yield db
    return factory


async def discover_work(sessions, kind: str, *, org_id: uuid.UUID | None = None):
    if kind not in {"queued", "recovery", "cancel"}:
        raise ValueError("Unsupported pipeline work kind")
    if org_id is None:
        async with sessions() as db:
            return list((await db.execute(text(
                "SELECT * FROM sphere_auth.pipeline_work(:kind)"
            ), {"kind": kind})).all())
    async with tenant_sessions(sessions, org_id)() as db:
        now = await database_now(db)
        conditions = {
            "queued": and_(PipelineRun.status == PipelineRunStatus.QUEUED,
                           PipelineRun.cancel_requested_at.is_(None)),
            "cancel": and_(PipelineRun.cancel_requested_at.is_not(None), PipelineRun.status.in_([
                PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING, PipelineRunStatus.WAITING, PipelineRunStatus.PAUSED,
            ])),
            "recovery": recovery_predicate(now),
        }
        order = PipelineRun.created_at if kind == "queued" else PipelineRun.updated_at
        return list((await db.execute(select(PipelineRun.id, PipelineRun.org_id).where(
            PipelineRun.org_id == org_id, conditions[kind],
        ).order_by(order, PipelineRun.id).limit(64))).all())


def recovery_predicate(now):
    return and_(
        PipelineRun.cancel_requested_at.is_(None),
        or_(PipelineRun.status.in_([PipelineRunStatus.RUNNING, PipelineRunStatus.WAITING]),
            and_(PipelineRun.status == PipelineRunStatus.PAUSED, PipelineRun.execution_owner.is_not(None))),
        or_(PipelineRun.execution_owner.is_(None), PipelineRun.execution_lease_until.is_(None),
            PipelineRun.execution_lease_until <= now),
    )
