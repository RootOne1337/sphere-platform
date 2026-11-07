"""Read-only, tenant-scoped coverage; availability is not data-plane health."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CoverageSignal(BaseModel):
    state: Literal["ready", "unavailable", "forbidden", "limited", "unmeasured"]
    source: str
    observed_at: datetime | None = None
    counts: dict[str, int] | None = Field(None, description="Null when the source was not measured; measured zero remains zero")
    reason: str = ""
    max_age_seconds: int | None = None


class FleetCoverageResponse(BaseModel):
    schema_version: Literal[1] = 1
    scope: Literal["current-tenant-active-inventory"] = "current-tenant-active-inventory"
    org_id: uuid.UUID
    generated_at: datetime
    max_inventory_devices: int
    inventory: CoverageSignal
    presence: CoverageSignal
    android_vpn: CoverageSignal
    vpn_assignment: CoverageSignal
    handshakes: CoverageSignal
    transport_tunnels: CoverageSignal
