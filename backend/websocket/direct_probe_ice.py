"""Short-lived coturn REST credentials; no client-selected endpoint or shared key on wire."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import re
import time
from dataclasses import dataclass, field

from backend.websocket.direct_probe_protocol import InvalidDirectProbe, session_id

TURN_CREDENTIAL_SECONDS = 120
MAX_TURN_URLS = 3


def turn_url(value: object) -> str:
    # This version deliberately accepts canonical IPv4/DNS only. IPv6 needs its own
    # cross-runtime fixture and network acceptance, rather than a permissive parser.
    if not isinstance(value, str) or len(value) > 320:
        raise InvalidDirectProbe("invalid_turn_url")
    match = re.fullmatch(r"(turn|turns):([a-z0-9.-]{1,253}):([1-9][0-9]{0,4})\?transport=(udp|tcp)", value)
    if not match:
        raise InvalidDirectProbe("invalid_turn_url")
    scheme, host, port, transport = match.groups()
    if int(port) > 65535 or scheme == "turns" and transport != "tcp":
        raise InvalidDirectProbe("invalid_turn_url")
    if re.fullmatch(r"[0-9.]+", host):
        try:
            address = ipaddress.IPv4Address(host)
            if str(address) != host or int(address) < 0x01000000 or address.is_loopback or address.is_multicast or address.is_link_local or int(address) >= 0xF0000000:
                raise ValueError()
        except ValueError:
            raise InvalidDirectProbe("invalid_turn_url") from None
    elif ("." not in host or not re.fullmatch(r"[a-z][a-z0-9-]*", host.split(".")[-1])
          or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split("."))):
        raise InvalidDirectProbe("invalid_turn_url")
    return value


def turn_urls(values: object) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= MAX_TURN_URLS:
        raise InvalidDirectProbe("invalid_turn_urls")
    result = tuple(turn_url(value) for value in values)
    if len(set(result)) != len(result):
        raise InvalidDirectProbe("invalid_turn_urls")
    return result


@dataclass(frozen=True, repr=False)
class ProbeIceGrant:
    urls: tuple[str, ...]
    username: str = field(repr=False)
    credential: str = field(repr=False)
    policy: str

    def wire(self) -> dict:
        return dict(urls=list(self.urls), username=self.username, credential=self.credential,
                    ttl_ms=TURN_CREDENTIAL_SECONDS * 1000, policy=self.policy)


def issue_turn_grant(urls: tuple[str, ...], secret: str, session: str, side: str,
                     *, relay_only: bool = False, now: float | None = None) -> ProbeIceGrant:
    urls = turn_urls(urls)
    session_id(session)
    if side not in {"browser", "agent"} or not isinstance(secret, str) or not 32 <= len(secret) <= 256 or not secret.isascii() or any(c.isspace() for c in secret):
        raise InvalidDirectProbe("invalid_turn_configuration")
    clock = time.time() if now is None else now
    if not isinstance(clock, (int, float)) or not 1_000_000_000 <= clock < 9_999_999_000:
        raise InvalidDirectProbe("invalid_turn_clock")
    # Opaque session nonce instead of tenant/user/device identifiers in relay logs.
    username = f"{int(clock) + TURN_CREDENTIAL_SECONDS}:{session}:{side}"
    credential = base64.b64encode(hmac.new(secret.encode("ascii"), username.encode("ascii"), hashlib.sha1).digest()).decode("ascii")
    return ProbeIceGrant(urls, username, credential, "relay" if relay_only else "all")


def validate_turn_grant(value: object, session: str, side: str) -> dict:
    """Validate internal pubsub before it can allocate native resources."""
    session_id(session)
    if (not isinstance(value, dict) or value.keys() != {"urls", "username", "credential", "ttl_ms", "policy"}
            or type(value["ttl_ms"]) is not int or value["ttl_ms"] != TURN_CREDENTIAL_SECONDS * 1000
            or value["policy"] not in ("all", "relay")
            or not isinstance(value["username"], str)
            or not re.fullmatch(r"[1-9][0-9]{9}:" + session + ":" + side, value["username"])
            or not isinstance(value["credential"], str) or not re.fullmatch(r"[A-Za-z0-9+/]{27}=", value["credential"])):
        raise InvalidDirectProbe("invalid_turn_grant")
    turn_urls(value["urls"])
    return value
