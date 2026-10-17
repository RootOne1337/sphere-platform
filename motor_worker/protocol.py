"""Bounded implementation of the existing Sphere video/shared-admission wire.

Does not import the backend or grant input authority. Default operation emits
OPEN/idle HEARTBEAT/CLOSE only. Pointer events need a separate explicit opt-in;
keys, text and game profiles are not implemented here.
"""

from __future__ import annotations

import ipaddress
import json
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit


class ProtocolError(ValueError):
    """Only fixed reason codes may cross the diagnostic boundary."""


def integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _unique(pairs: list[tuple]) -> dict:
    result = {}
    for k, v in pairs:
        if k in result:
            raise ProtocolError("duplicate_json_key")
        result[k] = v
    return result


def message(raw: object, limit: int = 36864) -> dict:
    if not isinstance(raw, str) or len(raw.encode()) > limit:
        raise ProtocolError("message_size_or_type")
    try:
        data = json.loads(raw, object_pairs_hook=_unique, parse_constant=lambda _: None)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("invalid_json") from exc
    if not isinstance(data, dict):
        raise ProtocolError("invalid_message")
    return data


def signaling_url(base: str, device: str) -> str:
    try:
        if str(uuid.UUID(device)) != device:
            raise ValueError()
        url = urlsplit(base)
        port = url.port
    except (ValueError, TypeError) as exc:
        raise ProtocolError("invalid_endpoint") from exc
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
        or any(c.isspace() for c in base)
    ):
        raise ProtocolError("invalid_endpoint")
    if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProtocolError("plaintext_non_loopback_endpoint")
    if port is not None and not 1 <= port <= 65535:
        raise ProtocolError("invalid_endpoint")
    return (
        ("wss" if url.scheme == "https" else "ws")
        + "://"
        + url.netloc
        + "/ws/direct-probe/"
        + device
    )


def validate_sdp(sdp: object, *, offer: bool) -> str:
    if not isinstance(sdp, str) or not 0 < len(sdp.encode()) <= 32768:
        raise ProtocolError("invalid_sdp")
    lines = sdp.splitlines()
    sections: list[list[str]] = []
    for line in lines:
        if line.startswith("m="):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
    video = [s for s in sections if s[0].startswith("m=video ")]
    application = [s for s in sections if s[0].startswith("m=application ")]
    fingerprints = [line for line in lines if line.startswith("a=fingerprint:")]
    if (
        not lines
        or lines[0] != "v=0"
        or len(sections) != 2
        or len(video) != 1
        or len(application) != 1
        or "UDP/TLS/RTP/SAVPF" not in video[0][0]
        or "UDP/DTLS/SCTP" not in application[0][0]
        or sum(
            line in {"a=sendonly", "a=recvonly", "a=sendrecv", "a=inactive"} for line in video[0]
        )
        != 1
        or ("a=recvonly" if offer else "a=sendonly") not in video[0]
        or not any(re.fullmatch(r"a=rtpmap:[0-9]+ H264/90000", line, re.I) for line in video[0])
        or not 1 <= len(fingerprints) <= 3
        or any(
            not re.fullmatch(r"a=fingerprint:sha-256 (?:[0-9a-f]{2}:){31}[0-9a-f]{2}", line, re.I)
            for line in fingerprints
        )
        or sum(line.startswith("a=candidate:") for line in lines) > 64
        or any(
            re.search(r"\btyp relay\b", line) for line in lines if line.startswith("a=candidate:")
        )
    ):
        raise ProtocolError("invalid_sdp")
    return sdp


def wire_offer(sdp: str) -> str:
    # aiortc advertises SHA-256/384/512 for the same local certificate. Sphere's
    # existing admission deliberately allows only SHA-256 (also used by Android).
    # Keep the real SHA-256 fingerprint; never weaken the remote SDP validator.
    lines = [
        line
        for line in sdp.splitlines()
        if not line.startswith(("a=fingerprint:sha-384 ", "a=fingerprint:sha-512 "))
    ]
    # aiortc includes a sender SSRC/MSID even on a receive-only transceiver.
    # This client sends no video. Do not announce a nonexistent remote source
    # to Android's send-only encoded-video factory.
    lines = [line for line in lines if not line.startswith(("a=ssrc:", "a=ssrc-group:", "a=msid:"))]
    # The pinned PyAV software H.264 decoder receives constrained baseline up to
    # level 4.2. aiortc's stock 3.1 offer is insufficient for APK 960x540 at 60fps.
    # Change only that codec's constrained-baseline fmtp, not ICE/DTLS/payload IDs.
    h264 = {m[1] for line in lines if (m := re.fullmatch(r"a=rtpmap:(\d+) H264/90000", line, re.I))}
    for i, line in enumerate(lines):
        fmtp = re.fullmatch(r"a=fmtp:(\d+) (.*)", line)
        if (
            fmtp
            and fmtp[1] in h264
            and "packetization-mode=1" in fmtp[2]
            and "level-asymmetry-allowed=1" in fmtp[2]
        ):
            lines[i] = re.sub(
                r"(profile-level-id=)42e0[0-9a-f]{2}", r"\g<1>42e02a", line, flags=re.I
            )
    return validate_sdp("\r\n".join(lines) + "\r\n", offer=True)


@dataclass(frozen=True)
class VideoBinding:
    epoch: str
    width: int
    height: int

    @classmethod
    def parse(cls, raw: object, session: str) -> VideoBinding:
        match = (
            re.fullmatch(
                r"SV1 ([0-9a-f]{32}) ([0-9a-f-]{36}) ([1-9][0-9]{0,4}) ([1-9][0-9]{0,4})", raw
            )
            if isinstance(raw, str)
            else None
        )
        if not match or match[1] != session:
            raise ProtocolError("invalid_capture_binding")
        try:
            epoch = str(uuid.UUID(match[2]))
        except ValueError as exc:
            raise ProtocolError("invalid_capture_binding") from exc
        width, height = int(match[3]), int(match[4])
        if (
            epoch != match[2]
            or uuid.UUID(epoch).int == 0
            or width > 8192
            or height > 8192
            or ((width + 15) // 16) * ((height + 15) // 16) > 36864
        ):
            raise ProtocolError("invalid_capture_binding")
        return cls(epoch, width, height)


class InputAvailability:
    """A bound state snapshot; it never substitutes for native READY or an ACK."""

    def __init__(self, session: str):
        self.session = session
        self.epoch: str | None = None
        self.snapshot: dict | None = None

    def bind(self, epoch: str) -> None:
        if self.snapshot and self.snapshot["capture_epoch"] != epoch:
            raise ProtocolError("foreign_availability_capture")
        self.epoch = epoch

    def receive(self, data: dict) -> None:
        epoch = data.get("capture_epoch")
        try:
            canonical = (
                isinstance(epoch, str)
                and str(uuid.UUID(epoch)) == epoch
                and uuid.UUID(epoch).int != 0
            )
        except ValueError:
            canonical = False
        state, task = data.get("state"), data.get("task_id")
        if (
            data.keys()
            != {
                "type",
                "schema_version",
                "session_id",
                "capture_epoch",
                "revision",
                "state",
                "task_id",
            }
            or data["type"] != "input_availability"
            or not integer(data["schema_version"], 1, 1)
            or data["session_id"] != self.session
            or not canonical
            or self.epoch is not None
            and epoch != self.epoch
            or not integer(data["revision"], 0, 2**53 - 1)
            or not isinstance(state, str)
            or state not in {"manual", "preparing", "automation", "cleanup_unknown"}
            or task is not None
            and (not isinstance(task, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", task))
            or state in {"preparing", "automation"}
            and task is None
            or state == "manual"
            and task is not None
        ):
            raise ProtocolError("invalid_input_availability")
        if self.snapshot and (
            data["revision"] < self.snapshot["revision"]
            or data["revision"] == self.snapshot["revision"]
            and data != self.snapshot
        ):
            raise ProtocolError("stale_or_conflicting_availability")
        self.snapshot = dict(data)

    @property
    def state(self) -> str | None:
        return self.snapshot["state"] if self.snapshot else None


class ControlAdmission:
    """Finite observer of native admission. READY is never inferred from media."""

    def __init__(self, session: str, binding: VideoBinding, *, allow_pointer: bool = False):
        if type(allow_pointer) is not bool:
            raise ProtocolError("invalid_control_option")
        self.session, self.binding = session, binding
        self.owner: str | None = None
        self.ready = False
        self.ever_ready = False
        self.closing = False
        self.closed = False
        self.failure: str | None = None
        self.sequence = 0
        self.pending: tuple[int, float] | None = None
        self.alive_receipts = 0
        self.last_actor_rtt_ms: float | None = None
        self.allow_pointer = allow_pointer
        self.pending_event: tuple[int, int] | None = None
        self.held = False
        self.gesture = 0
        self.xy = (0, 0)
        self.pointer_commands = 0
        self.applied_receipts = 0
        self.last_action_rtt_ms: float | None = None

    def open_message(self) -> dict:
        return {
            "type": "touch_open",
            "capture_epoch": self.binding.epoch,
            "frame_width": self.binding.width,
            "frame_height": self.binding.height,
        }

    def receive(self, raw: object, now: float) -> None:
        data = message(raw, 1024)
        if data.get("type") == "touch_session":
            if (
                self.owner is not None
                or data.keys()
                != {"type", "session_id", "owner", "capture_epoch", "frame_width", "frame_height"}
                or data.get("session_id") != self.session
                or data.get("capture_epoch") != self.binding.epoch
                or type(data.get("frame_width")) is not int
                or data["frame_width"] != self.binding.width
                or type(data.get("frame_height")) is not int
                or data["frame_height"] != self.binding.height
                or not isinstance(data.get("owner"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", data["owner"])
            ):
                raise ProtocolError("invalid_control_identity")
            self.owner = data["owner"]
            return
        if (
            self.owner is None
            or data.keys()
            != {
                "type",
                "session_id",
                "owner",
                "capture_epoch",
                "sequence",
                "gesture",
                "action",
                "outcome",
                "device_uptime_ms",
            }
            or data.get("type") != "shared_input_status"
            or data.get("session_id") != self.session
            or data.get("owner") != self.owner
            or data.get("capture_epoch") != self.binding.epoch
            or not integer(data.get("sequence"), 0, 2147483647)
            or not integer(data.get("gesture"), 0, 2147483647)
            or not integer(data.get("action"), 0, 4)
            or not integer(data.get("device_uptime_ms"), 0, 2**53 - 1)
        ):
            raise ProtocolError("invalid_control_receipt")
        seq, outcome = data["sequence"], data["outcome"]
        if not isinstance(outcome, str):
            raise ProtocolError("invalid_control_outcome")
        if outcome == "closed" and seq == 0 and data["gesture"] == 0 and data["action"] == 3:
            self.closed = True
            self.ready = False
            self.pending = None
            self.pending_event = None
            self.held = False
        elif outcome == "ready" and seq == 0 and data["gesture"] == 0 and data["action"] == 4:
            if self.closing or self.closed or self.failure or self.ever_ready:
                raise ProtocolError("unexpected_control_ready")
            self.ready = self.ever_ready = True
        elif (
            outcome == "alive"
            and (self.ready or self.closing)
            and not self.closed
            and not self.failure
            and self.pending
            and seq == self.pending[0]
            and self.pending_event is None
            and data["gesture"] == (self.gesture if self.held else 0)
            and data["action"] == 4
        ):
            self.alive_receipts += 1
            self.last_actor_rtt_ms = max(0, (now - self.pending[1]) * 1000)
            self.pending = None
        elif (
            outcome == "applied"
            and self.allow_pointer
            and (self.ready or self.closing)
            and not self.closed
            and not self.failure
            and self.pending
            and seq == self.pending[0]
            and self.pending_event == (data["gesture"], data["action"])
        ):
            self.held = data["action"] in {0, 2}
            self.applied_receipts += 1
            self.last_action_rtt_ms = max(0, (now - self.pending[1]) * 1000)
            self.pending = self.pending_event = None
        elif outcome == "interrupted" and self.allow_pointer:
            self.failure = "control_interrupted"
            self.ready = False
        elif outcome in {"denied", "unknown", "expired", "invalid", "busy"}:
            self.failure = "control_" + outcome
            self.ready = False
        else:
            raise ProtocolError("unexpected_control_receipt")

    def heartbeat(self, now: float) -> dict | None:
        if not self.ready or self.closing or self.closed or self.failure:
            return None
        if self.pending:
            if now - self.pending[1] >= (0.5 if self.pending_event else 1):
                raise ProtocolError(
                    "control_action_deadline" if self.pending_event else "control_alive_deadline"
                )
            return None
        self.sequence += 1
        if self.sequence > 2147483647:
            raise ProtocolError("control_sequence_limit")
        self.pending = self.sequence, now
        return {
            "type": "touch_event",
            "sequence": self.sequence,
            "gesture": self.gesture if self.held else 0,
            "action": 4,
            "x": self.xy[0],
            "y": self.xy[1],
        }

    def pointer(self, action: int, x: int, y: int, now: float) -> dict:
        if (
            not self.allow_pointer
            or not self.ready
            or self.closing
            or self.closed
            or self.failure
            or self.pending is not None
            or not integer(action, 0, 3)
            or not integer(x, 0, self.binding.width - 1)
            or not integer(y, 0, self.binding.height - 1)
            or (self.held if action == 0 else not self.held)
        ):
            raise ProtocolError("pointer_not_admitted")
        if action == 0:
            self.gesture += 1
        self.sequence += 1
        if self.sequence > 2147483647 or self.gesture > 2147483647:
            raise ProtocolError("control_sequence_limit")
        self.pending = self.sequence, now
        self.pending_event = self.gesture, action
        self.xy = x, y
        self.pointer_commands += 1  # Reserve before a potentially partial send; never retry.
        return dict(
            type="touch_event",
            sequence=self.sequence,
            gesture=self.gesture,
            action=action,
            x=x,
            y=y,
        )

    def close_message(self) -> dict:
        self.closing = True
        self.ready = False
        return {"type": "touch_close"}


def selected_route(peer: object) -> dict:
    """Guarded aiortc 1.15 adapter: public stats do not expose the selected pair.

    Only inspect nominated pairs, never the first succeeded/checklist candidate.
    Addresses stay out of the report. Attribute absence means unknown, not LAN.
    """
    unknown = {"path": "unknown", "protocol": None, "evidence": "unavailable", "lanProven": False}
    try:
        connection = peer.sctp.transport.transport._connection
        pairs = list(connection._nominated.values())
        if not pairs:
            return unknown
        types = [c.type for p in pairs for c in (p.local_candidate, p.remote_candidate)]
        transports = {
            c.transport.lower() for p in pairs for c in (p.local_candidate, p.remote_candidate)
        }
        if any(t not in {"host", "srflx", "prflx", "relay"} for t in types):
            return unknown
        scopes = []
        for p in pairs:
            for c in (p.local_candidate, p.remote_candidate):
                address = ipaddress.ip_address(c.host)
                scopes.append(
                    "loopback"
                    if address.is_loopback
                    else "private"
                    if address.is_private
                    else "public"
                )
        return {
            "path": "relay"
            if "relay" in types
            else "host"
            if all(t == "host" for t in types)
            else "nat",
            "protocol": "udp" if transports == {"udp"} else "unknown",
            "candidateTypes": types,
            "addressScopes": scopes,
            "evidence": "aiortc_1_15_nominated_pair_adapter",
            "lanProven": False,
        }
    except (AttributeError, TypeError, ValueError):
        return unknown
