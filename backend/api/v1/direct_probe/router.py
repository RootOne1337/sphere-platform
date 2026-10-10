"""Read diagnostic admission without allocating a peer or issuing TURN credentials."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.dependencies import require_permission
from backend.database import redis_client
from backend.database.engine import get_db
from backend.database.tenant import bind_tenant_context
from backend.models.device import Device
from backend.models.user import User
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.direct_probe_ice import turn_urls
from backend.websocket.direct_probe_protocol import (
    LIVE_VIDEO_MIN_AGENT_CODE,
    VIDEO_MIN_AGENT_CODE,
    InvalidDirectProbe,
)
from backend.websocket.direct_probe_runtime import get_direct_probe_runtime
from backend.websocket.stream_session_history import (
    RETENTION_SECONDS,
    SESSION_BYTES,
    SESSION_LIMIT,
    StreamSessionHistory,
)

router = APIRouter(prefix="/devices", tags=["direct-transport-canary"])
Profile = Literal["host", "public-stun", "turn"]


class StreamSessionHistoryResponse(BaseModel):
    schema_version: Literal[1] = 1
    device_id: uuid.UUID
    session_limit: int = SESSION_LIMIT
    session_byte_limit: int = SESSION_BYTES
    retention_seconds: int = RETENTION_SECONDS
    browser_observations: Literal["client_reported"] = "client_reported"
    sessions: list[dict[str, Any]]


@router.get("/{device_id}/stream-sessions", response_model=StreamSessionHistoryResponse,
            tags=["stream-diagnostics"], summary="Read the last ten bounded stream diagnostic sessions")
async def stream_session_history(
    device_id: uuid.UUID, response: Response,
    user: User = require_permission("stream:read"), db: AsyncSession = Depends(get_db),
) -> StreamSessionHistoryResponse:
    response.headers["Cache-Control"] = "private, no-store"
    await bind_tenant_context(db, str(user.org_id))
    device = await db.get(Device, device_id)
    if not device or not device.is_active or device.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Device not found")
    sessions = await StreamSessionHistory(redis_client.redis).read(str(user.org_id), str(device_id))
    if sessions is None:
        raise HTTPException(status_code=503, detail="Stream diagnostic history unavailable",
                            headers={"Cache-Control": "private, no-store"})
    return StreamSessionHistoryResponse(device_id=device_id, sessions=sessions)


class ProbeCapabilities(BaseModel):
    schema_version: Literal[1] = 1
    device_id: uuid.UUID
    enabled: bool
    profiles: list[Profile]
    scope: Literal["diagnostic_echo_only"] = "diagnostic_echo_only"
    max_duration_ms: Literal[30000] = 30000
    samples: Literal[20] = 20
    readonly_video_enabled: bool = False
    live_video_enabled: bool = False


def relay_configured() -> bool:
    """Configuration admission is not relay reachability or native acceptance."""
    try:
        turn_urls(settings.DIRECT_PROBE_TURN_URLS)
    except InvalidDirectProbe:
        return False
    secret = settings.DIRECT_PROBE_TURN_SECRET.get_secret_value()
    return 32 <= len(secret) <= 256 and secret.isascii() and not any(c.isspace() for c in secret)


@router.get("/{device_id}/direct-probe-capabilities", response_model=ProbeCapabilities,
            summary="Read per-device admission to the finite direct-channel diagnostic")
async def probe_capabilities(
    device_id: uuid.UUID, response: Response,
    user: User = require_permission("stream:read"), db: AsyncSession = Depends(get_db),
) -> ProbeCapabilities:
    response.headers["Cache-Control"] = "private, no-store"
    await bind_tenant_context(db, str(user.org_id))
    device = await db.get(Device, device_id)
    if not device or not device.is_active or device.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Device not found")
    runtime = get_direct_probe_runtime()
    enabled = bool(settings.DIRECT_TRANSPORT_PROBE_ENABLED
                   and str(device_id) in settings.DIRECT_TRANSPORT_PROBE_DEVICE_IDS
                   and runtime and runtime.available)
    profiles: list[Profile] = ["host", "public-stun"] if enabled else []
    if enabled and relay_configured():
        profiles.append("turn")
    video_enabled = False
    live_enabled = False
    if enabled and runtime and (settings.DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED or settings.DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED):
        status = await DeviceStatusCache(runtime.redis).get_status(str(device_id))
        current = bool(status and status.ws_session_id and status.status in {"online", "busy"})
        video_enabled = bool(current and settings.DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED and status
                             and status.agent_version_code and status.agent_version_code >= VIDEO_MIN_AGENT_CODE)
        live_enabled = bool(current and settings.DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED and status
                            and status.agent_version_code and status.agent_version_code >= LIVE_VIDEO_MIN_AGENT_CODE)
    return ProbeCapabilities(device_id=device_id, enabled=enabled, profiles=profiles,
                             readonly_video_enabled=video_enabled, live_video_enabled=live_enabled)
