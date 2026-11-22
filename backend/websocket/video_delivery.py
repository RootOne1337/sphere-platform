"""Explicit media handover; browser diagnostics remain storage-only."""
from __future__ import annotations

import re
from typing import Any

from backend.websocket.direct_probe_protocol import InvalidDirectProbe


def delivery_mode(data: Any) -> tuple[bool, str | None]:
    if not isinstance(data, dict) or data.get("type") != "video_delivery":
        raise ValueError("invalid_video_delivery")
    if data == {"type": "video_delivery", "mode": "legacy"}:
        return True, None
    if (data.keys() == {"type", "mode", "peer_session"} and data.get("mode") == "direct"
            and isinstance(data["peer_session"], str) and re.fullmatch(r"[0-9a-f]{32}", data["peer_session"])):
        return False, data["peer_session"]
    raise ValueError("invalid_video_delivery")


async def select_delivery(data: Any, *, runtime, bridge, device: str, org: str, user: str, viewer_session: str) -> str:
    legacy, peer = delivery_mode(data)
    if not legacy and (not runtime or not await runtime.video_peer(
            device=device, org=org, user=user, session=peer, viewer_session=viewer_session)):
        raise InvalidDirectProbe("video_delivery_unavailable")
    if not await bridge.set_legacy_delivery(device, viewer_session, legacy):
        raise InvalidDirectProbe("video_delivery_unavailable")
    return "legacy" if legacy else "direct"
