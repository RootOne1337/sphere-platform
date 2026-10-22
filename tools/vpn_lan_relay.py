"""Private-LAN AWG2 canary relay, with a bounded lifetime and one pinned client.

This optional diagnostic gateway forwards ciphertext only. It never configures
the OS network, stores tunnel keys, or proves a direct Android-to-server path.
The Android UID guard must remain installed independently of this process.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import select
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClientGate:
    allowed: ipaddress.IPv4Network
    header: int
    padding: int
    peer: tuple[str, int] | None = None
    rebindings: int = 0

    def accept(self, data: bytes, address: tuple[str, int]) -> bool:
        try:
            source = ipaddress.IPv4Address(address[0])
        except ipaddress.AddressValueError:
            return False
        if source not in self.allowed or not 1 <= len(data) <= 3072:
            return False
        if self.peer == address:
            return True
        if self.peer is not None and self.peer[0] != address[0]:
            return False
        # This public marker only pins a LAN endpoint. Authentication remains
        # the remote AWG server's cryptographic handshake, not this comparison.
        if len(data) != 148 + self.padding or struct.unpack_from("<I", data, self.padding)[0] != self.header:
            return False
        self.peer = address
        self.rebindings += 1
        return True


@dataclass
class PacketBudget:
    per_second: int
    tokens: float = 0
    sampled: float = 0

    def take(self, now: float) -> bool:
        self.tokens = min(self.per_second, self.tokens + max(0, now - self.sampled) * self.per_second)
        self.sampled = max(self.sampled, now)
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--allowed-lan", required=True)
    parser.add_argument("--upstream", required=True, help="Literal IPv4:UDP port; no credentials")
    parser.add_argument("--h1", type=int, required=True)
    parser.add_argument("--s1", type=int, required=True)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument("--packets-per-second", type=int, default=2000)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bind = ipaddress.IPv4Address(args.bind)
        network = ipaddress.IPv4Network(args.allowed_lan)
        host, port = args.upstream.rsplit(":", 1)
        target = ipaddress.IPv4Address(host)
        args.target = (str(target), int(port))
        args.network = network
        valid = bind.is_private and not bind.is_unspecified and not bind.is_loopback and not bind.is_multicast
        valid &= network.is_private and network.prefixlen >= 24 and bind in network
        valid &= not target.is_unspecified and not target.is_multicast and not target.is_loopback
        valid &= 1 <= args.port <= 65535 and 1 <= args.target[1] <= 65535
        valid &= 0 <= args.h1 < 2**32 and 0 <= args.s1 <= 64
        valid &= 1 <= args.seconds <= 86400 and 1 <= args.packets_per_second <= 10000
        valid &= args.state.parent.is_dir() and args.stop_file.parent.is_dir()
        valid &= args.state.resolve() != args.stop_file.resolve() and not args.stop_file.exists()
        if not valid:
            raise ValueError
    except (ValueError, TypeError):
        parser.error("Invalid bounded private-LAN relay settings")
    return args


def run(args: argparse.Namespace) -> None:
    gate = ClientGate(args.network, args.h1, args.s1)
    started = time.monotonic()
    expires = time.time() + args.seconds
    budgets = {name: PacketBudget(args.packets_per_second, args.packets_per_second, started)
               for name in ("lan", "wan")}
    counters = {key: 0 for key in ("toServerPackets", "toAndroidPackets", "toServerBytes", "toAndroidBytes",
                                   "rejectedPackets", "rateLimitedPackets", "socketErrors")}
    last_save = 0.0
    state = "closed"

    def save(phase: str) -> None:
        value = {"state": phase, "elapsedSeconds": round(time.monotonic() - started, 1),
                 "expiresAtEpochSeconds": int(expires), "ciphertextOnly": True,
                 "containsVpnKeys": False, "osRoutesModified": False, "firewallModified": False,
                 "rebindings": gate.rebindings, **counters}
        temp = args.state.with_suffix(args.state.suffix + ".tmp")
        temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        temp.replace(args.state)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as lan, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as wan:
        lan.bind((args.bind, args.port))
        wan.connect(args.target)
        for stream in (lan, wan):
            if hasattr(socket, "SIO_UDP_CONNRESET"):
                stream.ioctl(socket.SIO_UDP_CONNRESET, False)
        save("listening")
        try:
            while time.monotonic() - started < args.seconds and not args.stop_file.exists():
                now = time.monotonic()
                if now - last_save >= 1:
                    save("running")
                    last_save = now
                readable, _, _ = select.select([lan, wan], [], [], .25)
                for stream in readable:
                    try:
                        data, address = stream.recvfrom(3073)
                        if len(data) > 3072:
                            counters["rejectedPackets"] += 1
                            continue
                        direction = "lan" if stream is lan else "wan"
                        if not budgets[direction].take(time.monotonic()):
                            counters["rateLimitedPackets"] += 1
                            continue
                        if stream is lan:
                            if not gate.accept(data, address):
                                counters["rejectedPackets"] += 1
                                continue
                            wan.send(data)
                            counters["toServerPackets"] += 1
                            counters["toServerBytes"] += len(data)
                        elif gate.peer is not None:
                            lan.sendto(data, gate.peer)
                            counters["toAndroidPackets"] += 1
                            counters["toAndroidBytes"] += len(data)
                    except (ConnectionResetError, ConnectionRefusedError):
                        counters["socketErrors"] += 1
            state = "stopped" if args.stop_file.exists() else "expired"
        finally:
            save(state)


if __name__ == "__main__":
    run(arguments())
