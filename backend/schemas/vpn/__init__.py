# backend/schemas/vpn/__init__.py — TZ-06 VPN schemas
from backend.schemas.vpn.config import (
    AWGConfigPreviewRequest,
    AWGConfigPreviewResponse,
    AWGKeypairResponse,
    AWGObfuscationParamsSchema,
)
from backend.schemas.vpn.peer import (
    KillSwitchRequest,
    KillSwitchResponse,
    RotateDetail,
    VPNAssignRequest,
    VPNAssignResponse,
    VPNBulkRotateRequest,
    VPNBulkRotateResponse,
    VPNPeerResponse,
    VPNPoolStats,
)

__all__ = [
    "AWGObfuscationParamsSchema",
    "AWGKeypairResponse",
    "AWGConfigPreviewRequest",
    "AWGConfigPreviewResponse",
    "VPNAssignRequest",
    "VPNAssignResponse",
    "VPNPeerResponse",
    "VPNPoolStats",
    "VPNBulkRotateRequest",
    "VPNBulkRotateResponse",
    "RotateDetail",
    "KillSwitchRequest",
    "KillSwitchResponse",
]
