"""Immutable identifiers captured only after server-side authentication."""
from dataclasses import dataclass
from uuid import UUID

TASK_EXECUTION_REQUESTED = "task.execution_requested"
TASK_AGENT_RESULT = "task.agent_result"


@dataclass(frozen=True, slots=True)
class AuditIdentity:
    org_id: UUID
    user_id: UUID | None
