"""Bounded viewer/server echo; never forwards anything to the Android agent."""
from __future__ import annotations

import math
from typing import Any


class ViewerLinkProbe:
    def __init__(self) -> None:
        self.last_reply = -math.inf

    def reply(self, message: Any, now: float) -> dict[str, Any] | None:
        if not isinstance(message, dict) or set(message) != {"type", "sequence"}:
            return None
        sequence = message.get("sequence")
        if message.get("type") != "stream_link_probe" or type(sequence) is not int:
            return None
        if not 1 <= sequence <= 2_147_483_647 or not math.isfinite(now) or now - self.last_reply < 1:
            return None
        self.last_reply = now
        return {"type": "stream_link_result", "sequence": sequence}
