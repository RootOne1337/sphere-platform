from __future__ import annotations

import pytest

from backend.websocket.direct_probe_candidates import candidate
from backend.websocket.direct_probe_protocol import InvalidDirectProbe


def wire(address="192.168.1.20"):
    return dict(candidate=f"candidate:1 1 udp 2122260223 {address} 53000 typ host generation 0",
                sdpMid="0", sdpMLineIndex=0)


@pytest.mark.parametrize("address", ["192.168.1.20", "10.0.2.15", "2001:db8::1",
                                    "01234567-89ab-cdef-0123-456789abcdef.local"])
def test_candidate_is_an_ephemeral_ice_hint_not_arbitrary_dns(address):
    assert candidate(wire(address)) == wire(address)


@pytest.mark.parametrize("value", [wire("arbitrary.example.test"), wire("999.1.2.3"),
    wire() | dict(owner="another"), wire() | dict(sdpMLineIndex=True), wire() | dict(sdpMLineIndex="0"),
    wire() | dict(sdpMLineIndex=8), wire() | dict(candidate="x" * 2049),
    wire() | dict(candidate=wire()["candidate"] + "\r\na=other"), wire() | dict(sdpMid="../private")])
def test_unbounded_or_unscoped_ice_fields_are_rejected(value):
    with pytest.raises(InvalidDirectProbe, match="invalid_ice_candidate"):
        candidate(value)
