"""Opt-in 30-second echo or read-only RTP video; shared stream authentication/RBAC."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.api.ws.stream.router import _authenticate_viewer
from backend.core.config import settings
from backend.core.rbac import has_permission
from backend.database.engine import AsyncSessionLocal
from backend.models.device import Device
from backend.websocket.direct_probe_ice import issue_turn_grant
from backend.websocket.direct_probe_protocol import (
    MAX_WIRE_BYTES,
    SESSION_MS,
    InvalidDirectProbe,
    viewer_offer,
)
from backend.websocket.direct_probe_runtime import ProbeViewer, get_direct_probe_runtime

router = APIRouter(tags=["direct-transport-canary"])


async def close_probe(ws: WebSocket, code: int, reason: str) -> None:
    # The browser can send an explicit stop and close its socket immediately.
    # A concurrent worker retirement may also have closed it already.
    try:
        async with asyncio.timeout(1):
            await ws.close(code=code, reason=reason)
    except (WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
        pass


async def authorize(token: str, device_id: str) -> tuple[str, str]:
    async with asyncio.timeout(2):
        async with AsyncSessionLocal() as db:
            user = await _authenticate_viewer(token, db)
            device = await db.get(Device, uuid.UUID(device_id))
            if not device or not device.is_active or device.org_id != user.org_id or not has_permission(user.role, "stream:read"):
                raise HTTPException(status_code=403, detail="probe_access_denied")
            return str(user.org_id), str(user.id)


@router.websocket("/ws/direct-probe/{device_id}")
async def direct_probe_ws(ws: WebSocket, device_id: str) -> None:
    await ws.accept()
    runtime = get_direct_probe_runtime()
    if not settings.DIRECT_TRANSPORT_PROBE_ENABLED or not runtime or not runtime.available:
        await close_probe(ws, 4003, "direct_probe_disabled")
        return
    if device_id not in settings.DIRECT_TRANSPORT_PROBE_DEVICE_IDS:
        await close_probe(ws, 4003, "direct_probe_device_disabled")
        return
    viewer: ProbeViewer | None = None
    try:
        async with asyncio.timeout(10):
            raw = await ws.receive_text()
        if len(raw.encode()) > 8192:
            raise InvalidDirectProbe("invalid_auth")
        import json
        first = json.loads(raw)
        if (not isinstance(first, dict) or first.keys() not in ({"token"}, {"token", "protocol"}, {"token", "protocol", "relay"})
                or "protocol" in first and first["protocol"] not in {"sphere-probe-v2", "sphere-video-probe-v1"}
                or "relay" in first and (first.get("protocol") != "sphere-video-probe-v1" or first["relay"] is not True)
                or not isinstance(first["token"], str) or not first["token"]):
            raise InvalidDirectProbe("invalid_auth")
        identity = await authorize(first["token"], device_id)
        video = first.get("protocol") == "sphere-video-probe-v1"
        if video and not settings.DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED:
            raise InvalidDirectProbe("video_probe_disabled")
        viewer = ProbeViewer(device_id, *identity, ws, video=video)
        if first.get("protocol") == "sphere-probe-v2" or video and first.get("relay") is True:
            await runtime.prepare(viewer)
            options = dict(relay_only=settings.DIRECT_PROBE_TURN_RELAY_ONLY)
            secret = settings.DIRECT_PROBE_TURN_SECRET.get_secret_value()
            viewer.ice = issue_turn_grant(settings.DIRECT_PROBE_TURN_URLS, secret, viewer.session, "agent", **options).wire()
            browser_ice = issue_turn_grant(settings.DIRECT_PROBE_TURN_URLS, secret, viewer.session, "browser", **options)
            async with asyncio.timeout(1):
                await ws.send_json(dict(type="direct_probe_ready", protocol=first["protocol"],
                                        session_id=viewer.session, ice=browser_ice.wire()))
        async with asyncio.timeout(10):
            raw = await ws.receive_text()
        if len(raw.encode()) > MAX_WIRE_BYTES:
            raise InvalidDirectProbe("message_too_large")
        await runtime.open(viewer, viewer_offer(json.loads(raw), video=video))
        # Token revocation and device/role changes close the signaling grant.
        # APK also enforces a nonrenewable local TTL if the signaling path disappears.
        async with asyncio.timeout(SESSION_MS / 1000):
            while True:
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), 5)
                except asyncio.TimeoutError:
                    if video and not settings.DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED:
                        raise InvalidDirectProbe("video_probe_disabled")
                    if await authorize(first["token"], device_id) != identity:
                        raise InvalidDirectProbe("probe_access_revoked")
                    async with asyncio.timeout(2):
                        if not viewer.binding or not await runtime.remaining(viewer.binding):
                            raise InvalidDirectProbe("probe_expired")
                    continue
                if raw != '{"type":"direct_probe_close"}':
                    raise InvalidDirectProbe("unexpected_probe_message")
                break
    except WebSocketDisconnect:
        return
    except (HTTPException, InvalidDirectProbe, ValueError, TypeError, TimeoutError):
        await close_probe(ws, 4003, "direct_probe_rejected_or_expired")
        return
    except Exception:
        await close_probe(ws, 1013, "direct_probe_unavailable")
        return
    finally:
        if viewer:
            await runtime.retire(viewer)
    await close_probe(ws, 1000, "probe_finished")
