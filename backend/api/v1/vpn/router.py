# backend/api/v1/vpn/router.py — TZ-06 SPLIT-1
# VPN API v1 — AWG Config Builder endpoints.
# SPLIT-1: keypair generation + config preview (admin/dev).
# SPLIT-2: pool management (assign IPs, provision peers).
# SPLIT-3: self-healing.  SPLIT-4: kill switch.  SPLIT-5: full VPN API.
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.core.config import settings
from backend.schemas.vpn.config import (
    AWGConfigPreviewRequest,
    AWGConfigPreviewResponse,
    AWGKeypairResponse,
    AWGObfuscationParamsSchema,
)
from backend.services.vpn.awg_config import AWGConfigBuilder, AWGObfuscationParams
from backend.services.vpn.dependencies import get_awg_config_builder

router = APIRouter(prefix="/vpn", tags=["vpn"])


@router.post(
    "/admin/keypair",
    response_model=AWGKeypairResponse,
    summary="Сгенерировать WireGuard keypair",
    description=(
        "Генерирует новый X25519 keypair. "
        "Private key НИКОГДА не возвращается через API — используется только внутри сервиса."
    ),
)
async def generate_keypair(
    builder: AWGConfigBuilder = Depends(get_awg_config_builder),
) -> AWGKeypairResponse:
    _private, public = builder.generate_keypair()
    return AWGKeypairResponse(public_key=public)


@router.post(
    "/admin/config-preview",
    response_model=AWGConfigPreviewResponse,
    summary="Предпросмотр AWG конфига (dev/test only)",
    description=(
        "Генерирует полный клиентский конфиг и QR-код без сохранения в БД. "
        "Только для разработки и тестирования."
    ),
)
async def preview_config(
    request: AWGConfigPreviewRequest,
    builder: AWGConfigBuilder = Depends(get_awg_config_builder),
) -> AWGConfigPreviewResponse:
    if not settings.DEBUG and settings.ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="config-preview недоступен в production окружении",
        )

    private_key, public_key = builder.generate_keypair()
    obfuscation = AWGObfuscationParams.generate_random()
    psk = builder.generate_psk() if request.include_psk else None

    config_text = builder.build_client_config(
        private_key=private_key,
        assigned_ip=request.assigned_ip,
        obfuscation=obfuscation,
        psk=psk,
        split_tunnel=request.split_tunnel,
    )
    qr_code_b64 = builder.to_qr_code(config_text)

    return AWGConfigPreviewResponse(
        public_key=public_key,
        tunnel_ip=request.assigned_ip,
        config_text=config_text,
        qr_code_b64=qr_code_b64,
        obfuscation=AWGObfuscationParamsSchema(**obfuscation.model_dump()),
    )
