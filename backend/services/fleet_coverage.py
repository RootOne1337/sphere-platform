"""Bounded request-time SQL/Redis snapshot, without a router/device command."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.schemas.device_status import VPN_OBSERVATION_MAX_AGE_SECONDS
from backend.schemas.fleet_coverage import CoverageSignal, FleetCoverageResponse
from backend.services.device_status_cache import DeviceStatusCache
from backend.services.vpn.health_monitor import VPNHealthMonitor

logger = structlog.get_logger()
MAX_INVENTORY_DEVICES = 5000
REDIS_BATCH_SIZE = 500
SQL_TIMEOUT_SECONDS = 3
REDIS_TIMEOUT_SECONDS = 2


def absent(source: str, reason: str, state: str = "unavailable") -> CoverageSignal:
    return CoverageSignal.model_validate({"state": state, "source": source, "reason": reason})


async def read_fleet_coverage(db: AsyncSession, redis: Any, org_id: uuid.UUID, *, vpn_allowed: bool) -> FleetCoverageResponse:
    inventory = absent("sql-active-inventory", "inventory_unavailable")
    presence = absent("redis-presence", "inventory_unavailable")
    android = absent("android-managed-vpn-report", "inventory_unavailable")
    assignment = absent("sql-tenant-peers", "inventory_unavailable")
    handshake = absent("retained-sql-handshakes", "inventory_unavailable")
    rows = None
    try:
        async with asyncio.timeout(SQL_TIMEOUT_SECONDS):
            async with db.begin_nested():
                rows = (await db.execute(select(Device.id, func.count().over().label("total"))
                    .where(Device.org_id == org_id, Device.is_active.is_(True))
                    .order_by(Device.id).limit(MAX_INVENTORY_DEVICES + 1))).all()
        inventory = CoverageSignal(state="ready", source="sql-active-inventory", observed_at=datetime.now(timezone.utc),
                                   counts={"total": int(rows[0].total) if rows else 0})
    except Exception as exc:
        logger.warning("coverage.inventory_unavailable", kind=type(exc).__name__)
    if not vpn_allowed:
        android = absent(android.source, "vpn_read_required", "forbidden")
        assignment = absent(assignment.source, "vpn_read_required", "forbidden")
        handshake = absent(handshake.source, "vpn_read_required", "forbidden")
    if rows is not None:
        if vpn_allowed:
            try:
                async with asyncio.timeout(SQL_TIMEOUT_SECONDS):
                    # SAVEPOINT contains a SQL source failure; Redis may still be read.
                    async with db.begin_nested():
                        assignment, handshake = await _read_peer_counts(db, org_id)
            except Exception as exc:
                logger.warning("coverage.peers_unavailable", kind=type(exc).__name__)
                assignment = absent(assignment.source, "peer_source_unavailable")
                handshake = absent(handshake.source, "peer_source_unavailable")
        if len(rows) > MAX_INVENTORY_DEVICES:
            presence = absent(presence.source, "inventory_exceeds_budget", "limited")
            if vpn_allowed:
                android = absent(android.source, "inventory_exceeds_budget", "limited")
        elif rows and redis is None:
            presence = absent(presence.source, "redis_unavailable")
            if vpn_allowed:
                android = absent(android.source, "redis_unavailable")
        else:
            try:
                as_of = datetime.now(timezone.utc)
                pc = dict.fromkeys(["online", "busy", "connecting", "offline", "error", "unknown"], 0)
                ac = dict.fromkeys(["active", "inactive", "stale", "unknown"], 0)
                cache = DeviceStatusCache(redis)
                async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
                    for start in range(0, len(rows), REDIS_BATCH_SIZE):
                        ids = [str(row.id) for row in rows[start:start + REDIS_BATCH_SIZE]]
                        statuses = await cache.bulk_get_status(ids, as_of=as_of)
                        for device_id in ids:
                            status = statuses.get(device_id)
                            if status is None or status.device_id != device_id:
                                pc["unknown"] += 1
                                ac["unknown"] += 1
                                continue
                            kind: str = status.status
                            if kind in ("online", "busy"):
                                hb = status.last_heartbeat
                                if (not status.ws_session_id or hb is None or hb.tzinfo is None
                                        or not 0 <= (as_of - hb).total_seconds() < VPN_OBSERVATION_MAX_AGE_SECONDS):
                                    kind = "unknown"
                            pc[kind] += 1
                            if status.vpn_observation_state == "fresh":
                                ac["active" if status.vpn_active else "inactive"] += 1
                            else:
                                ac[status.vpn_observation_state] += 1
                presence = CoverageSignal(state="ready", source=presence.source, observed_at=as_of,
                                          counts=pc, max_age_seconds=VPN_OBSERVATION_MAX_AGE_SECONDS)
                if vpn_allowed:
                    android = CoverageSignal(state="ready", source=android.source, observed_at=as_of,
                                             counts=ac, max_age_seconds=VPN_OBSERVATION_MAX_AGE_SECONDS)
            except Exception as exc:
                logger.warning("coverage.presence_unavailable", kind=type(exc).__name__)
                presence = absent(presence.source, "redis_unavailable")
                if vpn_allowed:
                    android = absent(android.source, "redis_unavailable")
    return FleetCoverageResponse(org_id=org_id, generated_at=datetime.now(timezone.utc),
        max_inventory_devices=MAX_INVENTORY_DEVICES, inventory=inventory, presence=presence,
        android_vpn=android, vpn_assignment=assignment, handshakes=handshake,
        transport_tunnels=absent("transport-tunnel-probes", "transport_probes_not_connected", "unmeasured"))


async def _read_peer_counts(db: AsyncSession, org_id: uuid.UUID) -> tuple[CoverageSignal, CoverageSignal]:
    now = datetime.now(timezone.utc)
    threshold = VPNHealthMonitor.STALE_HANDSHAKE_THRESHOLD
    cutoff = now - timedelta(seconds=threshold)
    owned_active = select(Device.id).where(Device.id == VPNPeer.device_id, Device.org_id == org_id,
                                            Device.is_active.is_(True)).exists()
    eligible = and_(VPNPeer.status == VPNPeerStatus.ASSIGNED, owned_active)
    recent_time = and_(VPNPeer.last_handshake_at > cutoff, VPNPeer.last_handshake_at <= now)
    predicates = {state.value: VPNPeer.status == state for state in VPNPeerStatus}
    predicates.update({
        "outside_active_inventory": and_(VPNPeer.status == VPNPeerStatus.ASSIGNED, ~owned_active),
        "recent": and_(eligible, recent_time, VPNPeer.is_active.is_(True)),
        "stale": and_(eligible, VPNPeer.last_handshake_at <= cutoff),
        "unknown": and_(eligible, (VPNPeer.last_handshake_at.is_(None) | (VPNPeer.last_handshake_at > now))),
        "inactive": and_(eligible, recent_time, VPNPeer.is_active.is_(False)),
    })
    result = (await db.execute(select(*[func.count(case((condition, 1))).label(name)
        for name, condition in predicates.items()]).where(VPNPeer.org_id == org_id))).one()._mapping
    return (
        CoverageSignal(state="ready", source="sql-tenant-peers", observed_at=now,
            counts={name: int(result[name]) for name in [*[state.value for state in VPNPeerStatus], "outside_active_inventory"]}),
        CoverageSignal(state="ready", source="retained-sql-handshakes", observed_at=now,
            counts={name: int(result[name]) for name in ["recent", "stale", "unknown", "inactive"]}, max_age_seconds=threshold),
    )
