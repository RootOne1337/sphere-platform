# backend/services/vpn/health_monitor.py  TZ-06 SPLIT-3
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.services.vpn.awg_config import AWGObfuscationParams
from backend.services.vpn.event_publisher import EventPublisher

logger = structlog.get_logger()


class NoopCommandPublisher:
    """Stub for DeviceCommandPublisher until TZ-03 WebSocket Layer is merged."""

    async def send_command_to_device(self, device_id: str, command: dict) -> bool:
        logger.debug("noop: command not sent", device_id=device_id, type=command.get("type"))
        return False

    async def is_device_online(self, device_id: str) -> bool:
        return False


class VPNHealthMonitor:
    """
    Checks VPN tunnel health by polling WG Router handshake timestamps.
    Triggers reconnect commands for stale or missing peers.
    Run every 60 s via vpn_health_loop background task.
    """

    STALE_HANDSHAKE_THRESHOLD = 180  # seconds (3 minutes)

    def __init__(
        self,
        db: AsyncSession,
        pool_service,   # VPNPoolService  avoids circular import via type str
        publisher: EventPublisher,
        wg_router_url: str,
        redis=None,
    ) -> None:
        self.db = db
        self.pool_service = pool_service
        self.publisher = publisher
        self.wg_router_url = wg_router_url
        self._redis = redis
        self._http = httpx.AsyncClient(
            base_url=wg_router_url,
            timeout=httpx.Timeout(5.0),
        )

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def check_all_peers(self, org_id: uuid.UUID) -> dict:
        """Check handshake recency for all ASSIGNED peers in the org."""
        peers = await self._get_active_peers(org_id)
        if not peers:
            return {"checked": 0, "stale": 0, "missing": 0, "reconnects": 0}

        handshake_data = await self._get_handshake_times()
        now = datetime.now(timezone.utc)

        stale = missing = reconnects = 0

        for peer in peers:
            last_handshake = handshake_data.get(peer.public_key)

            if last_handshake is None:
                missing += 1
                await self._handle_missing_peer(peer, org_id)
                continue

            since_sec = (now - last_handshake).total_seconds()
            peer.last_handshake_at = last_handshake
            peer.is_active = since_sec < self.STALE_HANDSHAKE_THRESHOLD

            if since_sec > self.STALE_HANDSHAKE_THRESHOLD:
                stale += 1
                # FIX 6.4: only reconnect online devices (avoids false alerts for
                # powered-off emulators generating hundreds of spurious vpn_reconnect)
                if not await self._is_device_online(str(peer.device_id)):
                    continue
                logger.warning(
                    "VPN stale handshake",
                    device_id=str(peer.device_id),
                    since_handshake_s=since_sec,
                )
                if await self._trigger_reconnect(peer, org_id):
                    reconnects += 1

        await self.db.flush()
        return {
            "checked": len(peers),
            "stale": stale,
            "missing": missing,
            "reconnects": reconnects,
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _get_active_peers(self, org_id: uuid.UUID) -> list[VPNPeer]:
        result = await self.db.execute(
            select(VPNPeer).where(
                VPNPeer.org_id == org_id,
                VPNPeer.status == VPNPeerStatus.ASSIGNED,
                VPNPeer.device_id.isnot(None),
            )
        )
        return list(result.scalars().all())

    async def _get_handshake_times(self) -> dict[str, datetime]:
        """Fetch all peer handshake timestamps from WG Router API."""
        try:
            resp = await self._http.get("/peers/handshakes")
            data = resp.json()
            return {
                k: datetime.fromtimestamp(v, tz=timezone.utc)
                for k, v in data.items()
                if isinstance(v, (int, float)) and v > 0
            }
        except Exception as exc:
            logger.error("Failed to fetch handshake times from WG Router", exc=str(exc))
            return {}

    async def _is_device_online(self, device_id: str) -> bool:
        """Check Redis device status cache. Returns True when no cache entry (assume online)."""
        if self._redis is None:
            return True
        try:
            val = await self._redis.get(f"device:status:{device_id}")
            return val is not None
        except Exception:
            return True

    async def _trigger_reconnect(self, peer: VPNPeer, org_id: uuid.UUID) -> bool:
        """Send vpn_reconnect command to device agent via EventPublisher. Returns True if sent."""
        if not peer.device_id:
            return False

        try:
            decrypted_private = self.pool_service.key_cipher.decrypt(
                peer.private_key_enc
            ).decode()
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
            config = self.pool_service.config_builder.build_client_config(
                private_key=decrypted_private,
                assigned_ip=peer.tunnel_ip or "0.0.0.0",
                obfuscation=obfuscation,
            )
        except Exception as exc:
            logger.error(
                "Failed to decrypt peer config for reconnect",
                peer_id=str(peer.id),
                exc=str(exc),
            )
            return False

        sent = await self.publisher.send_command_to_device(
            str(peer.device_id),
            {
                "type": "vpn_reconnect",
                "config": config,
                "reason": "stale_handshake",
            },
        )
        if not sent:
            logger.warning(
                "Device offline during VPN reconnect attempt",
                device_id=str(peer.device_id),
                peer_id=str(peer.id),
            )
        return bool(sent)

    async def _handle_missing_peer(
        self, peer: VPNPeer, org_id: uuid.UUID
    ) -> None:
        """Re-register a peer that disappeared from the WG server via direct HTTP."""
        try:
            payload = {
                "public_key": peer.public_key,
                "allowed_ip": f"{peer.tunnel_ip or '0.0.0.0'}/32",
            }
            resp = await self._http.post("/peers", json=payload)
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"WG Router error {resp.status_code}")
            logger.info("Re-added missing VPN peer", device_id=str(peer.device_id))
        except Exception as exc:
            logger.error(
                "Failed to re-add missing VPN peer",
                device_id=str(peer.device_id),
                exc=str(exc),
            )
