# backend/services/vpn/pool_service.py  TZ-06 SPLIT-2
from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import quote

import httpx
import structlog
from circuitbreaker import circuit
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.services.vpn.awg_config import AWGConfigBuilder, AWGObfuscationParams
from backend.services.vpn.ip_pool import IPPoolAllocator

logger = structlog.get_logger()


@dataclass
class VPNAssignment:
    peer_id: str
    device_id: str
    assigned_ip: str
    config: str    # AmneziaWG .conf text
    qr_code: str   # Base64 PNG QR-code
    public_key: str = ""  # WireGuard public key


class VPNPoolService:
    """
    Manages VPN peer lifecycle: allocate IPs, provision WG peers, revoke.
    Owns commits on a dedicated session supplied by lifecycle DI. Do not pass a
    caller's session containing unrelated pending writes. Health observation may
    reuse only the pure configuration helpers on its own session.
    """

    def __init__(
        self,
        db: AsyncSession,
        ip_pool: IPPoolAllocator,
        config_builder: AWGConfigBuilder,
        key_cipher: Fernet,
        wg_router_url: str,
        wg_router_api_key: str = "",
    ) -> None:
        self.db = db
        self.ip_pool = ip_pool
        self.config_builder = config_builder
        self.key_cipher = key_cipher
        self.wg_router_url = wg_router_url
        self.wg_router_api_key = wg_router_api_key
        # Reuse single AsyncClient to avoid per-call TCP handshake
        headers = {"X-API-Key": wg_router_api_key} if wg_router_api_key else {}
        self._http = httpx.AsyncClient(
            base_url=wg_router_url,
            timeout=httpx.Timeout(10.0),
            headers={"Content-Type": "application/json", **headers},
        )

    async def close(self) -> None:
        await self._http.aclose()

    # aclose is an alias for close — supports both asyncio and httpx teardown conventions
    aclose = close

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def assign_vpn(
        self,
        device_id: str,
        org_id: uuid.UUID,
        split_tunnel: bool = True,
    ) -> VPNAssignment:
        """Commit reservation before provisioning; unknown outcomes retain the IP."""
        try:
            return await self._assign_vpn(device_id, org_id, split_tunnel)
        except BaseException:
            await self.db.rollback()
            raise

    async def _assign_vpn(self, device_id: str, org_id: uuid.UUID, split_tunnel: bool) -> VPNAssignment:
        device_uuid = uuid.UUID(device_id) if isinstance(device_id, str) else device_id
        owned = await self.db.scalar(select(Device.id).where(
            Device.id == device_uuid, Device.org_id == org_id, Device.is_active.is_(True),
        ).with_for_update())
        if owned is None:
            raise HTTPException(status_code=404, detail="Device not found")
        existing = await self._get_existing_peer(device_id, org_id)
        if existing:
            if existing.status != VPNPeerStatus.ASSIGNED:
                raise HTTPException(status_code=409, detail="VPN operation requires reconciliation")
            assignment = await self._peer_to_assignment(existing)
            await self.db.commit()
            return assignment

        assigned_ip = await self.ip_pool.reserve_ip(self.db)
        if not assigned_ip:
            raise HTTPException(status_code=503, detail="VPN pool exhausted")

        private_key, public_key = self.config_builder.generate_keypair()
        obfuscation = AWGObfuscationParams.generate_random()
        psk = self.config_builder.generate_psk() if self.config_builder.server_psk_enabled else None
        operation_id = uuid.uuid4()
        peer = VPNPeer(
            org_id=org_id,
            device_id=device_uuid,
            tunnel_ip=assigned_ip,
            public_key=public_key,
            private_key_enc=self.key_cipher.encrypt(private_key.encode()),
            preshared_key_enc=self.key_cipher.encrypt(psk.encode()) if psk else None,
            awg_jc=obfuscation.jc,
            awg_jmin=obfuscation.jmin,
            awg_jmax=obfuscation.jmax,
            awg_s1=obfuscation.s1,
            awg_s2=obfuscation.s2,
            awg_h1=obfuscation.h1,
            awg_h2=obfuscation.h2,
            awg_h3=obfuscation.h3,
            awg_h4=obfuscation.h4,
            status=VPNPeerStatus.PROVISIONING,
            is_active=False,
            operation_id=operation_id,
            split_tunnel=split_tunnel,
        )
        self.db.add(peer)
        await self.db.flush()
        assignment = await self._peer_to_assignment(peer)
        peer_id = peer.id
        await self.db.commit()
        # No SQL row/advisory locks are held across provider IO. A timeout or
        # crash leaves PROVISIONING intact; blind retry/release is forbidden.
        await self._add_peer_to_server(public_key, assigned_ip, psk)
        completed = await self.db.scalar(update(VPNPeer).where(
            VPNPeer.id == peer_id, VPNPeer.org_id == org_id,
            VPNPeer.operation_id == operation_id,
            VPNPeer.status == VPNPeerStatus.PROVISIONING,
        ).values(status=VPNPeerStatus.ASSIGNED).returning(VPNPeer.id))
        if completed is None:
            raise HTTPException(status_code=409, detail="VPN operation changed; reconciliation required")
        await self.db.commit()
        return assignment

    async def revoke_vpn(self, device_id: str, org_id: uuid.UUID) -> None:
        """Release ownership only after confirmed DELETE and a durable SQL commit."""
        try:
            await self._revoke_vpn(device_id, org_id)
        except BaseException:
            await self.db.rollback()
            raise

    async def _revoke_vpn(self, device_id: str, org_id: uuid.UUID) -> None:
        peer = await self._get_existing_peer(device_id, org_id)
        if not peer:
            await self.db.commit()
            return
        if peer.status != VPNPeerStatus.ASSIGNED:
            raise HTTPException(status_code=409, detail="VPN operation requires reconciliation")
        operation_id = uuid.uuid4()
        peer.operation_id = operation_id
        peer.status = VPNPeerStatus.REVOKING
        peer.is_active = False
        peer_id, public_key = peer.id, peer.public_key
        await self.db.commit()
        await self._remove_peer_from_server(public_key)
        completed = await self.db.scalar(update(VPNPeer).where(
            VPNPeer.id == peer_id, VPNPeer.org_id == org_id,
            VPNPeer.operation_id == operation_id,
            VPNPeer.status == VPNPeerStatus.REVOKING,
        ).values(status=VPNPeerStatus.FREE, device_id=None, is_active=False).returning(VPNPeer.id))
        if completed is None:
            raise HTTPException(status_code=409, detail="VPN operation changed; reconciliation required")
        await self.db.commit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_existing_peer(
        self, device_id: str, org_id: uuid.UUID
    ) -> VPNPeer | None:
        device_uuid = uuid.UUID(device_id) if isinstance(device_id, str) else device_id
        result = await self.db.execute(
            select(VPNPeer).where(
                VPNPeer.device_id == device_uuid,
                VPNPeer.org_id == org_id,
                VPNPeer.status != VPNPeerStatus.FREE,
            ).with_for_update().execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def _peer_to_assignment(
        self, peer: VPNPeer, split_tunnel: bool | None = None
    ) -> VPNAssignment:
        config = self.build_peer_config(peer, split_tunnel)
        return VPNAssignment(
            peer_id=str(peer.id),
            device_id=str(peer.device_id),
            assigned_ip=peer.tunnel_ip or "",
            config=config,
            qr_code=self.config_builder.to_qr_code(config),
            public_key=peer.public_key,
        )

    def build_peer_config(self, peer: VPNPeer, split_tunnel: bool | None = None) -> str:
        """Build retry/reconnect configuration from the same persisted credentials."""
        decrypted_private = self.key_cipher.decrypt(peer.private_key_enc).decode()
        obfuscation = AWGObfuscationParams(
            jc=peer.awg_jc or 4,
            jmin=peer.awg_jmin or 0,
            jmax=peer.awg_jmax or 1,
            s1=peer.awg_s1 or 1,
            s2=peer.awg_s2 or 1,
            h1=peer.awg_h1 or 1,
            h2=peer.awg_h2 or 1,
            h3=peer.awg_h3 or 1,
            h4=peer.awg_h4 or 1,
        )
        return self.config_builder.build_client_config(
            private_key=decrypted_private,
            assigned_ip=peer.tunnel_ip or "0.0.0.0",
            obfuscation=obfuscation,
            psk=self.key_cipher.decrypt(peer.preshared_key_enc).decode() if peer.preshared_key_enc else None,
            split_tunnel=peer.split_tunnel if peer.split_tunnel is not None else (
                split_tunnel if split_tunnel is not None else True
            ),
        )

    @circuit(failure_threshold=5, recovery_timeout=30)
    async def _add_peer_to_server(
        self, public_key: str, ip: str, psk: str | None
    ) -> None:
        """POST /peers on WireGuard Router API. Circuit-breaker: 5 failures  30s cooldown."""
        payload: dict = {"public_key": public_key, "allowed_ip": f"{ip}/32"}
        if psk:
            payload["psk"] = psk
        resp = await self._http.post("/peers", json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"WG Router error {resp.status_code}: {resp.text}")

    async def _remove_peer_from_server(self, public_key: str) -> None:
        """Require confirmed deletion before the caller may release the address."""
        resp = await self._http.delete(f"/peers/{quote(public_key, safe='')}")
        if resp.status_code not in (200, 204):
            # In particular, 202 only acknowledges a request; it does not prove
            # the peer is gone. A generic 404 can be a proxy/route error, not an
            # authoritative absent-peer result. Retain the intent for reconciliation.
            raise httpx.HTTPStatusError(
                "WG Router did not confirm peer deletion",
                request=resp.request, response=resp,
            )
