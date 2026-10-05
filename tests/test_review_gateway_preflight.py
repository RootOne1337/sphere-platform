from __future__ import annotations

import copy

import pytest

from scripts.pilot.review_gateway_preflight import validate


def configuration():
    return {"services": {
        "review-ui": {"read_only": True, "cap_drop": ["ALL"], "networks": {
            "review": {"ipv4_address": "172.30.0.3"}, "tools": {"ipv4_address": "172.29.0.3"}}},
        "review-gateway": {"read_only": True, "cap_drop": ["ALL"],
                           "environment": {"SPHERE_REVIEW_UI_IP": "172.30.0.3"},
                           "networks": {"review": {}, "existing-api": {}},
                           "ports": [{"host_ip": "127.0.0.1", "published": "3015"}],
                           "entrypoint": ["/bin/sh", "-ec", "envsubst '$SPHERE_REVIEW_UI_IP' < template > /tmp/nginx.conf; exec nginx -c /tmp/nginx.conf -g 'daemon off;'"]}},
            "networks": {"review": {"name": "test-review", "internal": True, "ipam": {"config": [
                {"subnet": "172.30.0.0/24", "ip_range": "172.30.0.128/25", "gateway": "172.30.0.1"}]}}}}


def test_private_reserved_route_without_changing_system():
    config = configuration()
    original = copy.deepcopy(config)
    assert validate(config)["staticUiIp"] == "172.30.0.3"
    assert validate(config)["liveHealthVerified"] is False
    assert config == original


def test_accepts_compose_dollar_escaping_without_expanding_other_variables():
    config = configuration()
    config["services"]["review-gateway"]["entrypoint"][2] = "envsubst '$$SPHERE_REVIEW_UI_IP' < template > /tmp/nginx.conf; exec nginx -c /tmp/nginx.conf"
    assert validate(config)["systemChangesPerformed"] is False


@pytest.mark.parametrize("address", ["172.30.0.129", "172.31.0.3", "172.30.0.1", "172.30.0.0", "172.30.0.255"])
def test_rejects_dynamic_outside_or_reserved_address(address):
    config = configuration()
    config["services"]["review-ui"]["networks"]["review"]["ipv4_address"] = address
    config["services"]["review-gateway"]["environment"]["SPHERE_REVIEW_UI_IP"] = address
    with pytest.raises(ValueError):
        validate(config)


@pytest.mark.parametrize("case", ["wrong_target", "public_binding", "external_review", "capabilities", "extra_network", "broad_envsubst", "same_tools_interface"])
def test_rejects_boundary_regression(case):
    config = configuration()
    ui = config["services"]["review-ui"]
    gateway = config["services"]["review-gateway"]
    if case == "wrong_target":
        gateway["environment"]["SPHERE_REVIEW_UI_IP"] = "192.168.0.1"
    elif case == "public_binding":
        gateway["ports"][0]["host_ip"] = "0.0.0.0"
    elif case == "external_review":
        config["networks"]["review"]["internal"] = False
    elif case == "capabilities":
        gateway["cap_drop"] = []
    elif case == "extra_network":
        gateway["networks"]["tools"] = {}
    elif case == "broad_envsubst":
        gateway["entrypoint"][2] = "envsubst < template > /tmp/nginx.conf; nginx -c /tmp/nginx.conf"
    else:
        ui["networks"]["tools"]["ipv4_address"] = "172.30.0.3"
    with pytest.raises(ValueError):
        validate(config)
