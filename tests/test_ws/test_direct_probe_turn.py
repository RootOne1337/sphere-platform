from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from backend.websocket.direct_probe_ice import issue_turn_grant, turn_url, validate_turn_grant
from backend.websocket.direct_probe_protocol import InvalidDirectProbe
from backend.websocket.direct_probe_runtime import ProbeViewer
from tests.test_ws.test_direct_probe import (  # noqa: F401 (shared two-worker fixture)
    SDP,
    eventually,
    peers,
)

SID = "a" * 32
KEY = "fixture-only-" + "x" * 32
URLS = ("turn:192.168.1.5:3478?transport=udp", "turns:relay.example.test:443?transport=tcp")


@pytest.mark.parametrize("url", URLS + ("turn:relay.example.test:3478?transport=tcp",))
def test_canonical_operator_urls(url):
    assert turn_url(url) == url


@pytest.mark.parametrize("url", [None, 42, "turn:relay:3478?transport=udp", "turn:0172.16.1.2:3478?transport=udp",
    "turn:127.0.0.1:3478?transport=udp", "turn:0.1.2.3:3478?transport=udp", "turn:169.254.1.1:3478?transport=udp",
    "turn:224.0.0.1:3478?transport=udp", "turn:240.0.0.1:3478?transport=udp", "turn:256.1.2.3:3478?transport=udp",
    "turn:relay.example.test:03478?transport=udp", "turn:relay.example.test:65536?transport=udp",
    "turn:relay.example.test:0?transport=udp", "turns:relay.example.test:443?transport=udp",
    "turn:user@relay.example.test:3478?transport=udp", "turn:relay.example.test:3478/path?transport=udp",
    "turn:relay.example.test:3478?transport=udp\n", "turn:RELAY.example.test:3478?transport=udp",
    "turn:relay.example.test:3478?transport=udp&credential=secret", "turn:relay.example.test:3478?transport=udp#x",
    "turn:[::1]:3478?transport=udp", "turn:" + "a" * 64 + ".test:3478?transport=udp"])
def test_rejects_ambiguous_or_non_endpoint_urls(url):
    with pytest.raises(InvalidDirectProbe, match="invalid_turn_url"):
        turn_url(url)


def test_coturn_hmac_uses_unique_opaque_side_binding_and_never_contains_master_key():
    browser = issue_turn_grant(URLS, KEY, SID, "browser", now=1_791_605_000.9)
    agent = issue_turn_grant(URLS, KEY, SID, "agent", now=1_791_605_000.9, relay_only=True)
    assert browser.username == f"1791605120:{SID}:browser"
    expected = base64.b64encode(hmac.new(KEY.encode(), browser.username.encode(), hashlib.sha1).digest()).decode()
    assert browser.credential == expected and browser.credential != agent.credential
    assert agent.policy == "relay" and browser.policy == "all"
    assert browser.wire()["ttl_ms"] == 120000
    assert KEY not in json.dumps(browser.wire()) and SID not in repr(browser)
    assert validate_turn_grant(agent.wire(), SID, "agent") == agent.wire()
    with pytest.raises(InvalidDirectProbe):
        validate_turn_grant(browser.wire(), SID, "agent")
    with pytest.raises(InvalidDirectProbe):
        validate_turn_grant(agent.wire(), "b" * 32, "agent")


@pytest.mark.parametrize("change", [{"ttl_ms": True}, {"ttl_ms": 120001}, {"policy": "any"},
    {"urls": []}, {"urls": [URLS[0]] * 2}, {"credential": "x" * 10000}, {"extra": "tap"}, {"username": 42},
    {"policy": []}, {"policy": {}}, {"policy": None}])
def test_tampered_grant_is_rejected(change):
    wire = issue_turn_grant(URLS, KEY, SID, "agent").wire() | change
    with pytest.raises(InvalidDirectProbe):
        validate_turn_grant(wire, SID, "agent")


@pytest.mark.parametrize("key", ["", "x" * 31, "x" * 257, "é" * 32, "x" * 32 + "\n"])
def test_missing_or_malformed_operator_key_fails_closed(key):
    with pytest.raises(InvalidDirectProbe):
        issue_turn_grant(URLS, key, SID, "browser")


@pytest.mark.asyncio
async def test_reserved_session_routes_agent_specific_credentials_across_workers(peers):
    runtimes, clients, _, agent, _, viewer = peers
    await runtimes[1].prepare(viewer)
    assert agent.send_json.call_count == 0
    assert await clients[0].pttl(runtimes[1].key("device")) <= 30000
    viewer.ice = issue_turn_grant(URLS, KEY, viewer.session, "agent").wire()
    grant = dict(viewer.ice)
    await runtimes[1].open(viewer, SDP)
    await eventually(lambda: agent.send_json.call_count == 1)
    sent = agent.send_json.call_args.args[0]
    assert sent["session_id"] == viewer.session and sent["ice"] == grant
    with pytest.raises(InvalidDirectProbe):
        await runtimes[1].open(viewer, SDP)
    await runtimes[1].retire(viewer)
    assert viewer.ice is None
    assert await clients[0].get(runtimes[1].key("device")) is None
    # Cooldown survives closing, unlike the peer lease.
    next_viewer = ProbeViewer("device", "org", "same_user", AsyncMock())
    with pytest.raises(InvalidDirectProbe, match="rate_limited"):
        await runtimes[1].prepare(next_viewer)
    assert await clients[0].get(runtimes[1].key("device")) is None


@pytest.mark.asyncio
async def test_v2_auth_is_completed_before_credentials_and_offer_is_bound_to_ready(peers, monkeypatch):
    from backend.api.ws.direct import router
    runtime = peers[0][1]
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_ENABLED", True)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({"device"}))
    monkeypatch.setattr(router.settings, "DIRECT_PROBE_TURN_URLS", URLS)
    monkeypatch.setattr(router.settings, "DIRECT_PROBE_TURN_SECRET", SecretStr(KEY))
    monkeypatch.setattr(router, "get_direct_probe_runtime", lambda: runtime)
    monkeypatch.setattr(router, "authorize", AsyncMock(return_value=("org", "user")))
    ws = AsyncMock()
    ws.receive_text.side_effect = [json.dumps(dict(token="fixture", protocol="sphere-probe-v2")),
        json.dumps(dict(type="direct_probe_offer", sdp=SDP)), '{"type":"direct_probe_close"}']
    await router.direct_probe_ws(ws, "device")
    ready = ws.send_json.call_args_list[0].args[0]
    assert ready["type"] == "direct_probe_ready" and ready["protocol"] == "sphere-probe-v2"
    assert ready["ice"]["username"].endswith(ready["session_id"] + ":browser")
    assert KEY not in json.dumps(ready)
    assert not runtime.viewers and await peers[1][1].get(runtime.key("device")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["auth", "configuration", "busy"])
async def test_denial_never_issues_credentials(peers, monkeypatch, failure):
    from fastapi import HTTPException

    from backend.api.ws.direct import router
    runtime = peers[0][1]
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_ENABLED", True)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({"device"}))
    monkeypatch.setattr(router.settings, "DIRECT_PROBE_TURN_URLS", () if failure == "configuration" else URLS)
    monkeypatch.setattr(router.settings, "DIRECT_PROBE_TURN_SECRET", SecretStr(KEY))
    monkeypatch.setattr(router, "get_direct_probe_runtime", lambda: runtime)
    monkeypatch.setattr(router, "authorize", AsyncMock(side_effect=HTTPException(403)) if failure == "auth" else AsyncMock(return_value=("org", "user")))
    if failure == "busy":
        await runtime.open(peers[-1], SDP)
    ws = AsyncMock()
    ws.receive_text.return_value = json.dumps(dict(token="fixture", protocol="sphere-probe-v2"))
    await router.direct_probe_ws(ws, "device")
    ws.send_json.assert_not_awaited()
    ws.close.assert_awaited_once_with(code=4003, reason="direct_probe_rejected_or_expired")
    assert len(runtime.viewers) == (1 if failure == "busy" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("retirement", ["socket", "worker"])
async def test_retirement_during_redis_reservation_never_leaks_grant_or_lease(peers, monkeypatch, retirement):
    runtime, client, viewer = peers[0][1], peers[1][1], peers[-1]
    entered, proceed = asyncio.Event(), asyncio.Event()
    original_set = client.set

    async def delayed_set(key, *args, **kwargs):
        if key == runtime.key(viewer.device):
            entered.set()
            await proceed.wait()
        return await original_set(key, *args, **kwargs)

    monkeypatch.setattr(client, "set", delayed_set)
    operation = asyncio.create_task(runtime.prepare(viewer))
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(InvalidDirectProbe, match="probe_unavailable"):
        await runtime.prepare(viewer)
    if retirement == "worker":
        runtime.available = False
    else:
        await runtime.retire(viewer)
    proceed.set()
    with pytest.raises(InvalidDirectProbe, match="probe_unavailable"):
        await operation
    assert viewer.retired and not viewer.binding and not viewer.ice
    assert not runtime.viewers and runtime.reservations == 0
    assert await client.get(runtime.key(viewer.device)) is None
    assert await client.get(f"{runtime.namespace}:relay-issued:{viewer.device}") is None
    viewer.ws.send_json.assert_not_awaited()
