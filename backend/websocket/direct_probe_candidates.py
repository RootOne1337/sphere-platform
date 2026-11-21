"""Bounded ephemeral trickle candidates; no logs, address storage or replay queue."""
from __future__ import annotations

import ipaddress
import re
from typing import Any

from backend.websocket.direct_probe_protocol import InvalidDirectProbe

MAX_CANDIDATES = 64
MAX_CANDIDATE_BYTES = 2048
MIN_TRICKLE_AGENT_CODE = 10273
MDNS = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.local")


def candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() != {"candidate", "sdpMid", "sdpMLineIndex"}:
        raise InvalidDirectProbe("invalid_ice_candidate")
    raw, mid, index = value["candidate"], value["sdpMid"], value["sdpMLineIndex"]
    if (not isinstance(raw, str) or not 1 <= len(raw.encode()) <= MAX_CANDIDATE_BYTES
            or "\r" in raw or "\n" in raw or not raw.isascii()
            or not isinstance(mid, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,16}", mid) is None
            or type(index) is not int or not 0 <= index <= 7):
        raise InvalidDirectProbe("invalid_ice_candidate")
    fields = raw.split()
    if (len(fields) < 8 or len(fields) > 32 or not fields[0].startswith("candidate:")
            or re.fullmatch(r"candidate:[A-Za-z0-9+/_-]{1,64}", fields[0]) is None
            or fields[1] not in {"1", "2"} or fields[2].lower() != "udp"
            or not fields[3].isdigit() or not 1 <= int(fields[3]) <= 0xffffffff
            or not fields[5].isdigit() or not 1 <= int(fields[5]) <= 65535
            or fields[6] != "typ" or fields[7] not in {"host", "srflx", "prflx"}):
        raise InvalidDirectProbe("invalid_ice_candidate")
    try:
        ipaddress.ip_address(fields[4])
    except ValueError:
        if MDNS.fullmatch(fields[4]) is None:
            raise InvalidDirectProbe("invalid_ice_candidate") from None
    return {"candidate": raw, "sdpMid": mid, "sdpMLineIndex": index}
