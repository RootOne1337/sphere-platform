# backend/services/vpn/health_monitor.py  TZ-06 SPLIT-3
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
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
    Requests reconnect for stale handshakes; never provisions router peers.
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
            headers={"X-API-Key": pool_service.wg_router_api_key}
            if pool_service.wg_router_api_key else {},
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
        if handshake_data is None:
            # An unavailable or invalid snapshot is not an empty peer inventory.
            # Preserve the last known state and let the next cycle retry.
            return {"checked": 0, "stale": 0, "missing": 0, "reconnects": 0,
                    "error": "router_unavailable"}
        now = datetime.now(timezone.utc)

        checked = stale = missing = reconnects = 0

        for peer in peers:
            last_handshake = handshake_data.get(peer.public_key)

            since_sec = (now - last_handshake).total_seconds() if last_handshake else None
            values: dict = {"is_active": since_sec is not None and since_sec < self.STALE_HANDSHAKE_THRESHOLD}
            freshness: ColumnElement[bool] = VPNPeer.last_handshake_at == peer.last_handshake_at
            if last_handshake:
                values["last_handshake_at"] = last_handshake
                freshness = or_(
                    VPNPeer.last_handshake_at.is_(None),
                    VPNPeer.last_handshake_at <= last_handshake,
                )
            # The router poll can overlap revocation. Recheck ownership/state
            # when writing, rather than flushing an obsolete ORM snapshot.
            current = await self.db.scalar(update(VPNPeer).where(
                VPNPeer.id == peer.id,
                VPNPeer.org_id == org_id,
                VPNPeer.device_id == peer.device_id,
                VPNPeer.status == VPNPeerStatus.ASSIGNED,
                freshness,
            ).values(**values).returning(VPNPeer.id).execution_options(synchronize_session="fetch"))
            if current is None:
                continue
            checked += 1

            if last_handshake is None:
                missing += 1
                # Zero/absent handshake can mean the peer has never connected.
                # Provisioning requires an authoritative inventory and durable
                # intent, neither of which this observation endpoint provides.
                continue

            if since_sec is not None and since_sec >= self.STALE_HANDSHAKE_THRESHOLD:
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
            "checked": checked,
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
            ).order_by(VPNPeer.id)
        )
        return list(result.scalars().all())

    async def _get_handshake_times(self) -> dict[str, datetime] | None:
        """Return a validated snapshot, or None when router state is unknown."""
        try:
            resp = await self._http.get("/peers/handshakes")
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid handshake snapshot")
            times = {}
            latest = datetime.now(timezone.utc).timestamp() + 60
            for key, timestamp in data.items():
                if (not isinstance(key, str) or not key
                        or not isinstance(timestamp, (int, float))
                        or isinstance(timestamp, bool) or not 0 <= timestamp <= latest):
                    raise ValueError("Invalid handshake timestamp")
                if timestamp > 0:
                    times[key] = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return times
        except Exception as exc:
            logger.error("Failed to fetch handshake times from WG Router", error_type=type(exc).__name__)
            return None

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
            config = self.pool_service.build_peer_config(peer)
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
