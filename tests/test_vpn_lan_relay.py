import ipaddress
import json
import socket
import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.vpn_lan_relay import ClientGate, PacketBudget, arguments, run, write_state


def handshake(header=12345, padding=32):
    result = bytearray(148 + padding)
    struct.pack_into("<I", result, padding, header)
    return bytes(result)


def test_only_one_lan_host_can_pin_and_rebind_after_a_valid_header():
    gate = ClientGate(ipaddress.IPv4Network("192.168.1.0/24"), 12345, 32)
    assert not gate.accept(handshake(), ("203.0.113.1", 20000))
    assert not gate.accept(b"junk", ("192.168.1.2", 20000))
    assert gate.accept(handshake(), ("192.168.1.2", 20000))
    assert gate.accept(b"ciphertext", ("192.168.1.2", 20000))
    assert not gate.accept(handshake(), ("192.168.1.3", 20001))
    assert not gate.accept(b"ciphertext", ("192.168.1.2", 20001))
    assert gate.accept(handshake(), ("192.168.1.2", 20001))
    assert gate.rebindings == 2


def test_bad_header_oversized_and_empty_packets_never_select_a_peer():
    gate = ClientGate(ipaddress.IPv4Network("192.168.1.0/24"), 12345, 32)
    for packet in (b"", b"x" * 3073, handshake(999), handshake()[:-1]):
        assert not gate.accept(packet, ("192.168.1.2", 20000))
    assert gate.peer is None


def test_packet_budget_caps_bursts_and_refills_without_clock_reversal_credit():
    budget = PacketBudget(2, 2, 10.0)
    assert budget.take(10.0)
    assert budget.take(10.0)
    assert not budget.take(10.0)
    assert not budget.take(9.0)
    assert not budget.take(10.0)
    assert budget.take(10.5)
    assert not budget.take(10.5)
    assert budget.take(100.0)
    assert budget.take(100.0)
    assert not budget.take(100.0)


@pytest.mark.parametrize("override", [
    ["--bind", "0.0.0.0"], ["--bind", "127.0.0.1"],
    ["--seconds", "86401"], ["--allowed-lan", "192.168.0.0/16"],
    ["--h1", str(2**32)], ["--port", "0"],
])
def test_cli_rejects_unbounded_or_non_lan_configuration(tmp_path, override):
    argv = ["--bind", "192.168.0.50", "--port", "57886", "--allowed-lan", "192.168.0.0/24",
            "--upstream", "203.0.113.5:57401", "--h1", "12345", "--s1", "32",
            "--state", str(tmp_path / "state.json"), "--stop-file", str(tmp_path / "STOP")]
    with pytest.raises(SystemExit):
        arguments(argv + override)


@pytest.mark.parametrize("reader_denials", [0, 2])
def test_real_socket_forwarding_preserves_bytes_and_stop_closes_both_sockets(tmp_path, monkeypatch, reader_denials):
    # Exercise the transport library entirely on loopback; the CLI separately
    # rejects loopback deployment. No external service or host routing is used.
    replace = Path.replace
    attempts = 0

    def transient_reader_lock(path, target):
        nonlocal attempts
        if Path(target) == tmp_path / "state.json":
            attempts += 1
            if attempts <= reader_denials:
                error = PermissionError("Windows status reader holds delete sharing")
                error.winerror = 5
                raise error
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", transient_reader_lock)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
        reserve.bind(("127.0.0.1", 0))
        relay_port = reserve.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
        upstream.bind(("127.0.0.1", 0))
        upstream.settimeout(2)
        args = SimpleNamespace(bind="127.0.0.1", port=relay_port, target=upstream.getsockname(),
                               network=ipaddress.IPv4Network("127.0.0.0/8"), h1=12345, s1=32,
                               seconds=5, packets_per_second=100,
                               state=tmp_path / "state.json", stop_file=tmp_path / "STOP")
        failures = []

        def worker():
            try:
                run(args)
            except Exception as error:
                failures.append(error)

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while not args.state.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            assert args.state.exists()
            packet = handshake()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(2)
                client.sendto(packet, ("127.0.0.1", relay_port))
                captured, sender = upstream.recvfrom(3072)
                assert captured == packet
                upstream.sendto(captured, sender)
                assert client.recv(3072) == packet
        finally:
            args.stop_file.write_text("stop test\n")
            thread.join(2)
        assert not thread.is_alive() and not failures
        state = json.loads(args.state.read_text())
        assert state["state"] == "stopped"
        assert state["toServerPackets"] == state["toAndroidPackets"] == 1
        assert "127.0.0.1" not in args.state.read_text()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as released:
            released.bind(("127.0.0.1", relay_port))


@pytest.mark.parametrize("winerror", [5, 32, 33, None])
def test_permanent_status_denial_is_bounded_and_preserves_complete_previous_snapshot(tmp_path, monkeypatch, winerror):
    path = tmp_path / "state.json"
    path.write_text('{"state":"previous"}')
    delays = []
    attempts = []

    def denied_replace(*args):
        attempts.append(True)
        error = PermissionError("status replace denied")
        if winerror is not None:
            error.winerror = winerror
        raise error

    monkeypatch.setattr(Path, "replace", denied_replace)
    monkeypatch.setattr("tools.vpn_lan_relay.time.sleep", delays.append)
    with pytest.raises(PermissionError):
        write_state(path, {"state": "next"})
    assert len(attempts) == (6 if winerror is not None else 1)
    assert sum(delays) <= .311
    assert json.loads(path.read_text()) == {"state": "previous"}


def test_lease_expiry_stops_without_a_stop_file_and_releases_the_port(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
        reserve.bind(("127.0.0.1", 0))
        relay_port = reserve.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
        upstream.bind(("127.0.0.1", 0))
        args = SimpleNamespace(bind="127.0.0.1", port=relay_port, target=upstream.getsockname(),
                               network=ipaddress.IPv4Network("127.0.0.0/8"), h1=12345, s1=32,
                               seconds=1, packets_per_second=100,
                               state=tmp_path / "state.json", stop_file=tmp_path / "STOP")
        started = time.monotonic()
        run(args)
    assert 1 <= time.monotonic() - started < 3
    state = json.loads(args.state.read_text())
    assert state["state"] == "expired" and not args.stop_file.exists()
    assert state["toServerPackets"] == state["toAndroidPackets"] == 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as released:
        released.bind(("127.0.0.1", relay_port))
