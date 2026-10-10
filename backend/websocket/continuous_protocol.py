"""Canary contracts, deliberately separate from the installed discrete WS route.

Browser data never chooses an owner, user, tenant, worker or APK socket. A
validated object is not a permission grant or proof of displayed capture.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

MAX_DIMENSION = 16_384
MAX_SEQUENCE = 2_147_483_647
MAX_GESTURE = MAX_SEQUENCE  # Also exact under Redis Lua cjson's number precision.
MAX_JSON_INTEGER = 9_007_199_254_740_991
DOWN, UP, MOVE, CANCEL, HEARTBEAT = range(5)


class InvalidContinuousInput(ValueError):
    def __init__(self) -> None:
        super().__init__("continuous_input_invalid")


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidContinuousInput()
    return value


def capture_uuid(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise InvalidContinuousInput()
    try:
        parsed = UUID(value)
    except ValueError:
        raise InvalidContinuousInput() from None
    if parsed.int == 0 or str(parsed) != value:
        raise InvalidContinuousInput()
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        raise InvalidContinuousInput()
    if not value.isascii() or any(not (c.isalnum() or c in "_-") for c in value):
        raise InvalidContinuousInput()
    return value


def _exact(message: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(message, dict) or message.keys() != keys:
        raise InvalidContinuousInput()
    return message


@dataclass(frozen=True)
class CaptureBinding:
    epoch: str
    width: int
    height: int

    def __post_init__(self) -> None:
        capture_uuid(self.epoch)
        _integer(self.width, 1, MAX_DIMENSION)
        _integer(self.height, 1, MAX_DIMENSION)


@dataclass(frozen=True)
class TouchEvent:
    sequence: int
    gesture: int
    action: int
    x: int
    y: int

    def __post_init__(self) -> None:
        _integer(self.sequence, 1, MAX_SEQUENCE)
        _integer(self.gesture, 0, MAX_GESTURE)
        _integer(self.action, DOWN, HEARTBEAT)
        _integer(self.x, 0, MAX_DIMENSION - 1)
        _integer(self.y, 0, MAX_DIMENSION - 1)
        if self.action != HEARTBEAT and self.gesture == 0:
            raise InvalidContinuousInput()

    def inside(self, capture: CaptureBinding) -> bool:
        return self.x < capture.width and self.y < capture.height


@dataclass(frozen=True)
class CloseInput:
    pass


def viewer_continuous(message: Any) -> CaptureBinding | TouchEvent | CloseInput:
    """Strict proposed browser protocol. No owner/identity metadata is ignored."""
    if not isinstance(message, dict):
        raise InvalidContinuousInput()
    kind = message.get("type")
    if kind == "touch_open":
        _exact(message, {"type", "capture_epoch", "frame_width", "frame_height"})
        return CaptureBinding(message["capture_epoch"], message["frame_width"], message["frame_height"])
    if kind == "touch_event":
        _exact(message, {"type", "sequence", "gesture", "action", "x", "y"})
        return TouchEvent(**{name: message[name] for name in ("sequence", "gesture", "action", "x", "y")})
    if kind == "touch_close":
        _exact(message, {"type"})
        return CloseInput()
    raise InvalidContinuousInput()


@dataclass(frozen=True)
class InputReceipt:
    session: str
    owner: str
    epoch: str
    sequence: int
    status: int
    stage: str
    origin: str
    uptime_ms: int

    @classmethod
    def parse(cls, message: Any) -> InputReceipt:
        _exact(message, {"type", "session_id", "owner", "capture_epoch", "sequence", "status", "stage", "origin", "device_uptime_ms"})
        if message["type"] != "continuous_input_status":
            raise InvalidContinuousInput()
        stage, origin = message["stage"], message["origin"]
        if stage not in ("startup", "input", "release") or origin not in ("injector", "admission"):
            raise InvalidContinuousInput()
        sequence = _integer(message["sequence"], 0, MAX_SEQUENCE)
        status = _integer(message["status"], 0, 6)
        if stage != "input" and sequence != 0:
            raise InvalidContinuousInput()
        if status == 0 and (stage != "startup" or origin != "injector"):
            raise InvalidContinuousInput()
        if stage == "startup" and status not in (0, 5, 6):
            raise InvalidContinuousInput()
        if stage == "release" and (origin != "injector" or status not in (3, 6)):
            raise InvalidContinuousInput()
        if origin == "admission" and status != 5:
            raise InvalidContinuousInput()
        return cls(identifier(message["session_id"]), identifier(message["owner"]),
                   capture_uuid(message["capture_epoch"]), sequence, status, stage, origin,
                   _integer(message["device_uptime_ms"], 0, MAX_JSON_INTEGER))

    @property
    def ready(self) -> bool:
        return self.stage == "startup" and self.origin == "injector" and self.status == 0

    @property
    def released(self) -> bool:
        return self.stage == "release" and self.origin == "injector" and self.status == 3

    @property
    def failed(self) -> bool:
        return self.status in (4, 5, 6)
