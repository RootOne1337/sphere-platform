"""Data-channel-only canary; never authorizes media, input or command execution."""
from __future__ import annotations

import re

MAX_SDP_BYTES = 32_768
MAX_WIRE_BYTES = 36_864
SESSION_MS = 30_000
MAX_PEERS = 8
CHANNEL_LABEL = "sphere-probe-v1"


class InvalidDirectProbe(ValueError):
    pass


def session_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise InvalidDirectProbe("invalid_session")
    return value


def description(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value.encode()) <= MAX_SDP_BYTES:
        raise InvalidDirectProbe("invalid_description")
    lines = value.splitlines()
    media = [line for line in lines if line.startswith("m=")]
    fingerprints = [line for line in lines if line.startswith("a=fingerprint:")]
    if (not lines or lines[0] != "v=0" or len(media) != 1
            or not media[0].startswith("m=application ")
            or "UDP/DTLS/SCTP" not in media[0]
            or not fingerprints or len(fingerprints) > 2
            or any(not re.fullmatch(r"a=fingerprint:sha-256 (?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}", f)
                   for f in fingerprints)
            or sum(line.startswith("a=candidate:") for line in lines) > 64):
        raise InvalidDirectProbe("invalid_description")
    return value


def viewer_offer(data: object) -> str:
    if not isinstance(data, dict) or data.keys() != {"type", "sdp"} or data["type"] != "direct_probe_offer":
        raise InvalidDirectProbe("invalid_offer")
    return description(data["sdp"])


def agent_answer(data: object) -> tuple[str, str]:
    if not isinstance(data, dict) or data.keys() != {"type", "session_id", "sdp"} or data["type"] != "direct_probe_answer":
        raise InvalidDirectProbe("invalid_answer")
    return session_id(data["session_id"]), description(data["sdp"])
