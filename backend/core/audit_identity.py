"""Immutable identifiers captured only after server-side authentication."""
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuditIdentity:
    org_id: UUID
    user_id: UUID | None
