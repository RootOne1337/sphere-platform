"""Session-owned UI hints; every operation still uses its own server guard."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SessionCapabilities(BaseModel):
    schema_version: Literal[1] = 1
    user_id: UUID
    org_id: UUID
    role: str
    permissions: list[str]
