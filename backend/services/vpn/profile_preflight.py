"""Pure VPN profile inspection. No DNS, subprocess, database or provider I/O.

This is a bounded import contract, not an AWG implementation. In particular a
valid profile is not a permission to run wg-quick or mutate Android routing.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import re

from backend.schemas.vpn.profile import (
    VPNProfileIssue,
    VPNProfilePreflightRequest,
    VPNProfilePreflightResponse,
    provider_capabilities,
)

_BASE_INTERFACE = {"privatekey", "address", "dns", "mtu", "listenport"}
_PEER = {"publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive"}
_AWG1 = {"jc", "jmin", "jmax", "s1", "s2", "h1", "h2", "h3", "h4"}
_CPS = {"i1", "i2", "i3", "i4", "i5"}
_AWG2 = {"s3", "s4"}
_AWG31 = {
    "headerprotectionkey", "contentpaddingaddition", "rekeyaftertime", "rekeytimeout",
    "rejectaftertime", "keepalivetimeout", "maxhandshakeattempts", "randomtrailers", "disablecookies",
}
_HOOKS = {"preup", "postup", "predown", "postdown", "saveconfig", "table", "fwmark"}
_TAG = re.compile(r"<(b 0x[0-9a-fA-F]+|t|r [0-9]+|rc [0-9]+|rd [0-9]+)>")


def _range(value: str, maximum: int, allow_range: bool = True) -> tuple[int, int]:
    if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?" if allow_range else r"[0-9]+", value):
        raise ValueError
    parts = value.split("-")
    low, high = int(parts[0]), int(parts[-1])
    if not 0 <= low <= high <= maximum:
        raise ValueError
    return low, high


def _key(value: str) -> None:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError from None
    if len(raw) != 32 or not any(raw):
        raise ValueError


def _endpoint(value: str) -> str:
    match = re.fullmatch(r"(?:\[([0-9a-fA-F:]+)\]|([A-Za-z0-9.-]+)):([0-9]{1,5})", value)
    if not match or not 1 <= int(match[3]) <= 65535:
        raise ValueError
    host = match[1] or match[2]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if match[1] or len(host) > 253 or re.fullmatch(r"[0-9.]+", host):
            raise ValueError from None
        labels = host.removesuffix(".").split(".")
        if any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels):
            raise ValueError from None
    else:
        if address.is_unspecified or address.is_multicast:
            raise ValueError
    return value


def _cps(value: str) -> None:
    # Parse the documented tag language; never evaluate expressions or invoke a
    # command. The import contract limits each CPS packet to 1280 bytes.
    tags = list(_TAG.finditer(value))
    if not tags or "".join(t.group(0) for t in tags) != value or sum(t[1] == "t" for t in tags) > 1:
        raise ValueError
    size = 0
    for tag in tags:
        kind, _, argument = tag[1].partition(" ")
        if kind == "b":
            if (len(argument) - 2) % 2:
                raise ValueError
            size += (len(argument) - 2) // 2
        elif kind == "t":
            size += 4
        else:
            count = int(argument)
            if not 1 <= count <= 1000:
                raise ValueError
            size += count
    if size > 1280:
        raise ValueError


def preflight_profile(request: VPNProfilePreflightRequest) -> VPNProfilePreflightResponse:
    issues: list[VPNProfileIssue] = []

    def issue(code: str, line: int | None = None) -> None:
        if len(issues) < 64:
            issues.append(VPNProfileIssue(code=code, line=line))

    interface: dict[str, tuple[str, int]] = {}
    peer: dict[str, tuple[str, int]] = {}
    section: str | None = None
    sections: set[str] = set()
    allowed = set(_BASE_INTERFACE)
    if request.protocol == "amneziawg":
        allowed |= _AWG1
        if request.protocol_version != "1":
            allowed |= _CPS
        if request.protocol_version in {"2", "3.1"}:
            allowed |= _AWG2
        if request.protocol_version == "3.1":
            allowed |= _AWG31
    elif request.protocol_version != "1":
        issue("protocol_version_mismatch")

    text = request.config_text.get_secret_value()
    if len(text.encode("utf-8")) > 65536:
        issue("config_too_large")
        text = ""  # No partial/truncated configuration can be accepted.
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if len(raw) > 8192 or any(ord(c) < 32 and c != "\t" for c in raw):
            issue("invalid_line", number)
            continue
        if line.startswith("["):
            name = line.lower()
            section = name if name in {"[interface]", "[peer]"} else None
            if section is None:
                issue("unknown_section", number)
            elif section in sections:
                issue("duplicate_section", number)
                section = None
            else:
                sections.add(section)
            continue
        name, sep, value = line.partition("=")
        name, value = name.strip().lower(), value.strip()
        if not sep or not value or section is None:
            issue("invalid_entry", number)
            continue
        if name in _HOOKS:
            issue("executable_or_routing_directive_forbidden", number)
            continue
        target = interface if section == "[interface]" else peer
        if name not in (allowed if section == "[interface]" else _PEER):
            issue("unsupported_field_for_protocol_version", number)
        elif name in target:
            issue("duplicate_field", number)
        else:
            target[name] = (value, number)

    for name in sorted({"privatekey", "address"} - interface.keys()):
        issue("missing_interface_" + name)
    for name in sorted({"publickey", "allowedips", "endpoint"} - peer.keys()):
        issue("missing_peer_" + name)
    if request.protocol == "amneziawg" and _AWG1 - interface.keys():
        issue("missing_awg_parameters")

    addresses = []
    routes = []
    dns_servers = []
    headers: list[tuple[int, int]] = []
    endpoint = None
    for name, (value, number) in [*interface.items(), *peer.items()]:
        try:
            if name in {"privatekey", "publickey", "presharedkey", "headerprotectionkey"}:
                _key(value)
            elif name == "address":
                addresses = [ipaddress.ip_interface(v.strip()) for v in value.split(",")]
            elif name == "allowedips":
                routes = [ipaddress.ip_network(v.strip(), strict=False) for v in value.split(",")]
            elif name == "dns":
                dns_servers = [ipaddress.ip_address(item.strip()) for item in value.split(",")]
            elif name == "endpoint":
                endpoint = _endpoint(value)
            elif name in _CPS:
                _cps(value)
            elif name in {"randomtrailers", "disablecookies"}:
                if value.lower() not in {"on", "off"}:
                    raise ValueError
            elif name.startswith("h") and name in _AWG1:
                headers.append(_range(value, 2**32 - 1, request.protocol_version in {"2", "3.1"}))
            elif name in {"mtu", "listenport", "persistentkeepalive"} | _AWG1 | _AWG2 | _AWG31:
                low, high = _range(value, 65535, name in _AWG31)
                if name == "mtu" and not 1280 <= low <= 9000:
                    raise ValueError
                if name == "jc" and high > 128:
                    raise ValueError
                if name in {"jmin", "jmax"} and high > 1280:
                    raise ValueError
                if name in {"s1", "s2", "s3", "s4"} and high > 2048:
                    raise ValueError
        except ValueError:
            issue("invalid_field_value", number)

    if "jmin" in interface and "jmax" in interface:
        try:
            if _range(interface["jmin"][0], 65535)[0] > _range(interface["jmax"][0], 65535)[0]:
                issue("junk_size_range_inverted")
        except ValueError:
            pass  # Individual invalid values already reported.
    if any(a[0] <= b[1] and b[0] <= a[1] for i, a in enumerate(headers) for b in headers[i + 1:]):
        issue("awg_header_ranges_overlap")
    if "headerprotectionkey" in interface:
        try:
            if any(_range(interface.get(s, ("0", 0))[0], 65535)[0] < 12 for s in ("s1", "s2", "s3", "s4")):
                issue("header_protection_requires_four_prefixes")
        except ValueError:
            pass
    if not any(r.version == 4 and r.prefixlen == 0 for r in routes):
        issue("selected_app_egress_requires_ipv4_default_route")
    if not any(a.version == 4 for a in addresses):
        issue("ipv4_tunnel_address_required")
    has_ipv6 = any(a.version == 6 for a in addresses) and any(r.version == 6 and r.prefixlen == 0 for r in routes)
    if request.traffic_policy.ipv6 == "tunnel" and not has_ipv6:
        issue("ipv6_tunnel_address_and_default_route_required")
    if request.traffic_policy.ipv6 == "block" and (any(a.version == 6 for a in addresses) or any(r.version == 6 for r in routes)
                                                  or any(d.version == 6 for d in dns_servers)):
        issue("ipv6_config_conflicts_with_block_policy")

    provider = next(p for p in provider_capabilities() if p.provider_id == request.provider_id)
    return VPNProfilePreflightResponse(
        config_valid=not issues, provider=provider, protocol=request.protocol,
        protocol_version=request.protocol_version, traffic_policy=request.traffic_policy,
        endpoint=endpoint if not issues else None,
        features=sorted((interface.keys() & (_AWG1 | _CPS | _AWG2 | _AWG31))),
        issues=issues,
        blockers=[provider.reason, "native_config_validation_required", "device_uid_and_lockdown_preflight_required", "live_control_plane_acceptance_required"],
    )
