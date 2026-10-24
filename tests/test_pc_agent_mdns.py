from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from unittest.mock import Mock

import dns.message
import dns.rrset
import httpx
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "pc-agent/agent/mdns_resolver.py"
spec = importlib.util.spec_from_file_location("sphere_local_mdns_test", SOURCE)
mdns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mdns)
NAME = "d5e993f8-5b0f-4e1d-b9b8-67e6cd5db8ac.local"
SESSION = "ab" * 16
KEY = "k" * 43


def packet(name=NAME, address="192.168.100.7", ttl=120, cache_flush=True):
    reply = dns.message.make_response(dns.message.make_query(name, "A"))
    reply.answer.append(dns.rrset.from_text(name + ".", ttl, "IN", "A", address))
    wire = bytearray(reply.to_wire())
    if cache_flush:
        offset = len(dns.message.make_query(name, "A").to_wire()) + 4
        wire[offset] |= 0x80
    return bytes(wire)


def test_real_mdns_cache_flush_records_parse_without_other_lan_names():
    for cache_flush in (True, False):
        assert mdns.answer_addresses(packet(cache_flush=cache_flush), (NAME,)) == {NAME: {"192.168.100.7"}}
    assert mdns.answer_addresses(packet(name="printer.local"), (NAME,)) == {}
    assert mdns.answer_addresses(packet(address="8.8.8.8"), (NAME,)) == {}
    assert mdns.answer_addresses(packet(ttl=0), (NAME,)) == {}


@pytest.mark.parametrize("data", [b"", b"x" * 8193, b"\x00" * 20, packet()[:-1], packet() + b"junk"])
def test_malformed_or_oversized_lan_packets_are_ignored(data):
    assert mdns.answer_addresses(data, (NAME,)) == {}


@pytest.mark.parametrize("change", [{"version": True}, {"session": "not-session"}, {"names": []},
    {"names": ["printer.local"]}, {"names": [NAME] * 2}, {"target": "other"}, {"names": [None]}])
def test_host_helper_has_no_arbitrary_dns_scan_or_cross_session_api(change):
    with pytest.raises(ValueError):
        mdns.request_names({"version": 1, "session": SESSION, "names": [NAME], **change})


@pytest.fixture
def server(monkeypatch):
    query = Mock(return_value={NAME: "192.168.100.7"})
    monkeypatch.setattr(mdns, "resolve_names", query)
    with mdns.LocalResolverServer(0, KEY) as instance:
        thread = threading.Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{instance.server_port}", query, instance
        finally:
            instance.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_http_requires_key_before_dns_and_never_relays_media(server):
    url, query, _ = server
    with httpx.Client(base_url=url, trust_env=False) as client:
        body = {"version": 1, "session": SESSION, "names": [NAME]}
        assert client.post("/v1/mdns", json=body).status_code == 403
        assert client.post("/media", json=body, headers={"Authorization": "Bearer " + KEY}).status_code == 403
        query.assert_not_called()
        headers = {"Authorization": "Bearer " + KEY}
        assert client.get("/health", headers=headers).json()["media_relay"] is False
        response = client.post("/v1/mdns", json=body, headers=headers)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json() == {"version": 1, "session": SESSION,
                                   "resolved": [{"name": NAME, "address": "192.168.100.7"}]}
        query.assert_called_once_with((NAME,))


def test_invalid_requests_do_not_emit_multicast(server):
    url, query, _ = server
    with httpx.Client(base_url=url, trust_env=False, headers={"Authorization": "Bearer " + KEY}) as client:
        assert client.post("/v1/mdns", json={"names": [NAME]}).status_code == 400
        assert client.post("/v1/mdns", content=b"x" * 1025, headers={"Content-Type": "application/json"}).status_code == 400
    query.assert_not_called()


def test_rate_limit_is_bounded_and_releases_old_slots(server, monkeypatch):
    _, _, instance = server
    monkeypatch.setattr(mdns.time, "monotonic", lambda: 100.0)
    assert all(instance.admit() for _ in range(60))
    assert not instance.admit()
    monkeypatch.setattr(mdns.time, "monotonic", lambda: 161.0)
    assert instance.admit() and len(instance.request_times) == 1
