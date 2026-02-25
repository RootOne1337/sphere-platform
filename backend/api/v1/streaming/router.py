# backend/api/v1/streaming/router.py
# ВЛАДЕЛЕЦ: TZ-05 SPLIT-3. REST endpoints for stream session management.
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.device import Device
from backend.models.user import User
from backend.websocket.connection_manager import get_connection_manager
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
    manager = get_connection_manager()
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    sent = await manager.send_to_device(device_id, {
        "type": "start_stream",
        "quality": "720p",
        "bitrate": 2_000_000,
    })
    if not sent:
        raise HTTPException(status_code=503, detail="Failed to reach device")

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
    manager = get_connection_manager()
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    sent = await manager.send_to_device(device_id, {"type": "stop_stream"})
    if not sent:
        raise HTTPException(status_code=503, detail="Failed to reach device")

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
    manager = get_connection_manager()
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    sent = await manager.send_to_device(device_id, {"type": "request_keyframe"})
    if not sent:
        raise HTTPException(status_code=503, detail="Failed to reach device")

    return {"status": "keyframe_requested", "device_id": device_id}
