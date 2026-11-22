"""Validate rendered review Compose configuration, without creating resources."""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from typing import Any


def validate(config: dict[str, Any]) -> dict[str, Any]:
    services = config["services"]
    ui, gateway = services["review-ui"], services["review-gateway"]
    network = config["networks"]["review"]
    ipam = network["ipam"]["config"]
    if len(ipam) != 1:
        raise ValueError("Review requires one IPv4 IPAM allocation")
    subnet = ipaddress.ip_network(ipam[0]["subnet"])
    pool = ipaddress.ip_network(ipam[0]["ip_range"])
    address = ipaddress.ip_address(ui["networks"]["review"]["ipv4_address"])
    router = ipaddress.ip_address(ipam[0]["gateway"])
    if not isinstance(subnet, ipaddress.IPv4Network) or not subnet.is_private:
        raise ValueError("Review subnet must be private IPv4")
    if not pool.subnet_of(subnet) or address not in subnet or address in pool:
        raise ValueError("Static UI must be in subnet and outside dynamic allocation")
    if address in {subnet.network_address, subnet.broadcast_address, router}:
        raise ValueError("UI cannot use network, broadcast or gateway address")
    if router not in subnet or router in {subnet.network_address, subnet.broadcast_address}:
        raise ValueError("Invalid review gateway address")
    if gateway["environment"]["SPHERE_REVIEW_UI_IP"] != str(address):
        raise ValueError("Gateway destination must match static UI address")
    if network.get("internal") is not True:
        raise ValueError("Review network must be internal")
    if set(gateway["networks"]) != {"review", "existing-api"}:
        raise ValueError("Gateway network boundary changed")
    if any(port.get("host_ip") != "127.0.0.1" for port in gateway["ports"]):
        raise ValueError("Gateway must bind loopback only")
    for service in (ui, gateway):
        if service.get("read_only") is not True or service.get("cap_drop") != ["ALL"]:
            raise ValueError("Review service confinement changed")
    entrypoint = gateway["entrypoint"]
    if entrypoint[:2] != ["/bin/sh", "-ec"] or len(entrypoint) != 3:
        raise ValueError("Unexpected template renderer")
    # compose config preserves escaped dollars; container config unescapes them.
    renderer = entrypoint[2].replace("$$", "$")
    if "envsubst '$SPHERE_REVIEW_UI_IP'" not in renderer or "nginx -c /tmp/nginx.conf" not in renderer:
        raise ValueError("Renderer must substitute only the UI address in bounded tmpfs")
    if "tools" in ui["networks"]:
        tools = ipaddress.ip_address(ui["networks"]["tools"]["ipv4_address"])
        if not isinstance(tools, ipaddress.IPv4Address) or not tools.is_private or tools == address:
            raise ValueError("Tools proxy needs a separate private interface")
    return {"state": "CONFIGURATION_VALID", "network": network["name"],
            "subnet": str(subnet), "dynamicPool": str(pool), "staticUiIp": str(address),
            "liveHealthVerified": False, "systemChangesPerformed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose_config", type=Path, help="Private JSON from docker compose config --format json")
    args = parser.parse_args()
    if args.compose_config.stat().st_size > 1_048_576:
        raise SystemExit("Configuration exceeds the 1 MiB input limit")
    try:
        result = validate(json.loads(args.compose_config.read_text(encoding="utf-8-sig")))
    except (KeyError, TypeError, ValueError) as error:
        # Never dump a rendered Compose configuration; it can contain credentials.
        raise SystemExit("Review configuration rejected: " + type(error).__name__) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
