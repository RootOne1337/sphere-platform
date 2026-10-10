# backend/api/v1/streaming/router.py
# ВЛАДЕЛЕЦ: TZ-05 SPLIT-3. REST endpoints for stream session management.
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.device import Device
from backend.models.user import User
from backend.websocket.stream_bridge import get_stream_bridge

logger = structlog.get_logger()

router = APIRouter(prefix="/streaming", tags=["streaming"])


class StreamStatusResponse(BaseModel):
    device_id: str
    is_streaming: bool
    viewer_connected: bool
    drop_ratio: float


async def _check_device_ownership(
    device_id: str,
    org_id: str,
    db: AsyncSession,
) -> None:
    """Raise 404 if device doesn't exist or belongs to a different org (tenant check)."""
    result = await db.execute(
        select(Device.id).where(
            Device.id == device_id,
            Device.org_id == org_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Device not found")


async def _send_live_control(device_id: str, command: dict) -> None:
    """Publish to the agent's owner worker; never defer interactive controls."""
    from backend.websocket.pubsub_router import get_pubsub_publisher

    publisher = get_pubsub_publisher()
    if publisher is None:
        raise HTTPException(503, "Stream command transport is unavailable")
    try:
        sent = await publisher.send_command_live(device_id, command)
    except RedisError as exc:
        # Publication may have succeeded before a lost response. Do not retry an
        # interactive start/stop automatically or misreport an infrastructure
        # failure as a missing/offline device.
        logger.warning("stream_control_transport_failed", device_id=device_id, command_type=command["type"])
        raise HTTPException(503, "Stream command transport failed; delivery outcome is unknown") from exc
    if not sent:
        raise HTTPException(503, "Device stream command channel is unavailable")


@router.get("/{device_id}/status", response_model=StreamStatusResponse)
async def get_stream_status(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permission("stream:read"),
) -> StreamStatusResponse:
    """Returns current streaming status for a device."""
    await _check_device_ownership(device_id, str(current_user.org_id), db)
    bridge = get_stream_bridge()
    is_streaming = bridge.is_streaming(device_id) if bridge else False
    drop_ratio = bridge.get_drop_ratio(device_id) if bridge else 0.0

    return StreamStatusResponse(
        device_id=device_id,
        is_streaming=is_streaming,
        viewer_connected=is_streaming,
        drop_ratio=drop_ratio,
    )


@router.post("/{device_id}/start")
async def request_stream_start(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permission("stream:control"),
) -> dict:
    """
    Send start_stream command to the Android agent.
    Normally the viewer WS endpoint triggers this automatically;
    this REST endpoint is for manual/testing purposes.
    """
    await _check_device_ownership(device_id, str(current_user.org_id), db)
    await _send_live_control(device_id, {
        "type": "start_stream",
        "quality": "720p",
        "bitrate": 2_000_000,
    })
    logger.info("stream_start_requested", device_id=device_id, user_id=str(current_user.id))
    return {"status": "start_requested", "device_id": device_id}


@router.post("/{device_id}/stop")
async def request_stream_stop(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permission("stream:control"),
) -> dict:
    """Send stop_stream command to the Android agent."""
    await _check_device_ownership(device_id, str(current_user.org_id), db)
    await _send_live_control(device_id, {"type": "stop_stream"})

    logger.info("stream_stop_requested", device_id=device_id, user_id=str(current_user.id))
    return {"status": "stop_requested", "device_id": device_id}


@router.post("/{device_id}/keyframe")
async def request_keyframe(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permission("stream:control"),
) -> dict:
    """Request an immediate I-frame (for viewer reconnect recovery)."""
    await _check_device_ownership(device_id, str(current_user.org_id), db)
    await _send_live_control(device_id, {"type": "request_keyframe"})

    return {"status": "keyframe_requested", "device_id": device_id}
