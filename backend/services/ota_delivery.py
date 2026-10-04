"""Wake an existing Android socket using only a committed, tenant-owned grant."""
from __future__ import annotations

import asyncio
import time
import uuid

import structlog
from sqlalchemy import select

from backend.models.device import Device
from backend.websocket.connection_manager import ConnectionManager

logger = structlog.get_logger()


async def dispatch_ota_wake(manager: ConnectionManager, device_id: str, message: dict) -> None:
    """Internal Redis hint, never an Android command or a new permission.

    Re-read the signed grant on the socket-owning worker. A stale/revoked wake
    cannot dispatch a replacement grant. The active socket supplies the HTTPS
    origin; operator HTTP requests and Redis payload URLs cannot choose it.
    """
    try:
        target = uuid.UUID(device_id)
        org_id = uuid.UUID(message["org_id"])
        command_id = uuid.UUID(message["command_id"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return
    info = manager.connection_snapshot(device_id)
    if info is None or info.agent_type != "android" or info.org_id != str(org_id):
        return

    from backend.database.engine import AsyncSessionLocal
    from backend.database.tenant import bind_tenant_context
    from backend.services.device_ota_recovery import get_device_ota_grant

    try:
        async with asyncio.timeout(3):
            async with AsyncSessionLocal() as db:
                await bind_tenant_context(db, str(org_id))
                # Serialize with revoke/replace until the send attempt finishes.
                device = await db.scalar(select(Device).where(
                    Device.id == target, Device.org_id == org_id, Device.is_active.is_(True),
                ).with_for_update())
                if device is None:
                    return
                grant = await get_device_ota_grant(db, device_id=device_id, org_id=str(org_id))
                if grant is None or grant.command_id != command_id:
                    return
                remaining = grant.expires_at - int(time.time())
                if remaining <= 0:
                    return
                command = {
                    "type": "OTA_UPDATE", "command_id": str(grant.command_id),
                    "signed_at": int(time.time()), "ttl_seconds": min(180, remaining),
                    "payload": {
                        "download_url": str(info.ws.base_url.replace(scheme="https")).rstrip("/")
                                        + "/api/v1/updates/artifacts/" + grant.sha256,
                        "version": grant.version_name, "version_code": grant.version_code,
                        "sha256": grant.sha256,
                    },
                }
                sent = await manager.send_to_session(device_id, info.session_id, command)
                logger.info("ota_recovery.live_send_attempt", device_id=device_id,
                            command_id=str(command_id), sent=sent)
    except Exception as error:
        # The durable grant remains for reconnect; no raw error/URL/token payload.
        logger.warning("ota_recovery.live_wake_unavailable", device_id=device_id,
                       command_id=str(command_id), error_class=type(error).__name__)
