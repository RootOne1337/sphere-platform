from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from backend.websocket import direct_probe_mdns as mdns

NAME = "d5e993f8-5b0f-4e1d-b9b8-67e6cd5db8ac.local"
SESSION = "ab" * 16
CANDIDATE = f"a=candidate:1 1 udp 2122260223 {NAME} 59111 typ host generation 0\r\n"
SDP = ("v=0\r\na=ice-ufrag:unchanged\r\na=ice-pwd:unchanged\r\n"
       "a=fingerprint:sha-256 " + ":".join(["AB"] * 32) + "\r\n" + CANDIDATE)


@pytest.mark.parametrize("name", ["printer.local", "127.0.0.1", NAME.upper(), NAME + ".",
                                  NAME[:-6], "../" + NAME, None, 1, "x" * 500])
def test_discovery_accepts_only_canonical_ephemeral_ice_names(name):
    assert not mdns.valid_name(name)
    assert mdns.valid_name(NAME)


@pytest.mark.parametrize("url", ["https://public.example/v1/mdns", "http://localhost:8890/v1/mdns",
    "http://127.0.0.1:80/v1/mdns", "http://user@127.0.0.1:8890/v1/mdns", "http://127.0.0.1:8890/other",
    "http://127.0.0.1:8890/v1/mdns?destination=other", "http://127.0.0.1:8890/v1/mdns#x",
    "http://host.docker.internal.evil:8890/v1/mdns", "http://host.docker.internal:bad/v1/mdns"])
def test_peer_cannot_select_arbitrary_dns_or_network_targets(url):
    assert not mdns.valid_helper_url(url)
    assert mdns.valid_helper_url("http://127.0.0.1:8890/v1/mdns")
    assert mdns.valid_helper_url("http://host.docker.internal:8890/v1/mdns")


def test_rewrites_only_host_address_preserving_crypto_ports_and_sdp_bytes():
    address = "192.168.100.7"
    other = CANDIDATE.replace("udp", "tcp") + CANDIDATE.replace("typ host", "typ srflx")
    with_whitespace = CANDIDATE.replace(" udp ", "\tudp  ")
    source = SDP + other + with_whitespace
    result = mdns.apply_mapping(source, {NAME: address})
    assert result == SDP.replace(NAME, address) + other + with_whitespace.replace(NAME, address)
    assert result.count("a=fingerprint:") == 1
    assert result.count("59111") == source.count("59111")
    assert mdns.candidate_names(source) == (NAME,)


@pytest.mark.parametrize("address", ["8.8.8.8", "127.0.0.1", "0.0.0.0", "169.254.1.2",
                                     "100.64.1.1", "::1", "fd00::1", True, None])
def test_discovery_reply_cannot_inject_other_networks(address):
    with pytest.raises((ValueError, TypeError)):
        mdns.reply_mapping({"version": 1, "session": SESSION, "resolved": [{"name": NAME, "address": address}]},
                           SESSION, (NAME,))


@pytest.mark.parametrize("change", [
    {"session": "cd" * 16}, {"version": True}, {"extra": "secret"}, {"resolved": "other"},
    {"resolved": [{"name": "foreign.local", "address": "10.0.1.2"}]},
    {"resolved": [{"name": NAME, "address": "10.0.1.2", "sdp": "injected"}]},
    {"resolved": [{"name": NAME, "address": "10.0.1.2"}] * 2},
])
def test_replies_must_match_reserved_session_and_original_names(change):
    with pytest.raises(ValueError):
        mdns.reply_mapping({"version": 1, "session": SESSION, "resolved": [], **change}, SESSION, (NAME,))


@pytest.fixture
def helper(monkeypatch):
    monkeypatch.setattr(mdns.settings, "DIRECT_PROBE_MDNS_RESOLVER_URL", "http://127.0.0.1:8890/v1/mdns")
    monkeypatch.setattr(mdns.settings, "DIRECT_PROBE_MDNS_RESOLVER_KEY", SecretStr("k" * 43))
    native = httpx.AsyncClient
    def use(handler):
        def client(**kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            return native(**kwargs, transport=httpx.MockTransport(handler))
        monkeypatch.setattr(mdns.httpx, "AsyncClient", client)
    return use


@pytest.mark.asyncio
async def test_authenticated_discovery_uses_no_sdp_or_credentials(helper):
    def response(request):
        assert request.headers["authorization"] == "Bearer " + "k" * 43
        assert json.loads(request.content) == {"version": 1, "session": SESSION, "names": [NAME]}
        assert b"ice-pwd" not in request.content and b"fingerprint" not in request.content
        return httpx.Response(200, json={"version": 1, "session": SESSION,
                                        "resolved": [{"name": NAME, "address": "10.66.1.4"}]})
    helper(response)
    assert await mdns.resolve_offer(SDP, SESSION) == SDP.replace(NAME, "10.66.1.4")


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(403), httpx.Response(302, headers={"location": "https://foreign.example"}),
    httpx.Response(200, content=b"x" * 2049), httpx.Response(200, content=b"not-json"),
    httpx.Response(200, json={"version": 1, "session": "cd" * 16, "resolved": []})])
async def test_faulty_helper_preserves_the_original_offer(helper, reply):
    helper(lambda _: reply)
    assert await mdns.resolve_offer(SDP, SESSION) == SDP


@pytest.mark.asyncio
async def test_total_helper_deadline_falls_back_before_ice_lease_expires(helper, monkeypatch):
    monkeypatch.setattr(mdns, "HELPER_SECONDS", .025)
    async def stalled(_):
        await asyncio.sleep(30)
    helper(stalled)
    async with asyncio.timeout(.2):
        assert await mdns.resolve_offer(SDP, SESSION) == SDP


@pytest.mark.asyncio
async def test_cancelled_viewer_cannot_be_revived_by_name_resolution(helper):
    async def cancelled(_):
        raise asyncio.CancelledError()
    helper(cancelled)
    with pytest.raises(asyncio.CancelledError):
        await mdns.resolve_offer(SDP, SESSION)


@pytest.mark.asyncio
async def test_disabled_helper_and_numeric_offers_make_no_network_requests(helper, monkeypatch):
    def forbidden(_):
        raise AssertionError("Unnecessary network operation")
    helper(forbidden)
    assert await mdns.resolve_offer(SDP.replace(NAME, "192.168.1.9"), SESSION) == SDP.replace(NAME, "192.168.1.9")
    monkeypatch.setattr(mdns.settings, "DIRECT_PROBE_MDNS_RESOLVER_URL", "")
    assert await mdns.resolve_offer(SDP, SESSION) == SDP
