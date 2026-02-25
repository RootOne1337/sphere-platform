# backend/services/vpn/pool_service.py  TZ-06 SPLIT-2
from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import structlog
from circuitbreaker import circuit
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    Instantiated per-request via FastAPI Depends.
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
        """Assign a VPN peer to a device. Idempotent  returns existing if already assigned."""
        existing = await self._get_existing_peer(device_id, org_id)
        if existing:
            return await self._peer_to_assignment(existing, split_tunnel)

        assigned_ip = await self.ip_pool.allocate_ip(str(org_id))
        if not assigned_ip:
            raise HTTPException(status_code=503, detail="VPN pool exhausted")

        try:
            private_key, public_key = self.config_builder.generate_keypair()
            obfuscation = AWGObfuscationParams.generate_random()
            psk = (
                self.config_builder.generate_psk()
                if self.config_builder.server_psk_enabled
                else None
            )
            await self._add_peer_to_server(public_key, assigned_ip, psk)

            device_uuid = uuid.UUID(device_id) if isinstance(device_id, str) else device_id
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
                status=VPNPeerStatus.ASSIGNED,
            )
            self.db.add(peer)
            await self.db.flush()

            config_text = self.config_builder.build_client_config(
                private_key, assigned_ip, obfuscation, psk, split_tunnel
            )
            return VPNAssignment(
                peer_id=str(peer.id),
                device_id=device_id,
                assigned_ip=assigned_ip,
                config=config_text,
                qr_code=self.config_builder.to_qr_code(config_text),
                public_key=public_key,
            )
        except Exception:
            # Always return IP to pool on any failure
            await self.ip_pool.release_ip(str(org_id), assigned_ip)
            raise

    async def revoke_vpn(self, device_id: str, org_id: uuid.UUID) -> None:
        """Revoke VPN for a device; return IP to pool and mark peer FREE."""
        peer = await self._get_existing_peer(device_id, org_id)
        if not peer:
            return

        await self._remove_peer_from_server(peer.public_key)
        if peer.tunnel_ip:
            await self.ip_pool.release_ip(str(org_id), peer.tunnel_ip)

        peer.status = VPNPeerStatus.FREE
        peer.device_id = None
        peer.is_active = False

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
                VPNPeer.status == VPNPeerStatus.ASSIGNED,
            )
        )
        return result.scalar_one_or_none()

    async def _peer_to_assignment(
        self, peer: VPNPeer, split_tunnel: bool = True
    ) -> VPNAssignment:
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
        config = self.config_builder.build_client_config(
            private_key=decrypted_private,
            assigned_ip=peer.tunnel_ip or "0.0.0.0",
            obfuscation=obfuscation,
            split_tunnel=split_tunnel,
        )
        return VPNAssignment(
            peer_id=str(peer.id),
            device_id=str(peer.device_id),
            assigned_ip=peer.tunnel_ip or "",
            config=config,
            qr_code=self.config_builder.to_qr_code(config),
            public_key=peer.public_key,
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
        """DELETE /peers/{public_key} on WG Router API (best-effort, won't raise)."""
        try:
            resp = await self._http.delete(f"/peers/{public_key}")
            if resp.status_code not in (200, 204, 404):
                logger.warning(
                    "WG Router remove peer unexpected status",
                    public_key=public_key,
                    status=resp.status_code,
                )
        except Exception as exc:
            logger.warning("Failed to remove peer from WG server", exc=str(exc))
