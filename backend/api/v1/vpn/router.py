# backend/api/v1/vpn/router.py  TZ-06 SPLIT-1..5
# SPLIT-1: AWG Config Builder (keypair, config-preview)
# SPLIT-2: Pool Manager (assign, revoke)
# SPLIT-3: Self-Healing (health monitor via background task)
# SPLIT-4: Kill Switch (command dispatch)
# SPLIT-5: Full VPN REST API
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.dependencies import require_permission, require_role
from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.schemas.vpn import (
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
from backend.schemas.vpn.config import (
    AWGConfigPreviewRequest,
    AWGConfigPreviewResponse,
    AWGKeypairResponse,
    AWGObfuscationParamsSchema,
)
from backend.services.vpn.awg_config import AWGConfigBuilder, AWGObfuscationParams
from backend.services.vpn.dependencies import get_awg_config_builder, get_key_cipher
from backend.services.vpn.event_publisher import EventPublisher
from backend.services.vpn.ip_pool import IPPoolAllocator
from backend.services.vpn.killswitch_service import KillSwitchService
from backend.services.vpn.pool_service import VPNPoolService

router = APIRouter(prefix="/vpn", tags=["vpn"])

# Register background health loop (SPLIT-3) — side-effect on import
import backend.tasks.vpn_health  # noqa: F401, E402

# ---------------------------------------------------------------------------
# DI factories for SPLIT-2..5
# ---------------------------------------------------------------------------

def get_ip_pool(redis=Depends(get_redis)) -> IPPoolAllocator:
    return IPPoolAllocator(redis, subnet=settings.VPN_POOL_SUBNET)


async def get_pool_service(
    db: AsyncSession = Depends(get_db),
    ip_pool: IPPoolAllocator = Depends(get_ip_pool),
    builder: AWGConfigBuilder = Depends(get_awg_config_builder),
    cipher: Fernet = Depends(get_key_cipher),
):
    service = VPNPoolService(
        db=db,
        ip_pool=ip_pool,
        config_builder=builder,
        key_cipher=cipher,
        wg_router_url=settings.WG_ROUTER_URL,
        wg_router_api_key=settings.WG_ROUTER_API_KEY,
    )
    try:
        yield service
    finally:
        await service.close()


def get_killswitch_service() -> KillSwitchService:
    return KillSwitchService(EventPublisher())


# ---------------------------------------------------------------------------
# SPLIT-1: AWG Config Builder (admin/dev endpoints)
# ---------------------------------------------------------------------------

@router.post(
    "/admin/keypair",
    response_model=AWGKeypairResponse,
    summary="Generate WireGuard keypair",
)
async def generate_keypair(
    builder: AWGConfigBuilder = Depends(get_awg_config_builder),
) -> AWGKeypairResponse:
    _private, public = builder.generate_keypair()
    return AWGKeypairResponse(public_key=public)


@router.post(
    "/admin/config-preview",
    response_model=AWGConfigPreviewResponse,
    summary="Preview AWG config (dev/test only)",
)
async def preview_config(
    request: AWGConfigPreviewRequest,
    builder: AWGConfigBuilder = Depends(get_awg_config_builder),
) -> AWGConfigPreviewResponse:
    if not settings.DEBUG and settings.ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="config-preview not available in production",
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
    return AWGConfigPreviewResponse(
        public_key=public_key,
        tunnel_ip=request.assigned_ip,
        config_text=config_text,
        qr_code_b64=builder.to_qr_code(config_text),
        obfuscation=AWGObfuscationParamsSchema(**obfuscation.model_dump()),
    )


# ---------------------------------------------------------------------------
# SPLIT-5: VPN Pool Management API
# ---------------------------------------------------------------------------

@router.post(
    "/assign",
    response_model=VPNAssignResponse,
    summary="Assign VPN peer to device",
)
async def assign_vpn(
    req: VPNAssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("org_admin")),
    pool_service: VPNPoolService = Depends(get_pool_service),
) -> VPNAssignResponse:
    try:
        assignment = await pool_service.assign_vpn(
            device_id=str(req.device_id),
            org_id=current_user.org_id,
            split_tunnel=req.split_tunnel,
        )
        await db.commit()
        return VPNAssignResponse(
            peer_id=uuid.UUID(assignment.peer_id),
            device_id=uuid.UUID(assignment.device_id),
            assigned_ip=assignment.assigned_ip,
            public_key=assignment.public_key,
            config=assignment.config,
            qr_code=assignment.qr_code,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"VPN assignment failed: {exc}")


@router.delete(
    "/revoke/{device_id}",
    status_code=204,
    response_model=None,
    summary="Revoke VPN peer of device",
)
async def revoke_vpn(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("org_admin")),
    pool_service: VPNPoolService = Depends(get_pool_service),
):
    await pool_service.revoke_vpn(str(device_id), current_user.org_id)
    await db.commit()


@router.get(
    "/health",
    summary="VPN subsystem health check",
)
async def vpn_health(
    current_user=require_permission("vpn:read"),
) -> dict:
    return {
        "status": "ok",
        "checks": {
            "vpn_service": {"status": "ok"},
        },
    }


@router.get(
    "/peers",
    response_model=list[VPNPeerResponse],
    summary="List VPN peers",
)
async def list_peers(
    peer_status: str | None = Query(None, alias="status", description="free|assigned|error"),
    device_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("vpn:read"),
) -> list[VPNPeerResponse]:
    query = select(VPNPeer).where(VPNPeer.org_id == current_user.org_id)

    if peer_status:
        try:
            query = query.where(VPNPeer.status == VPNPeerStatus(peer_status))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {peer_status}")
    if device_id:
        query = query.where(VPNPeer.device_id == uuid.UUID(device_id))

    result = await db.execute(query)
    stale_threshold = datetime.now(timezone.utc) - timedelta(seconds=180)
    return [
        VPNPeerResponse(
            id=p.id,
            device_id=p.device_id,
            assigned_ip=p.tunnel_ip,
            status=p.status.value if isinstance(p.status, VPNPeerStatus) else p.status,
            is_active=bool(p.is_active and p.last_handshake_at and p.last_handshake_at > stale_threshold),
            public_key=p.public_key,
            last_handshake_at=p.last_handshake_at,
            created_at=p.created_at,
        )
        for p in result.scalars().all()
    ]


@router.get(
    "/pool/stats",
    response_model=VPNPoolStats,
    summary="VPN pool statistics",
)
async def pool_stats(
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("vpn:read"),
    ip_pool: IPPoolAllocator = Depends(get_ip_pool),
) -> VPNPoolStats:
    org_id = current_user.org_id
    free = await ip_pool.pool_size(str(org_id))

    allocated = await db.scalar(
        select(func.count(VPNPeer.id)).where(
            VPNPeer.org_id == org_id,
            VPNPeer.status == VPNPeerStatus.ASSIGNED,
        )
    ) or 0

    active = await db.scalar(
        select(func.count(VPNPeer.id)).where(
            VPNPeer.org_id == org_id,
            VPNPeer.is_active == True,  # noqa: E712
        )
    ) or 0

    stale_threshold = datetime.now(timezone.utc) - timedelta(seconds=180)
    stale = await db.scalar(
        select(func.count(VPNPeer.id)).where(
            VPNPeer.org_id == org_id,
            VPNPeer.status == VPNPeerStatus.ASSIGNED,
            VPNPeer.last_handshake_at < stale_threshold,
        )
    ) or 0

    return VPNPoolStats(
        total_ips=free + allocated,
        allocated=allocated,
        free=free,
        active_tunnels=active,
        stale_handshakes=stale,
    )


@router.post(
    "/rotate",
    response_model=VPNBulkRotateResponse,
    summary="Bulk rotate VPN IPs",
)
async def bulk_rotate(
    req: VPNBulkRotateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("org_admin")),
    pool_service: VPNPoolService = Depends(get_pool_service),
) -> VPNBulkRotateResponse:
    device_ids: list[uuid.UUID] = list(req.device_ids)
    if not device_ids:
        result = await db.execute(
            select(VPNPeer.device_id).where(
                VPNPeer.org_id == current_user.org_id,
                VPNPeer.status == VPNPeerStatus.ASSIGNED,
                VPNPeer.device_id.isnot(None),
            )
        )
        device_ids = [r[0] for r in result.all()]

    details: list[RotateDetail] = []
    success = 0
    failed = 0

    for dev_id in device_ids:
        try:
            peer = await db.scalar(
                select(VPNPeer).where(
                    VPNPeer.device_id == dev_id,
                    VPNPeer.org_id == current_user.org_id,
                    VPNPeer.status == VPNPeerStatus.ASSIGNED,
                )
            )
            old_ip = peer.tunnel_ip if peer else None

            await pool_service.revoke_vpn(str(dev_id), current_user.org_id)
            assignment = await pool_service.assign_vpn(
                str(dev_id), current_user.org_id, split_tunnel=True
            )
            details.append(RotateDetail(
                device_id=dev_id,
                old_ip=old_ip,
                new_ip=assignment.assigned_ip,
                error=None,
            ))
            success += 1
        except Exception as exc:
            details.append(RotateDetail(
                device_id=dev_id,
                old_ip=None,
                new_ip=None,
                error=str(exc),
            ))
            failed += 1

    await db.commit()
    return VPNBulkRotateResponse(
        total=len(device_ids),
        success=success,
        failed=failed,
        details=details,
    )


@router.post(
    "/killswitch",
    response_model=KillSwitchResponse,
    summary="Enable/disable Kill Switch on devices",
)
async def manage_killswitch(
    req: KillSwitchRequest,
    current_user=Depends(require_role("org_admin")),
    ks_service: KillSwitchService = Depends(get_killswitch_service),
) -> KillSwitchResponse:
    if req.action not in ("enable", "disable"):
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    if req.action == "enable":
        results = await ks_service.bulk_enable(
            req.device_ids, settings.WG_SERVER_ENDPOINT, req.method
        )
    else:
        results = await ks_service.bulk_disable(req.device_ids)

    return KillSwitchResponse(
        action=req.action,
        total=len(req.device_ids),
        success=sum(1 for v in results.values() if v),
        results=results,
    )
