# backend/schemas/vpn/peer.py — TZ-06 SPLIT-5
# Pydantic schemas для VPN Pool Manager и REST API.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── Assign / Revoke ──────────────────────────────────────────────────────────

class VPNAssignRequest(BaseModel):
    device_id: uuid.UUID
    split_tunnel: bool = Field(True, description="True = весь трафик через VPN (0.0.0.0/0)")


class VPNAssignResponse(BaseModel):
    peer_id: uuid.UUID
    device_id: uuid.UUID
    assigned_ip: str
    public_key: str | None = None
    config: str = Field(..., description="AmneziaWG .conf для клиента")
    qr_code: str = Field(..., description="Base64 PNG QR-код")


# ── Peer listing ─────────────────────────────────────────────────────────────

class VPNPeerResponse(BaseModel):
    id: uuid.UUID
    device_id: uuid.UUID | None
    assigned_ip: str | None = Field(None, validation_alias="tunnel_ip")
    status: str
    is_active: bool = False
    public_key: str
    last_handshake_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


# ── Pool stats ────────────────────────────────────────────────────────────────

class VPNPoolStats(BaseModel):
    total_ips: int = Field(..., description="Всего IP в подсети (allocated + free)")
    allocated: int = Field(..., description="Назначено устройствам")
    free: int = Field(..., description="Свободно в Redis пуле")
    active_tunnels: int = Field(..., description="Туннели с handshake < 3 мин")
    stale_handshakes: int = Field(..., description="Туннели с handshake > 3 мин")


# ── Bulk rotate ───────────────────────────────────────────────────────────────

class VPNBulkRotateRequest(BaseModel):
    device_ids: list[uuid.UUID] = Field(
        default=[], description="Пустой список = ротация всех устройств org"
    )
    reason: str = "scheduled_rotation"


class RotateDetail(BaseModel):
    device_id: uuid.UUID
    old_ip: str | None
    new_ip: str | None
    error: str | None


class VPNBulkRotateResponse(BaseModel):
    total: int
    success: int
    failed: int
    details: list[RotateDetail]


# ── Kill Switch ───────────────────────────────────────────────────────────────

class KillSwitchRequest(BaseModel):
    device_ids: list[str]
    action: str = Field("enable", description="enable | disable")
    method: str = Field("vpnservice", description="vpnservice (no-root) | iptables (root required)")


class KillSwitchResponse(BaseModel):
    action: str
    total: int
    success: int
    results: dict[str, bool]
