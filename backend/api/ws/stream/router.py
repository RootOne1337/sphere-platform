# backend/api/ws/stream/router.py
# ВЛАДЕЛЕЦ: TZ-05 SPLIT-3. Browser viewer endpoint — получает H.264 поток от агента.
from __future__ import annotations

import asyncio
import secrets

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import get_db
from backend.websocket.connection_manager import get_connection_manager
from backend.websocket.stream_bridge import get_stream_bridge

logger = structlog.get_logger()

router = APIRouter(tags=["streaming"])


async def _authenticate_viewer(token: str, db: AsyncSession):
    """Re-use the JWT auth logic from ws/android router."""
    import uuid

    import jwt as pyjwt

    from backend.core.security import decode_access_token
    from backend.models.user import User
    from backend.services.cache_service import CacheService

    try:
        payload = decode_access_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    cache = CacheService()
    if await cache.is_token_blacklisted(payload["jti"]):
        raise HTTPException(status_code=401, detail="Token revoked")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive")
    return user


@router.websocket("/ws/stream/{device_id}")
async def stream_viewer_ws(
    ws: WebSocket,
    device_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Browser viewer endpoint.

    Protocol:
    1. Accept connection
    2. Receive first JSON message with {token: "..."}
    3. Validate JWT, check device ownership
    4. Register as viewer in VideoStreamBridge
    5. Signal agent to send viewer_connected (triggers SPS/PPS + I-frame)
    6. Forward viewer actions (click, request_keyframe) to agent
    7. Unregister on disconnect
    """
    await ws.accept()

    # First-message auth (JWT in payload, not URL — avoids log exposure)
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        await ws.close(code=4003, reason="auth_timeout")
        return
    except Exception:
        await ws.close(code=4001, reason="receive_error")
        return

    token = first.get("token", "")
    if not token:
        await ws.close(code=4001, reason="no_token")
        return

    try:
        user = await _authenticate_viewer(token, db)
    except HTTPException:
        await ws.close(code=4001, reason="invalid_token")
        return

    # Verify device ownership
    import uuid as _uuid

    from backend.models.device import Device
    try:
        device_uuid = _uuid.UUID(device_id)
    except ValueError:
        await ws.close(code=4004, reason="invalid_device_id")
        return

    device = await db.get(Device, device_uuid)
    if not device or str(device.org_id) != str(user.org_id):
        await ws.close(code=4004, reason="device_not_found")
        return

    bridge = get_stream_bridge()
    if not bridge:
        await ws.close(code=1013, reason="stream_bridge_unavailable")
        return

    manager = get_connection_manager()

    # Unique session for this viewer
    session_id = secrets.token_hex(8)

    await bridge.register_viewer(device_id, ws, session_id)
    logger.info(
        "Stream viewer connected",
        device_id=device_id,
        session_id=session_id,
        user_id=str(user.id),
    )

    # Notify agent → triggers SPS/PPS replay + I-frame request
    await manager.send_to_device(device_id, {
        "type": "viewer_connected",
        "session_id": session_id,
    })

    try:
        while True:
            data = await ws.receive_json()
            match data.get("type"):
                case "click":
                    # Forward tap coordinates to agent — coordinate mapping done client-side
                    x = int(data.get("x", 0))
                    y = int(data.get("y", 0))
                    await manager.send_to_device(device_id, {
                        "type": "touch_tap",
                        "x": x,
                        "y": y,
                        "session_id": session_id,
                    })
                case "request_keyframe":
                    await manager.send_to_device(device_id, {
                        "type": "request_keyframe",
                    })
                case _:
                    logger.debug(
                        "Unknown viewer message",
                        type=data.get("type"),
                        device_id=device_id,
                    )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await bridge.unregister_viewer(device_id)
        logger.info(
            "Stream viewer disconnected",
            device_id=device_id,
            session_id=session_id,
        )
