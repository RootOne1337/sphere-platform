# backend/services/audit_log_service.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-5. Прямые вызовы из бизнес-логики для детальных событий.
# Middleware автоматически пишет для HTTP-запросов — см. backend/middleware/audit.py.
from __future__ import annotations

import re
import uuid
from typing import Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.audit_identity import TASK_AGENT_RESULT, TASK_EXECUTION_REQUESTED
from backend.middleware.request_id import REQUEST_ID_PATTERN
from backend.models.audit_log import AuditLog
from backend.models.task import Task

AgentOutcome = Literal["completed", "failed", "cancelled", "unknown"]
_AGENT_OUTCOME_STATUS = {"completed": "success", "failed": "failure", "cancelled": "warning", "unknown": "unknown"}


def _valid_request_id(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(REQUEST_ID_PATTERN, value) else None

logger = structlog.get_logger()


class AuditLogService:
    """
    Фиксировать события в audit_logs в рамках ТЕКУЩЕЙ транзакции.
    Используется из сервисного слоя для детальных событий с diff (old/new values).
    Generic log() attempts a flush without commit. Task receipts use the
    surrounding transaction so an aborted write cannot acknowledge an outcome.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def record_task_request(self, task: Task, user_id: uuid.UUID) -> None:
        """Persist authenticated admission with the queued task, using its assigned ID."""
        meta = {"status": "success", "device_id": str(task.device_id)}
        request_id = _valid_request_id(structlog.contextvars.get_contextvars().get("request_id"))
        if request_id:
            meta["request_id"] = request_id
        self.db.add(AuditLog(
            org_id=task.org_id, user_id=user_id, action=TASK_EXECUTION_REQUESTED,
            resource_type="task", resource_id=str(task.id), meta=meta,
        ))

    async def record_agent_result(self, task: Task, outcome: AgentOutcome) -> None:
        """Append the agent's report inside the same task transaction and row lock."""
        # WebSocket results carry the admitted command's UUID. Keep the agent as
        # the source and show the initiating user separately when one is known.
        task_id = str(task.id)
        meta = {
            "status": _AGENT_OUTCOME_STATUS[outcome], "agent_outcome": outcome,
            "receipt_id": task_id, "device_id": str(task.device_id),
        }
        admission = (await self.db.execute(select(
            AuditLog.user_id, AuditLog.meta["request_id"].as_string(),
        ).where(
            AuditLog.org_id == task.org_id, AuditLog.resource_id == task_id,
            AuditLog.resource_type == "task", AuditLog.action == TASK_EXECUTION_REQUESTED,
        ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(1))).one_or_none()
        if admission is not None:
            requested_by, request = admission
            if requested_by is not None:
                meta["requested_by"] = str(requested_by)
            request_id = _valid_request_id(request)
            if request_id:
                meta["request_id"] = request_id
        self.db.add(AuditLog(
            org_id=task.org_id, action=TASK_AGENT_RESULT,
            resource_type="task", resource_id=task_id, meta=meta,
        ))

    async def log(
        self,
        action: str,
        *,
        org_id=None,
        user_id=None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        status: str = "success",
        duration_ms: int | None = None,
    ) -> None:
        """
        Записать audit event.
        status и duration_ms хранятся в поле meta (модель не имеет отдельных колонок для них).
        """
        try:
            meta: dict = {"status": status}
            if duration_ms is not None:
                meta["duration_ms"] = duration_ms
            request_id = _valid_request_id(structlog.contextvars.get_contextvars().get("request_id"))
            if request_id:
                meta["request_id"] = request_id

            entry = AuditLog(
                org_id=org_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                ip_address=ip_address,
                user_agent=user_agent,
                old_value=old_values,
                new_value=new_values,
                meta=meta,
            )
            self.db.add(entry)
            await self.db.flush()
        except Exception as exc:
            logger.error(
                "audit_log_failed",
                error_type=type(exc).__name__,
                action=action,
                org_id=str(org_id) if org_id else None,
                user_id=str(user_id) if user_id else None,
            )
