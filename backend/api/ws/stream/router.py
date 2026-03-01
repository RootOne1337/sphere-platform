# backend/api/ws/stream/router.py
# ВЛАДЕЛЕЦ: TZ-05 SPLIT-3. Browser viewer endpoint — получает H.264 поток от агента.
from __future__ import annotations

import asyncio
import secrets

import structlog
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import _is_dev_skip_auth
from backend.database.engine import AsyncSessionLocal
from backend.websocket.connection_manager import get_connection_manager
from backend.websocket.stream_bridge import get_stream_bridge

logger = structlog.get_logger()

router = APIRouter(tags=["streaming"])


async def _authenticate_viewer(token: str, db: AsyncSession):
    """
    Аутентификация зрителя стрима по JWT.
    При DEV_SKIP_AUTH — возвращает первого активного пользователя без валидации токена.
    """
    # DEV_SKIP_AUTH: вернуть первого активного пользователя без JWT валидации
    if _is_dev_skip_auth():
        import sqlalchemy as sa

        from backend.models.user import User

        result = await db.execute(
            sa.select(User).where(User.is_active.is_(True)).limit(1)
        )
        dev_user = result.scalar_one_or_none()
        if dev_user:
            logger.warning("stream_viewer: DEV_SKIP_AUTH — авторизация пропущена", user_id=str(dev_user.id))
            return dev_user
        # Если пользователей нет в БД — fallback на обычную JWT авторизацию

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
    if not token and not _is_dev_skip_auth():
        await ws.close(code=4001, reason="no_token")
        return

    # Auth phase: DB session opened and closed immediately — not held for WS lifetime
    import uuid as _uuid

    from backend.models.device import Device

    user = None
    try:
        async with AsyncSessionLocal() as db:
            try:
                user = await _authenticate_viewer(token, db)
            except HTTPException:
                await ws.close(code=4001, reason="invalid_token")
                return

            try:
                device_uuid = _uuid.UUID(device_id)
            except ValueError:
                await ws.close(code=4004, reason="invalid_device_id")
                return

            device = await db.get(Device, device_uuid)
            if not device or str(device.org_id) != str(user.org_id):
                await ws.close(code=4004, reason="device_not_found")
                return

            # Extract needed values before DB session closes
            user_id_str = str(user.id)
    except Exception:
        await ws.close(code=1011, reason="auth_error")
        return
    # DB session is now CLOSED — safe to enter long-lived WS loop

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
        user_id=user_id_str,
    )

    # Notify agent → triggers SPS/PPS replay + I-frame request
    await manager.send_to_device(device_id, {
        "type": "viewer_connected",
        "session_id": session_id,
    })

    # FIX-KEEPALIVE: Периодический ping каждые 10 секунд — предотвращает
    # закрытие WS Cloudflare tunnel'ом при отсутствии upstream трафика.
    # Cloudflare Quick Tunnel агрессивно дропает idle WS (замечено через ~5-25 сек).
    async def _viewer_ping_loop() -> None:
        try:
            while True:
                await asyncio.sleep(10)
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    ping_task = asyncio.create_task(_viewer_ping_loop())

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
                case "swipe":
                    x1 = int(data.get("x1", 0))
                    y1 = int(data.get("y1", 0))
                    x2 = int(data.get("x2", 0))
                    y2 = int(data.get("y2", 0))
                    duration_ms = int(data.get("duration_ms", 300))
                    await manager.send_to_device(device_id, {
                        "type": "touch_swipe",
                        "x1": x1, "y1": y1,
                        "x2": x2, "y2": y2,
                        "duration_ms": duration_ms,
                        "session_id": session_id,
                    })
                case "request_keyframe":
                    await manager.send_to_device(device_id, {
                        "type": "request_keyframe",
                    })
                case "keyevent":
                    await manager.send_to_device(device_id, {
                        "type": "keyevent",
                        "code": int(data.get("code", 0)),
                        "session_id": session_id,
                    })
                case "text":
                    await manager.send_to_device(device_id, {
                        "type": "text",
                        "text": str(data.get("text", "")),
                        "session_id": session_id,
                    })
                case "pong":
                    pass  # Ответ на наш keepalive ping — просто игнорируем
                case _:
                    logger.debug(
                        "Unknown viewer message",
                        type=data.get("type"),
                        device_id=device_id,
                    )
    except WebSocketDisconnect as exc:
        logger.info(
            "Stream viewer WS disconnect",
            device_id=device_id,
            session_id=session_id,
            code=exc.code,
            reason=getattr(exc, "reason", ""),
        )
    except Exception as exc:
        logger.warning(
            "Stream viewer WS error",
            device_id=device_id,
            session_id=session_id,
            error=str(exc),
        )
    finally:
        ping_task.cancel()
        await bridge.unregister_viewer(device_id)
        logger.info(
            "Stream viewer disconnected",
            device_id=device_id,
            session_id=session_id,
        )
