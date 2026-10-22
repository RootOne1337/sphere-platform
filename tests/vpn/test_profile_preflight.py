from __future__ import annotations

import base64
import json
import socket
import subprocess

import pytest
from pydantic import ValidationError

from backend.schemas.vpn.profile import VPNProfilePreflightRequest
from backend.services.vpn.profile_preflight import preflight_profile

KEY = base64.b64encode(bytes(range(1, 33))).decode()
CONFIG = f"""[Interface]
PrivateKey = {KEY}
Address = 10.100.0.2/32
DNS = 1.1.1.1
MTU = 1280
[Peer]
PublicKey = {KEY}
AllowedIPs = 0.0.0.0/0
Endpoint = vpn.example:51820
PersistentKeepalive = 25
"""
AWG = "\nJc = 4\nJmin = 40\nJmax = 70\nS1 = 20\nS2 = 30\nH1 = 1\nH2 = 2\nH3 = 3\nH4 = 4\n"


def payload(config=CONFIG, **extra):
    return {
        "protocol": "wireguard", "protocol_version": "1", "config_text": config,
        "traffic_policy": {"included_packages": ["org.example.game"]}, **extra,
    }


def inspect(config=CONFIG, **extra):
    return preflight_profile(VPNProfilePreflightRequest.model_validate(payload(config, **extra)))


def awg(fields=AWG, **extra):
    return inspect(CONFIG.replace("[Peer]", fields + "[Peer]"), protocol="amneziawg", **extra)


def codes(result):
    return {item.code for item in result.issues}


def test_valid_config_is_never_an_activation_or_secret_receipt(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Preflight attempted external I/O")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = inspect()
    assert result.config_valid
    assert not result.apply_allowed and not result.persisted and not result.execution_confirmed
    assert not result.provider.execution_available
    assert result.provider.supported_protocol_versions == []
    assert KEY not in result.model_dump_json()
    assert "PrivateKey" not in repr(VPNProfilePreflightRequest.model_validate(payload()))
    assert result.endpoint == "vpn.example:51820"


def test_ipv6_dns_cannot_implicitly_allow_a_blocked_address_family():
    result = inspect(CONFIG.replace("DNS = 1.1.1.1", "DNS = 2606:4700:4700::1111"))
    assert not result.config_valid and "ipv6_config_conflicts_with_block_policy" in codes(result)


def test_ipv6_dns_is_allowed_with_explicit_ipv6_tunnel_address_and_default_route():
    config = CONFIG.replace("DNS = 1.1.1.1", "DNS = 2606:4700:4700::1111").replace("Address = 10.100.0.2/32", "Address = 10.100.0.2/32, fd00::2/128").replace("AllowedIPs = 0.0.0.0/0", "AllowedIPs = 0.0.0.0/0, ::/0")
    result = inspect(config, traffic_policy={"included_packages": ["org.example.game"], "ipv6": "tunnel"})
    assert result.config_valid


@pytest.mark.parametrize("version", ["1", "1.5", "2", "3.1"])
def test_awg_versions_are_explicitly_recognized_without_claiming_runtime_support(version):
    result = awg(protocol_version=version)
    assert result.config_valid and not result.apply_allowed


def test_awg31_header_protection_ranges_and_cps():
    fields = AWG + f"S3 = 12\nS4 = 12\nHeaderProtectionKey = {KEY}\nContentPaddingAddition = 0-32\nI1 = <b 0xaabb><rc 8><t><r 20>\nRandomTrailers = on\nDisableCookies = off\n"
    result = awg(fields, protocol_version="3.1")
    assert result.config_valid
    assert "headerprotectionkey" in result.features
    assert KEY not in result.model_dump_json()


@pytest.mark.parametrize("directive", ["PostUp", "PreUp", "PostDown", "PreDown", "SaveConfig", "Table", "FwMark"])
def test_shell_hooks_and_route_overrides_are_rejected(directive):
    result = inspect(CONFIG.replace("[Peer]", f"{directive} = secret-sentinel-command\n[Peer]"))
    assert not result.config_valid
    assert "executable_or_routing_directive_forbidden" in codes(result)
    assert "secret-sentinel" not in result.model_dump_json()


@pytest.mark.parametrize("bad", [
    CONFIG.replace(KEY, "secret-invalid-key"),
    CONFIG.replace("vpn.example:51820", "vpn.example:0"),
    CONFIG.replace("vpn.example:51820", "vpn.example:65536"),
    CONFIG.replace("vpn.example:51820", "vpn.example;id:51820"),
    CONFIG.replace("vpn.example:51820", "999.2.3.4:51820"),
    CONFIG.replace("vpn.example:51820", "http://vpn.example:51820"),
    CONFIG.replace("10.100.0.2/32", "not-an-address"),
    CONFIG.replace("0.0.0.0/0", "not-a-route"),
    CONFIG.replace("MTU = 1280", "MTU = 12"),
    CONFIG.replace("[Peer]", "PrivateKey = duplicate-secret\n[Peer]"),
    CONFIG + "[Peer]\nPublicKey = second-peer-secret\n",
    CONFIG + "[Unrecognized]\nKey = value\n",
    CONFIG + "UnknownSecretDirective = secret-sentinel\n",
    CONFIG + "broken-line\n",
])
def test_malformed_or_unsupported_configs_never_echo_values(bad):
    result = inspect(bad)
    assert not result.config_valid and not result.apply_allowed
    assert result.endpoint is None
    assert not any(secret in result.model_dump_json() for secret in (KEY, "secret-sentinel", "duplicate-secret"))


@pytest.mark.parametrize("version,fields,code", [
    ("1", AWG + "I1 = <r 20>\n", "unsupported_field_for_protocol_version"),
    ("1.5", AWG + "S3 = 12\n", "unsupported_field_for_protocol_version"),
    ("2", AWG + "HeaderProtectionKey = abc\n", "unsupported_field_for_protocol_version"),
    ("1", AWG.replace("H1 = 1", "H1 = 1-5"), "invalid_field_value"),
    ("2", AWG.replace("H1 = 1", "H1 = 1-5"), "awg_header_ranges_overlap"),
    ("3.1", AWG + f"HeaderProtectionKey = {KEY}\n", "header_protection_requires_four_prefixes"),
    ("3.1", AWG + "I1 = <b 0xabc>\n", "invalid_field_value"),
    ("3.1", AWG + "I1 = <t><t>\n", "invalid_field_value"),
    ("3.1", AWG + "I1 = <r 1001>\n", "invalid_field_value"),
    ("3.1", AWG + "I1 = <r 1000><r 1000>\n", "invalid_field_value"),
    ("3.1", AWG + "I1 = $(id)\n", "invalid_field_value"),
    ("1", AWG.replace("Jmax = 70", "Jmax = 20"), "junk_size_range_inverted"),
])
def test_protocol_features_and_cross_field_constraints(version, fields, code):
    result = awg(fields, protocol_version=version)
    assert code in codes(result)


@pytest.mark.parametrize("policy", [
    {"included_packages": []},
    {"included_packages": ["com.sphereplatform.agent"]},
    {"included_packages": ["com.sphereplatform.agent.debug"]},
    {"included_packages": ["org.example.game", "org.example.game"]},
    {"included_packages": ["org.example.game;id"]},
    {"included_packages": ["org.example.game"], "control_plane": "tunnel"},
    {"included_packages": ["org.example.game"], "mode": "all_apps"},
    {"included_packages": ["org.example.game"], "kill_switch": "global"},
])
def test_unsafe_routing_policy_rejected(policy):
    with pytest.raises(ValidationError):
        VPNProfilePreflightRequest.model_validate(payload(traffic_policy=policy))


def test_ipv6_requires_a_consistent_explicit_policy():
    dual = CONFIG.replace("Address = 10.100.0.2/32", "Address = 10.100.0.2/32, fd00::2/128").replace(
        "AllowedIPs = 0.0.0.0/0", "AllowedIPs = 0.0.0.0/0, ::/0")
    assert "ipv6_config_conflicts_with_block_policy" in codes(inspect(dual))
    policy = {"included_packages": ["org.example.game"], "ipv6": "tunnel"}
    assert inspect(dual, traffic_policy=policy).config_valid
    assert "ipv6_tunnel_address_and_default_route_required" in codes(inspect(traffic_policy=policy))


def test_no_silent_truncation_and_bounded_error_output():
    result = inspect(CONFIG + ("X = " + "é" * 33000))
    assert "config_too_large" in codes(result)
    result = inspect(CONFIG + "X = invalid\n" * 3000)
    assert len(result.issues) == 64


@pytest.mark.asyncio
async def test_api_preflight_is_read_only_and_secret_free(vpn_admin_client):
    response = await vpn_admin_client.post("/api/v1/vpn/profile-preflight", json=payload())
    assert response.status_code == 200, response.text
    assert response.json()["config_valid"]
    assert response.json()["apply_allowed"] is False
    assert KEY not in response.text
    providers = await vpn_admin_client.get("/api/v1/vpn/providers")
    assert providers.status_code == 200
    assert all(not p["execution_available"] for p in providers.json())


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"config_text": "secret-sentinel", "traffic_policy": "bad-policy"},
    {**payload(), "config_text": ["secret-sentinel"]},
    {**payload(), "extra-secret": "secret-sentinel"},
    {**payload(), "traffic_policy": {"included_packages": ["com.sphereplatform.agent"]}},
])
async def test_api_validation_does_not_echo_imported_secrets(vpn_admin_client, body):
    response = await vpn_admin_client.post("/api/v1/vpn/profile-preflight", json=body)
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_vpn_profile_request"}
    assert KEY not in response.text and "secret-sentinel" not in response.text


@pytest.mark.asyncio
async def test_api_rejects_bad_json_and_oversize_body(vpn_admin_client):
    for content, status in [(b'{"secret-sentinel":', 422), (b"x" * 98305, 413)]:
        response = await vpn_admin_client.post("/api/v1/vpn/profile-preflight", content=content)
        assert response.status_code == status
        assert "secret-sentinel" not in response.text


@pytest.mark.asyncio
async def test_preflight_requires_vpn_write(vpn_manager_client):
    response = await vpn_manager_client.post("/api/v1/vpn/profile-preflight", json=payload())
    assert response.status_code == 403


def test_openapi_request_schema_has_no_unresolved_local_refs():
    from backend.main import app

    schema = app.openapi()["paths"]["/api/v1/vpn/profile-preflight"]["post"]["requestBody"]
    assert "#/$defs/" not in json.dumps(schema)
    assert schema["content"]["application/json"]["schema"]["properties"]["config_text"]["writeOnly"]


def test_all_apps_policy_is_a_separate_closed_v2_contract_without_package_inventory():
    policy = {"mode": "all_apps_except_control", "kill_switch": "all_apps_except_control", "ipv6": "block"}
    request = VPNProfilePreflightRequest.model_validate(payload(schema_version=2, traffic_policy=policy))
    result = preflight_profile(request)
    assert result.config_valid and result.schema_version == 2
    assert "included_packages" not in result.traffic_policy.model_dump()
    assert result.traffic_policy.control_plane == "bypass"
    assert not result.apply_allowed and not result.provider.execution_available
    assert KEY not in result.model_dump_json()
    for change in ({"schema_version": 1}, {"provider_id": "legacy-root"},
                   {"traffic_policy": policy | {"included_packages": []}},
                   {"traffic_policy": policy | {"excluded_packages": ["org.example.game"]}},
                   {"traffic_policy": policy | {"excluded_uids": [0]}},
                   {"traffic_policy": policy | {"kill_switch": "selected_apps"}},
                   {"traffic_policy": policy | {"control_plane": "tunnel"}}):
        with pytest.raises(ValidationError):
            VPNProfilePreflightRequest.model_validate(payload(schema_version=2, traffic_policy=policy) | change)
    with pytest.raises(ValidationError):
        VPNProfilePreflightRequest.model_validate(payload(schema_version=2))


def test_openapi_v2_retains_both_closed_scope_variants_after_inlining():
    from backend.api.v1.vpn.profile_input import profile_request_schema
    schema = profile_request_schema(VPNProfilePreflightRequest)
    branches = schema["content"]["application/json"]["schema"]["properties"]["traffic_policy"]["oneOf"]
    assert {b["properties"]["mode"]["const"] for b in branches} == {"selected_apps", "all_apps_except_control"}
    assert all(b["additionalProperties"] is False for b in branches)
    assert "#/$defs/" not in json.dumps(schema)
