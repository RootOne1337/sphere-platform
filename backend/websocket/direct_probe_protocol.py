"""Finite echo and separately admitted read-only RTP video; no Android input."""
from __future__ import annotations

import re

MAX_SDP_BYTES = 32_768
MAX_WIRE_BYTES = 36_864
SESSION_MS = 30_000
MAX_PEERS = 8
CHANNEL_LABEL = "sphere-probe-v1"
VIDEO_MODE = "readonly_video_v1"
VIDEO_MIN_AGENT_CODE = 10251


class InvalidDirectProbe(ValueError):
    pass


def session_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise InvalidDirectProbe("invalid_session")
    return value


def description(value: object, *, video: bool = False, offer: bool = True) -> str:
    if not isinstance(value, str) or not 0 < len(value.encode()) <= MAX_SDP_BYTES:
        raise InvalidDirectProbe("invalid_description")
    lines = value.splitlines()
    media = [line for line in lines if line.startswith("m=")]
    fingerprints = [line for line in lines if line.startswith("a=fingerprint:")]
    sections: list[list[str]] = []
    for line in lines:
        if line.startswith("m="):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
    application = [s for s in sections if s[0].startswith("m=application ")]
    picture = [s for s in sections if s[0].startswith("m=video ")]
    valid_media = (len(media) == 1 and len(application) == 1) if not video else (
        len(media) == 2 and len(application) == 1 and len(picture) == 1
        and "UDP/TLS/RTP/SAVPF" in picture[0][0]
        and sum(line in {"a=recvonly", "a=sendonly", "a=sendrecv", "a=inactive"} for line in picture[0]) == 1
        and ("a=recvonly" if offer else "a=sendonly") in picture[0]
        and any(re.fullmatch(r"a=rtpmap:[0-9]+ H264/90000", line, re.I) for line in picture[0]))
    if (not lines or lines[0] != "v=0" or not valid_media
            or not application or "UDP/DTLS/SCTP" not in application[0][0]
            or not fingerprints or len(fingerprints) > (3 if video else 2)
            or any(not re.fullmatch(r"a=fingerprint:sha-256 (?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}", f)
                   for f in fingerprints)
            or sum(line.startswith("a=candidate:") for line in lines) > 64):
        raise InvalidDirectProbe("invalid_description")
    return value


def viewer_offer(data: object, *, video: bool = False) -> str:
    if not isinstance(data, dict) or data.keys() != {"type", "sdp"} or data["type"] != "direct_probe_offer":
        raise InvalidDirectProbe("invalid_offer")
    return description(data["sdp"], video=video, offer=True)


def agent_answer(data: object, *, video: bool = False) -> tuple[str, str]:
    if not isinstance(data, dict) or data.keys() != {"type", "session_id", "sdp"} or data["type"] != "direct_probe_answer":
        raise InvalidDirectProbe("invalid_answer")
    return session_id(data["session_id"]), description(data["sdp"], video=video, offer=False)
