# backend/schemas/vpn/__init__.py — TZ-06 VPN schemas
from backend.schemas.vpn.config import (
    AWGObfuscationParamsSchema,
    AWGKeypairResponse,
    AWGConfigPreviewRequest,
    AWGConfigPreviewResponse,
)

__all__ = [
    "AWGObfuscationParamsSchema",
    "AWGKeypairResponse",
    "AWGConfigPreviewRequest",
    "AWGConfigPreviewResponse",
]
