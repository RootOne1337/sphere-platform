# backend/api/ws/stream/router.py
# ВЛАДЕЛЕЦ: TZ-05 SPLIT-3. Browser viewer endpoint — получает H.264 поток от агента.
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import _is_dev_skip_auth
from backend.database import redis_client
from backend.database.engine import AsyncSessionLocal
from backend.websocket.continuous_lease import InputLeaseUnavailable
from backend.websocket.continuous_runtime import (
    ContinuousAdmissionRejected,
    TouchViewer,
    get_continuous_runtime,
)
from backend.websocket.stream_bridge import get_stream_bridge
from backend.websocket.stream_session_history import (
    REPORT_INTERVAL_SECONDS,
    StreamSessionHistory,
    utc_now,
)
from backend.websocket.viewer_input import InvalidViewerInput, viewer_command

logger = structlog.get_logger()

router = APIRouter(tags=["streaming"])

VIEWER_AUTH_RECHECK_SECONDS = 10.0
VIEWER_AUTH_TIMEOUT_SECONDS = 2.0


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
    from backend.database.tenant import bind_tenant_context
    from backend.models.user import User
    from backend.services.cache_service import CacheService

    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            raise pyjwt.InvalidTokenError("Expected a user access token")
        user_id = uuid.UUID(payload["sub"])
        org_id = uuid.UUID(payload["org_id"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except (KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid identity claims")

    cache = CacheService()
    if await cache.is_token_blacklisted(payload["jti"]):
        raise HTTPException(status_code=401, detail="Token revoked")

    await bind_tenant_context(db, str(org_id))
    user = await db.get(User, user_id)
    if not user or not user.is_active or user.org_id != org_id:
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

    if not isinstance(first, dict) or not isinstance(first.get("token", ""), str):
        await ws.close(code=4001, reason="invalid_auth_message")
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
            from backend.core.rbac import has_permission
            if not has_permission(user.role, "stream:read"):
                await ws.close(code=4003, reason="stream_access_denied")
                return
            user_id_str = str(user.id)
            org_id_str = str(user.org_id)
    except Exception:
        await ws.close(code=1011, reason="auth_error")
        return
    # DB session is now CLOSED — safe to enter long-lived WS loop

    bridge = get_stream_bridge()
    if not bridge:
        await ws.close(code=1013, reason="stream_bridge_unavailable")
        return

    # Unique session for this viewer
    session_id = secrets.token_hex(8)

    try:
        await bridge.register_viewer(device_id, ws, session_id)
    except Exception:
        await ws.close(code=1013, reason="stream_transport_unavailable")
        return
    logger.info(
        "Stream viewer connected",
        device_id=device_id,
        session_id=session_id,
        user_id=user_id_str,
    )
    history = StreamSessionHistory(redis_client.redis, redis_client.redis_binary)
    history_enabled = await history.begin(org_id_str, device_id, session_id)
    last_browser_report = last_direct_report = -float("inf")
    direct_reports = 0
    diagnostic_queue: asyncio.Queue[tuple[str, dict[str, Any], int]] = asyncio.Queue(maxsize=4)

    def enqueue_diagnostic(kind: str, sample: dict[str, Any], limit: int = 15) -> None:
        if not history_enabled or diagnostic_queue.full():
            return
        diagnostic_queue.put_nowait((kind, sample | {"received_at": utc_now()}, limit))

    async def write_diagnostics() -> None:
        while True:
            kind, sample, limit = await diagnostic_queue.get()
            try:
                await history.update(org_id_str, device_id, session_id, {"kind": kind, "sample": sample}, limit)
            finally:
                diagnostic_queue.task_done()

    diagnostic_writer: asyncio.Task | None = None

    # Notify agent → triggers SPS/PPS replay + I-frame request
    async def send_control(command: dict) -> None:
        try:
            sent = await bridge.send_control(device_id, command)
        except Exception:
            sent = False
        if not sent:
            await ws.send_json({"type": "error", "error": "stream_control_unavailable"})

    auth_stopped = asyncio.Event()
    touch_runtime = get_continuous_runtime()
    touch_viewer = TouchViewer(device_id, org_id_str, user_id_str, session_id, ws)
    touch_registered = bool(touch_runtime and touch_runtime.register(touch_viewer))

    async def current_control_permission() -> bool | None:
        """Fresh identity/ownership for input; no DB session is held while streaming."""
        try:
            async with asyncio.timeout(VIEWER_AUTH_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
                current_user = await _authenticate_viewer(token, db)
                if str(current_user.id) != user_id_str or str(current_user.org_id) != org_id_str:
                    raise HTTPException(401, "Viewer identity changed")
                current_device = await db.get(Device, device_uuid)
                if not current_device or str(current_device.org_id) != org_id_str:
                    raise HTTPException(404, "Device ownership changed")
                if not has_permission(current_user.role, "stream:read"):
                    raise HTTPException(403, "Viewer access revoked")
                return has_permission(current_user.role, "stream:control")
        except HTTPException as exc:
            code, reason = {
                401: (4001, "invalid_token"),
                403: (4003, "stream_access_denied"),
                404: (4004, "device_not_found"),
            }.get(exc.status_code, (1013, "stream_auth_unavailable"))
        except Exception as exc:
            code, reason = 1013, "stream_auth_unavailable"
            logger.warning("stream_viewer_auth_unavailable", device_id=device_id,
                           session_id=session_id, error_type=type(exc).__name__)
        # Retire the sender before closing. A client that never acknowledges
        # close must not retain video or keep the route's receiver alive.
        try:
            await bridge.unregister_viewer(device_id, session_id)
            await ws.close(code=code, reason=reason)
        finally:
            auth_stopped.set()
        return None

    # Reuse the existing ten-second keepalive cadence for passive-view access
    # checks. Video bytes never wait on these SQL/Redis reads. Input validates
    # immediately before dispatch instead of caching the handshake's grant.
    async def _viewer_ping_loop() -> None:
        try:
            while True:
                if history_enabled:
                    await history.observe_agent(org_id_str, device_id, session_id)
                await asyncio.sleep(VIEWER_AUTH_RECHECK_SECONDS)
                try:
                    if await current_control_permission() is None:
                        break
                    await ws.send_json({"type": "ping"})
                except Exception:
                    auth_stopped.set()
                    break
        except asyncio.CancelledError:
            pass

    ping_task = asyncio.create_task(_viewer_ping_loop())
    stop_task = asyncio.create_task(auth_stopped.wait())

    async def device_task_idle() -> bool:
        async with asyncio.timeout(0.5), AsyncSessionLocal() as db:
            from sqlalchemy import select

            from backend.database.tenant import bind_tenant_context
            from backend.models.task import Task, TaskStatus
            await bind_tenant_context(db, org_id_str)
            running = await db.scalar(select(Task.id).where(
                Task.device_id == device_uuid, Task.org_id == user.org_id,
                Task.status.in_([TaskStatus.ASSIGNED, TaskStatus.RUNNING]),
            ).limit(1))
        return running is None

    async def current_touch_permission() -> bool:
        return bool(await current_control_permission()) and await device_task_idle()

    async def _touch_auth_loop() -> None:
        # Separate from MOVE cadence and video. Fresh control authorization
        # renews only auth, never the viewer/native owner lease.
        while True:
            await asyncio.sleep(0.75)
            if not touch_viewer.lease or touch_viewer.closing or not touch_runtime:
                continue
            try:
                # Native ownership independently excludes DAG/discrete actions.
                # Server denies opening/continuing while a known task is running.
                await touch_runtime.recheck_authorization(touch_viewer, current_touch_permission)
            except Exception:
                pass  # The bounded check already retired its owner; video stays independent.

    touch_auth_task = asyncio.create_task(_touch_auth_loop())

    try:
        if history_enabled:
            diagnostic_writer = asyncio.create_task(write_diagnostics())
        if history_enabled:
            await ws.send_json({"type": "stream_session", "schema_version": 1, "session_id": session_id,
                                "history_enabled": True, "report_interval_seconds": REPORT_INTERVAL_SECONDS})
        await send_control({"type": "viewer_connected", "session_id": session_id})
        while True:
            receive_task = asyncio.create_task(ws.receive_json())
            try:
                done, _ = await asyncio.wait((receive_task, stop_task), return_when=asyncio.FIRST_COMPLETED)
                if stop_task in done:
                    break
                try:
                    data = await receive_task
                except (ValueError, RecursionError):
                    # Includes JSON/UTF-8 decoding and Python's integer digit /
                    # nesting limits. Do not echo decoder exception contents.
                    await ws.send_json({"type": "error", "error": "stream_input_invalid", "reason": "invalid_message"})
                    continue
            finally:
                if not receive_task.done():
                    receive_task.cancel()
                await asyncio.gather(receive_task, return_exceptions=True)
            if isinstance(data, dict) and isinstance(data.get("type"), str) and data["type"] in {"viewer_telemetry", "viewer_direct_result"}:
                # This branch terminates at diagnostic storage. It never forwards
                # a browser-supplied payload to Android or changes input ownership.
                now = time.monotonic()
                if history_enabled and set(data) == {"type", "sample"}:
                    if data["type"] == "viewer_telemetry" and now - last_browser_report >= 1:
                        last_browser_report = now
                        sample = history.validated_sample(data["sample"])
                        if sample is not None:
                            enqueue_diagnostic("browser_samples", sample)
                    elif data["type"] == "viewer_direct_result" and direct_reports < 3 and now - last_direct_report >= 1:
                        last_direct_report = now
                        direct_reports += 1
                        sample = history.validated_sample(data["sample"], probe=True)
                        if sample is not None:
                            enqueue_diagnostic("direct_diagnostics", sample, 3)
                continue
            if isinstance(data, dict) and isinstance(data.get("type"), str) and data["type"] in {"touch_probe", "touch_open", "touch_event", "touch_close"}:
                rejection: dict[str, Any] = {"type": "touch_error", "error": "input_rejected_or_unavailable"}
                try:
                    if not touch_registered or not touch_runtime:
                        raise InputLeaseUnavailable()
                    if data["type"] in {"touch_probe", "touch_open"}:
                        allowed = await current_control_permission()
                        if allowed is None:
                            break  # Authentication already retired and closed this viewer.
                        if not allowed:
                            rejection = {"type": "touch_error", "error": "control_denied", "retryable": False}
                            raise PermissionError()
                        if data["type"] == "touch_open" and not await device_task_idle():
                            if touch_viewer.lease is None and not touch_viewer.closing:
                                raise ContinuousAdmissionRejected("task_running")
                            raise PermissionError()
                    await touch_runtime.handle(touch_viewer, data)
                except Exception as exc:
                    if isinstance(exc, ContinuousAdmissionRejected) and touch_viewer.lease is None:
                        rejection = {"type": "touch_error", "error": "input_admission_rejected",
                                     "reason": exc.reason, "retryable": True}
                    elif isinstance(exc, (InputLeaseUnavailable, TimeoutError)):
                        rejection = {"type": "touch_error", "error": "input_temporarily_unavailable",
                                     "reason": "runtime_unavailable", "retryable": True}
                    logger.info("stream_touch_rejected", device_id=device_id, session_id=session_id,
                                message_type=data["type"], reason=rejection.get("reason", rejection["error"]),
                                retryable=rejection.get("retryable", False), owner_bound=touch_viewer.lease is not None,
                                error_type=type(exc).__name__)
                    rejection["operation"] = data["type"]
                    if history_enabled:
                        enqueue_diagnostic("control_events", {
                            "operation": data["type"], "error": rejection["error"],
                            "reason": rejection.get("reason"), "retryable": rejection.get("retryable", False),
                            "owner_bound": touch_viewer.lease is not None,
                        }, limit=8)
                    if touch_viewer.lease is not None:
                        rejection["owner"] = touch_viewer.lease.owner
                    if touch_runtime:
                        await touch_runtime.retire(touch_viewer)
                    await ws.send_json(rejection)
                continue
            try:
                control = viewer_command(data)
            except InvalidViewerInput as exc:
                await ws.send_json({"type": "error", "error": "stream_input_invalid", "reason": exc.reason})
                continue
            if control is None:
                continue
            if control["type"] in {"touch_tap", "touch_swipe", "keyevent", "text"}:
                if touch_viewer.lease is not None:
                    await ws.send_json({"type": "touch_error", "error": "close_gestures_before_discrete_input"})
                    continue
                can_control = await current_control_permission()
                if can_control is None:
                    break
                if not can_control:
                    await ws.send_json({"type": "error", "error": "stream_control_denied"})
                    continue
                # The browser cannot supply or replace the authenticated viewer identity.
                control["session_id"] = session_id
            await send_control(control)
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
            error_type=type(exc).__name__,
        )
    finally:
        ping_task.cancel()
        stop_task.cancel()
        touch_auth_task.cancel()
        await asyncio.gather(ping_task, stop_task, touch_auth_task, return_exceptions=True)
        if touch_registered and touch_runtime:
            await touch_runtime.unregister(touch_viewer)
        await bridge.unregister_viewer(device_id, session_id)
        if history_enabled:
            try:
                async with asyncio.timeout(0.5):
                    await diagnostic_queue.join()
            except TimeoutError:
                pass
            if diagnostic_writer:
                diagnostic_writer.cancel()
                await asyncio.gather(diagnostic_writer, return_exceptions=True)
            await history.end(org_id_str, device_id, session_id)
        logger.info(
            "Stream viewer disconnected",
            device_id=device_id,
            session_id=session_id,
        )
