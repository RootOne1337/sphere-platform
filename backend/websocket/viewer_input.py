"""Strict admission of the existing discrete viewer protocol, not injection.

Never invent missing coordinates, coerce JSON values or echo private input.
Physical display bounds and execution remain the installed APK's authority.
"""
from __future__ import annotations

from typing import Any

ANDROID_INT_MAX = 2_147_483_647
MAX_SWIPE_DURATION_MS = 60_000
MAX_TEXT_CHARACTERS = 65_536
MAX_TEXT_BYTES = 262_144


class InvalidViewerInput(ValueError):
    """A fixed reason code, without input values, field names or exception text."""

    def __init__(self, reason: str = "invalid_message") -> None:
        super().__init__(reason)
        self.reason = reason


def viewer_command(message: Any) -> dict[str, Any] | None:
    """Translate one validated legacy message; caller owns auth and session ID.

    Existing omitted swipe duration keeps its documented 300 ms default.
    Unknown metadata is ignored and never forwarded. Unsupported message types
    are rejected rather than interpreted as a new Android capability.
    """
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise InvalidViewerInput()
    kind = message["type"]

    def integer(name: str, maximum: int = ANDROID_INT_MAX, default: int | None = None) -> int:
        value = message.get(name, default)
        if type(value) is not int or not 0 <= value <= maximum:
            raise InvalidViewerInput("invalid_parameter")
        return value

    if kind == "click":
        return {"type": "touch_tap", "x": integer("x"), "y": integer("y")}
    if kind == "swipe":
        return {"type": "touch_swipe", **{name: integer(name) for name in ("x1", "y1", "x2", "y2")},
                "duration_ms": integer("duration_ms", MAX_SWIPE_DURATION_MS, 300)}
    if kind == "keyevent":
        return {"type": "keyevent", "code": integer("code")}
    if kind == "text":
        value = message.get("text")
        if not isinstance(value, str) or len(value) > MAX_TEXT_CHARACTERS:
            raise InvalidViewerInput("invalid_parameter")
        try:
            if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
                raise InvalidViewerInput("invalid_parameter")
        except UnicodeEncodeError:
            raise InvalidViewerInput("invalid_parameter") from None
        return {"type": "text", "text": value}
    if kind == "request_keyframe":
        return {"type": "request_keyframe"}
    if kind == "pong":
        return None
    raise InvalidViewerInput("unsupported_message")
