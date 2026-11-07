"""Optional local ICE discovery helper. No SDP, video, input, or arbitrary DNS API.

Run on a workstation whose local network contains the Chromium viewer. The
central server still authorizes each session; SRTP/SCTP flow directly to APK.
This does not extend multicast across the Internet or promise universal P2P.
"""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import re
import signal
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID

import dns.flags
import dns.message
import dns.rdatatype

MAX_NAMES = 4
MAX_BODY = 1024
MAX_DNS_PACKET = 8192
MAX_PACKETS = 64
QUERY_SECONDS = .45
PRIVATE_V4 = tuple(ipaddress.ip_network(value) for value in
                   ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def valid_name(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith(".local"):
        return False
    try:
        return str(UUID(value[:-6])) == value[:-6]
    except (ValueError, AttributeError):
        return False


def private_v4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return isinstance(address, ipaddress.IPv4Address) and any(address in subnet for subnet in PRIVATE_V4)
    except ValueError:
        return False


def interface_addresses() -> tuple[str, ...]:
    import psutil

    values = {row.address for rows in psutil.net_if_addrs().values() for row in rows
              if row.family == socket.AF_INET and (row.address == "127.0.0.1" or private_v4(row.address))}
    return tuple(sorted(values))[:16]


def answer_addresses(packet: bytes, names: tuple[str, ...]) -> dict[str, set[str]]:
    """dnspython parses bounds/compression; account for mDNS's cache-flush class bit."""
    result: dict[str, set[str]] = {}
    if not 12 <= len(packet) <= MAX_DNS_PACKET:
        return result
    try:
        message = dns.message.from_wire(packet, ignore_trailing=False)
        if not message.flags & dns.flags.QR or message.rcode() != 0:
            return result
        for answer in message.answer:
            name = answer.name.to_text().lower().rstrip(".")
            if (name not in names or answer.rdtype != dns.rdatatype.A or answer.rdclass & 0x7fff != 1
                    or not 0 < answer.ttl <= 86400):
                continue
            for value in answer:
                wire = value.to_wire()
                if len(wire) == 4:
                    address = str(ipaddress.ip_address(wire))
                    if private_v4(address):
                        result.setdefault(name, set()).add(address)
    except (dns.exception.DNSException, ValueError, UnicodeError):
        return {}
    return result


def resolve_names(names: tuple[str, ...]) -> dict[str, str]:
    addresses = interface_addresses()
    found: dict[str, set[str]] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("", 5353))
        listener.settimeout(.05)
        for address in addresses:
            try:
                listener.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                    socket.inet_aton("224.0.0.251") + socket.inet_aton(address))
            except OSError:
                continue
        for name in names:
            query = dns.message.make_query(name, dns.rdatatype.A)
            query.id = query.flags = 0
            # Chromium's responder supports single questions. A+AAAA in the
            # same packet and only listening on an ephemeral port lose replies.
            packet = query.to_wire()
            for address in addresses:
                try:
                    listener.sendto(packet, (address, 5353))
                    listener.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(address))
                    listener.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
                    listener.sendto(packet, ("224.0.0.251", 5353))
                except OSError:
                    continue
        deadline = time.monotonic() + QUERY_SECONDS
        packets = 0
        while time.monotonic() < deadline and packets < MAX_PACKETS:
            try:
                packet, _ = listener.recvfrom(MAX_DNS_PACKET + 1)
            except socket.timeout:
                continue
            packets += 1
            for name, values in answer_addresses(packet, names).items():
                found.setdefault(name, set()).update(values)
            if all(name in found for name in names):
                break
    # Ambiguous names are left untouched rather than guessing a private host.
    return {name: next(iter(values)) for name, values in found.items() if len(values) == 1}


def request_names(data: object) -> tuple[str, tuple[str, ...]]:
    if (not isinstance(data, dict) or data.keys() != {"version", "session", "names"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["session"], str) or not re.fullmatch(r"[0-9a-f]{32}", data["session"])
            or not isinstance(data["names"], list) or not 1 <= len(data["names"]) <= MAX_NAMES
            or not all(valid_name(value) for value in data["names"])
            or len(set(data["names"])) != len(data["names"])):
        raise ValueError("invalid_request")
    return data["session"], tuple(data["names"])


class LocalResolverServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, key: str):
        self.key = key
        self.slots = threading.BoundedSemaphore(4)
        self.rate_lock = threading.Lock()
        self.request_times: deque[float] = deque(maxlen=64)
        self.counters = {"accepted": 0, "resolved": 0, "unresolved": 0, "rejected": 0}
        super().__init__(("127.0.0.1", port), Handler)
        self.timeout = .25

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Do not log private request bodies, names, or authentication headers.
        pass

    def admit(self) -> bool:
        now = time.monotonic()
        with self.rate_lock:
            while self.request_times and self.request_times[0] <= now - 60:
                self.request_times.popleft()
            if len(self.request_times) >= 60:
                return False
            self.request_times.append(now)
            self.counters["accepted"] += 1
            return True


class Handler(BaseHTTPRequestHandler):
    server: LocalResolverServer

    def setup(self):
        super().setup()
        self.request.settimeout(.5)

    def log_message(self, *args):
        pass

    def reply(self, status: int, data: dict) -> None:
        payload = json.dumps(data, separators=(",", ":")).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self) -> bool:
        value = self.headers.get("Authorization", "")
        return len(value) <= 300 and hmac.compare_digest(value, "Bearer " + self.server.key)

    def do_GET(self):
        if self.path != "/health" or not self.authorized():
            return self.reply(403, {"error": "forbidden"})
        self.reply(200, {"service": "sphere-local-mdns", "version": 1, "media_relay": False})

    def do_POST(self):
        if self.path != "/v1/mdns" or not self.authorized():
            return self.reply(403, {"error": "forbidden"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                # Drain only one byte over the cap so a small malformed body
                # receives the rejection before Windows resets the socket.
                self.rfile.read(min(length, MAX_BODY + 1))
                raise ValueError("oversized_body")
            if (not 1 <= length <= MAX_BODY or self.headers.get("Transfer-Encoding")
                    or self.headers.get("Content-Type", "").split(";")[0] != "application/json"):
                raise ValueError("invalid_body")
            session, names = request_names(json.loads(self.rfile.read(length)))
        except (ValueError, UnicodeError, OSError):
            return self.reply(400, {"error": "invalid_request"})
        if not self.server.admit():
            return self.reply(429, {"error": "rate_limited"})
        try:
            mapping = resolve_names(names)
        except OSError:
            mapping = {}
        self.server.counters["resolved" if mapping else "unresolved"] += 1
        self.reply(200, {"version": 1, "session": session,
                         "resolved": [{"name": name, "address": address} for name, address in mapping.items()]})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--max-lifetime-seconds", type=int, default=0,
                        help="0 runs until stopped; finite checks may use 60..86400 seconds")
    args = parser.parse_args()
    key = args.token_file.read_text(encoding="utf-8").strip()
    if (not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key) or not 0 <= args.port <= 65535
            or not (args.max_lifetime_seconds == 0 or 60 <= args.max_lifetime_seconds <= 86400)):
        parser.error("invalid private configuration")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    with LocalResolverServer(args.port, key) as server:
        args.ready_file.write_text(json.dumps({"pid": os.getpid(), "port": server.server_port,
                                               "mediaRelay": False, "version": 1}) + "\n", encoding="utf-8")
        print(json.dumps({"ready": True, "scope": "loopback discovery only", "mediaRelay": False}), flush=True)
        deadline = time.monotonic() + args.max_lifetime_seconds if args.max_lifetime_seconds else None
        while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
            server.handle_request()


if __name__ == "__main__":
    main()
