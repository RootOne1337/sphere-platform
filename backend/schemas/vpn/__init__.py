# backend/schemas/vpn/__init__.py — TZ-06 VPN schemas
from backend.schemas.vpn.config import (
    AWGObfuscationParamsSchema,
    AWGKeypairResponse,
    AWGConfigPreviewRequest,
    AWGConfigPreviewResponse,
)
from backend.schemas.vpn.peer import (
    VPNAssignRequest,
    VPNAssignResponse,
    VPNPeerResponse,
    VPNPoolStats,
    VPNBulkRotateRequest,
    VPNBulkRotateResponse,
    RotateDetail,
    KillSwitchRequest,
    KillSwitchResponse,
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
