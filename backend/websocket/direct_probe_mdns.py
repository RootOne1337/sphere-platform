"""Resolve authenticated ICE host names on a nearby host; never proxy media/input.

Some emulator networks cannot deliver Chromium's multicast DNS responses to
Android. The optional local helper performs that one discovery step. Failure
preserves the original offer, and normal ICE/fallback behavior remains intact.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from prometheus_client import Counter, Histogram

from backend.core.config import settings

MAX_NAMES = 4
MAX_RESPONSE_BYTES = 2048
HELPER_SECONDS = 0.8
PRIVATE_V4 = tuple(ipaddress.ip_network(value) for value in
                   ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
RESOLUTIONS = Counter("sphere_direct_mdns_resolution_total", "Discovery-only ICE hostname outcomes", ["outcome"])
RESOLUTION_SECONDS = Histogram("sphere_direct_mdns_resolution_seconds", "Local ICE name discovery duration",
                               buckets=(.01, .025, .05, .1, .25, .5, .8, 1))


def valid_name(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith(".local"):
        return False
    try:
        return str(UUID(value[:-6])) == value[:-6]
    except (ValueError, AttributeError):
        return False


def candidate_names(sdp: str) -> tuple[str, ...]:
    names: dict[str, None] = {}
    for line in sdp.splitlines():
        fields = line.split()
        if (len(fields) >= 8 and fields[0].startswith("a=candidate:")
                and fields[1] in {"1", "2"} and fields[2].lower() == "udp"
                and fields[6:8] == ["typ", "host"] and valid_name(fields[4])):
            names[fields[4]] = None
    return tuple(names) if len(names) <= MAX_NAMES else ()


def valid_helper_url(value: str) -> bool:
    """Operator configuration only; peer offers cannot provide discovery URLs."""
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "host.docker.internal"}
                    and parsed.port and 1024 <= parsed.port <= 65535
                    and parsed.netloc == f"{parsed.hostname}:{parsed.port}"
                    and parsed.path == "/v1/mdns" and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def reply_mapping(data: object, session: str, names: tuple[str, ...]) -> dict[str, str]:
    if (not isinstance(data, dict) or data.keys() != {"version", "session", "resolved"}
            or type(data["version"]) is not int or data["version"] != 1 or data["session"] != session
            or not isinstance(data["resolved"], list) or len(data["resolved"]) > len(names)):
        raise ValueError("invalid_mdns_reply")
    result: dict[str, str] = {}
    for row in data["resolved"]:
        if (not isinstance(row, dict) or row.keys() != {"name", "address"}
                or row["name"] not in names or row["name"] in result or not isinstance(row["address"], str)):
            raise ValueError("invalid_mdns_reply")
        address = ipaddress.ip_address(row["address"])
        if not isinstance(address, ipaddress.IPv4Address) or not any(address in subnet for subnet in PRIVATE_V4):
            raise ValueError("invalid_mdns_address")
        result[row["name"]] = str(address)
    return result


def apply_mapping(sdp: str, mapping: dict[str, str]) -> str:
    """Change exactly candidate address tokens; retain crypto, ports and all other SDP bytes."""
    lines: list[str] = []
    for line in sdp.splitlines(keepends=True):
        tokens = list(re.finditer(r"\S+", line))
        if len(tokens) >= 8:
            fields = [token.group() for token in tokens]
            if (fields[0].startswith("a=candidate:") and fields[1] in {"1", "2"}
                    and fields[2].lower() == "udp" and fields[6:8] == ["typ", "host"]
                    and fields[4] in mapping):
                address = tokens[4]
                line = line[:address.start()] + mapping[fields[4]] + line[address.end():]
        lines.append(line)
    return "".join(lines)


async def resolve_offer(sdp: str, session: str) -> str:
    url = settings.DIRECT_PROBE_MDNS_RESOLVER_URL
    key = settings.DIRECT_PROBE_MDNS_RESOLVER_KEY.get_secret_value()
    names = candidate_names(sdp)
    if not url or not key or not names:
        return sdp
    if not valid_helper_url(url) or not 32 <= len(key) <= 256 or not re.fullmatch(r"[0-9a-f]{32}", session):
        RESOLUTIONS.labels("unconfigured").inc()
        return sdp
    try:
        with RESOLUTION_SECONDS.time():
            async with asyncio.timeout(HELPER_SECONDS), httpx.AsyncClient(
                timeout=HELPER_SECONDS, trust_env=False, follow_redirects=False,
            ) as client:
                # Streaming limits retained bytes even for a faulty/hostile helper.
                async with client.stream("POST", url, headers={"Authorization": "Bearer " + key},
                                         json={"version": 1, "session": session, "names": list(names)}) as response:
                    response.raise_for_status()
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(payload) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ValueError("mdns_reply_too_large")
                        payload.extend(chunk)
        mapping = reply_mapping(json.loads(payload), session, names)
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, UnicodeError):
        RESOLUTIONS.labels("unavailable").inc()
        return sdp
    RESOLUTIONS.labels("resolved" if mapping else "unresolved").inc()
    return apply_mapping(sdp, mapping)
