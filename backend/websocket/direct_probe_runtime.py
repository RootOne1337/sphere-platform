"""Ephemeral, generation-bound SDP routing. No offline queue or signal replay."""
from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from backend.core.config import settings
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.channels import ChannelPattern
from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.continuous_lease import no_replay_redis
from backend.websocket.direct_probe_ice import validate_turn_grant
from backend.websocket.direct_probe_mdns import resolve_offer
from backend.websocket.direct_probe_protocol import (
    LIVE_VIDEO_MIN_AGENT_CODE,
    LIVE_VIDEO_MODE,
    MAX_PEERS,
    MAX_WIRE_BYTES,
    SESSION_MS,
    VIDEO_MIN_AGENT_CODE,
    VIDEO_MODE,
    InvalidDirectProbe,
    agent_answer,
    description,
    session_id,
)
from backend.websocket.direct_probe_telemetry import native_peer_report
from backend.websocket.shared_peer_lease import SHARED_PEER_MIN_AGENT_CODE, SharedPeerLease
from backend.websocket.stream_session_history import StreamSessionHistory, utc_now

OPERATION_SECONDS = 2.0
LEGACY_HANDOVER_MIN_AGENT_CODE = 10260
DELETE_EXACT = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"
REMAINING_EXACT = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('PTTL', KEYS[1]) else return 0 end"
RENEW_EXACT = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('PEXPIRE', KEYS[1], ARGV[2]) else return 0 end"


@dataclass
class ProbeViewer:
    device: str
    org: str
    user: str
    ws: Any
    session: str = ""
    binding: dict | None = None
    answered: bool = False
    offered: bool = False
    reserving: bool = False
    retired: bool = False
    ice: dict | None = field(default=None, repr=False)
    video: bool = False
    live: bool = False
    renewal: int = 0
    renewed_at: float = 0
    control_session: str | None = None
    history_session: str | None = None
    shared_control: bool = False


@dataclass
class PendingProbe:
    binding: dict
    deadline: float
    answered: bool = False
    diagnostic_sequence: int = 0
    diagnostic_elapsed: int = -1
    diagnostic_at: float = -float("inf")
    diagnostic_closed: bool = False


class DirectProbeRuntime:
    def __init__(self, redis: Any, manager: ConnectionManager, namespace: str = "sphere:direct-probe:v1") -> None:
        self.redis, self.manager, self.namespace = redis, manager, namespace
        self.shared = SharedPeerLease(redis, namespace)
        self.worker = secrets.token_hex(16)
        self.viewers: dict[str, ProbeViewer] = {}
        self.pending: dict[str, PendingProbe] = {}
        self.available = False
        self.pubsub: Any = None
        self.task: asyncio.Task | None = None
        self.reservations = 0
        self.diagnostics: asyncio.Queue[tuple[PendingProbe, dict[str, Any]]] = asyncio.Queue(maxsize=4)
        self.diagnostic_task: asyncio.Task | None = None

    @property
    def viewer_channel(self) -> str:
        return f"{self.namespace}:viewer:{self.worker}"

    def key(self, device: str) -> str:
        return f"{self.namespace}:lease:{device}"

    def lease_key(self, binding: dict) -> str:
        return self.shared.key(binding["device"], binding["session"]) if binding.get("shared") is True else self.key(binding["device"])

    async def peer_binding(self, device: str, session: str) -> str | bytes | None:
        session_id(session)
        raw = await self.redis.get(self.shared.key(device, session))
        return raw if raw is not None else await self.redis.get(self.key(device))

    @staticmethod
    def encode(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":"), sort_keys=True)
        if len(raw.encode()) > MAX_WIRE_BYTES:
            raise InvalidDirectProbe("message_too_large")
        return raw

    async def start(self) -> None:
        self.pubsub = self.redis.pubsub()
        async with asyncio.timeout(OPERATION_SECONDS):
            await self.pubsub.psubscribe(f"{self.namespace}:agent:*")
            await self.pubsub.subscribe(self.viewer_channel)
        self.available = True
        self.task = asyncio.create_task(self.listen())
        self.diagnostic_task = asyncio.create_task(self.write_diagnostics())

    async def topology(self, binding: dict) -> bool:
        status = await DeviceStatusCache(self.redis).get_status(binding["device"])
        return bool(status and status.ws_session_id == binding["agent_session"]
                    and status.status in {"online", "busy", "connecting"})

    async def remaining(self, binding: dict) -> int:
        if not await self.topology(binding):
            return 0
        # GET + PTTL must be atomic: an expired owner's GET cannot borrow a newer owner's TTL.
        ttl = await self.redis.eval(REMAINING_EXACT, 1, self.lease_key(binding), self.encode(binding))
        return ttl if 0 < ttl <= SESSION_MS else 0

    async def input_peer(self, *, device: str, org: str, user: str, session: str, agent_session: str,
                         viewer_session: str) -> bool:
        """Cross-worker lookup of an existing peer; a browser cannot borrow another user's video grant."""
        if (not self.available or not settings.DIRECT_TRANSPORT_INPUT_ENABLED
                or not settings.DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED
                or device not in settings.DIRECT_TRANSPORT_PROBE_DEVICE_IDS):
            return False
        async with asyncio.timeout(OPERATION_SECONDS):
            raw = await self.peer_binding(device, session)
            if not isinstance(raw, (str, bytes)) or len(raw) > MAX_WIRE_BYTES:
                return False
            try:
                binding = json.loads(raw)
                if (not isinstance(binding, dict)
                        or not {"session", "device", "org", "user", "worker", "agent_session", "media", "control_session"} <= binding.keys()
                        or binding.keys() - {"session", "device", "org", "user", "worker", "agent_session", "media", "control_session", "history_session", "shared"}
                        or "shared" in binding and binding["shared"] is not True
                        or binding != {**binding, "session": session, "device": device, "org": org, "user": user,
                                       "agent_session": agent_session, "media": LIVE_VIDEO_MODE, "control_session": viewer_session}):
                    return False
                session_id(binding["worker"])
            except (ValueError, TypeError):
                return False
            status = await DeviceStatusCache(self.redis).get_status(device)
            return bool(status and status.agent_version_code and status.agent_version_code >= 10254
                        and await self.remaining(binding))

    async def video_peer(self, *, device: str, org: str, user: str, session: str, viewer_session: str) -> bool:
        """The stream may retire only its own duplicate, never another viewer's.

        Read-only viewers bind through the existing history correlation nonce;
        this lookup grants no Android input or diagnostic command forwarding.
        """
        if (not self.available or not settings.DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED
                or device not in settings.DIRECT_TRANSPORT_PROBE_DEVICE_IDS):
            return False
        async with asyncio.timeout(OPERATION_SECONDS):
            raw = await self.peer_binding(device, session)
            if not isinstance(raw, (str, bytes)) or len(raw) > MAX_WIRE_BYTES:
                return False
            try:
                binding = json.loads(raw)
                required = {"session", "device", "org", "user", "worker", "agent_session", "media"}
                if (not isinstance(binding, dict) or not required <= binding.keys()
                        or binding.keys() - required - {"control_session", "history_session", "shared", "shared_control"}
                        or "shared" in binding and binding["shared"] is not True
                        or "shared_control" in binding and (binding["shared_control"] is not True or binding.get("shared") is not True)
                        or any(binding.get(k) != v for k, v in {
                            "session": session, "device": device, "org": org, "user": user, "media": LIVE_VIDEO_MODE,
                        }.items())
                        or binding.get("history_session") != viewer_session):
                    return False
                session_id(binding["worker"])
                session_id(binding["session"])
            except (ValueError, TypeError):
                return False
            status = await DeviceStatusCache(self.redis).get_status(device)
            return bool(status and status.agent_version_code
                        and status.agent_version_code >= LEGACY_HANDOVER_MIN_AGENT_CODE and await self.remaining(binding))

    async def legacy_video_required(self, device: str) -> bool:
        # NUMSUB is global across viewer workers. Presence is a different topic:
        # a direct-only worker keeps capture alive without subscribing to bytes.
        try:
            async with asyncio.timeout(.25):
                result = await self.redis.pubsub_numsub(ChannelPattern.video_stream(device))
                return bool(result[0][1])
        except Exception:
            return True  # Unknown demand never suppresses the recovery transport.

    async def publish(self, channel: str, data: dict) -> None:
        if await self.redis.publish(channel, self.encode(data)) < 1:
            raise InvalidDirectProbe("transport_unavailable")

    async def open(self, viewer: ProbeViewer, sdp: str) -> None:
        if viewer.reserving or viewer.retired:
            raise InvalidDirectProbe("probe_unavailable")
        if viewer.binding:
            if not self.available or self.viewers.get(viewer.session) is not viewer or viewer.offered:
                raise InvalidDirectProbe("probe_unavailable")
            description(sdp, video=viewer.video)
            async with asyncio.timeout(OPERATION_SECONDS):
                if not await self.remaining(viewer.binding):
                    raise InvalidDirectProbe("probe_expired")
                await self._publish_offer(viewer, sdp)
            return
        if not self.available or viewer.binding or len(self.viewers) + self.reservations >= MAX_PEERS:
            raise InvalidDirectProbe("probe_unavailable")
        description(sdp, video=viewer.video)
        self.reservations += 1
        viewer.reserving = True
        try:
            await self._open(viewer, sdp)
        except BaseException:
            await self.retire(viewer)
            raise
        finally:
            self.reservations -= 1
            viewer.reserving = False

    async def _open(self, viewer: ProbeViewer, sdp: str) -> None:
        await self._reserve(viewer)
        async with asyncio.timeout(OPERATION_SECONDS):
            await self._publish_offer(viewer, sdp)

    async def prepare(self, viewer: ProbeViewer) -> None:
        """Reserve the same global device lease BEFORE issuing relay credentials."""
        if not self.available or viewer.binding or viewer.reserving or viewer.retired or len(self.viewers) + self.reservations >= MAX_PEERS:
            raise InvalidDirectProbe("probe_unavailable")
        self.reservations += 1
        viewer.reserving = True
        try:
            await self._reserve(viewer)
            async with asyncio.timeout(OPERATION_SECONDS):
                # Survives socket close. Repeated connect/close cannot mint unlimited
                # 120-second relay credentials using the same device lease.
                if not await self.redis.set(f"{self.namespace}:relay-issued:{viewer.device}", "1", nx=True, px=15000):
                    raise InvalidDirectProbe("relay_grant_rate_limited")
                if not self.available or viewer.retired or self.viewers.get(viewer.session) is not viewer:
                    raise InvalidDirectProbe("probe_unavailable")
        except BaseException:
            await self.retire(viewer)
            raise
        finally:
            self.reservations -= 1
            viewer.reserving = False

    async def _reserve(self, viewer: ProbeViewer) -> None:
        async with asyncio.timeout(OPERATION_SECONDS):
            status = await DeviceStatusCache(self.redis).get_status(viewer.device)
            if not status or not status.ws_session_id or status.status not in {"online", "busy", "connecting"}:
                raise InvalidDirectProbe("agent_unavailable")
            if viewer.live and not viewer.video:
                raise InvalidDirectProbe("invalid_live_scope")
            admitted = settings.DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED if viewer.live else settings.DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED
            minimum = LIVE_VIDEO_MIN_AGENT_CODE if viewer.live else VIDEO_MIN_AGENT_CODE
            if viewer.video and (not admitted
                                 or viewer.device not in settings.DIRECT_TRANSPORT_PROBE_DEVICE_IDS
                                 or not status.agent_version_code or status.agent_version_code < minimum):
                raise InvalidDirectProbe("video_probe_not_admitted")
            viewer.session = secrets.token_hex(16)
            binding: dict[str, Any] = dict(session=viewer.session, device=viewer.device, org=viewer.org,
                                          user=viewer.user, worker=self.worker, agent_session=status.ws_session_id)
            if viewer.video:
                binding["media"] = LIVE_VIDEO_MODE if viewer.live else VIDEO_MODE
            if viewer.video and status.agent_version_code and status.agent_version_code >= SHARED_PEER_MIN_AGENT_CODE:
                binding["shared"] = True
            if viewer.shared_control:
                if not binding.get("shared") or not viewer.live or viewer.control_session is None:
                    raise InvalidDirectProbe("shared_input_not_admitted")
                binding["shared_control"] = True
            if viewer.control_session is not None:
                if (not viewer.live or not settings.DIRECT_TRANSPORT_INPUT_ENABLED
                        or not status.agent_version_code or status.agent_version_code < 10254
                        or not isinstance(viewer.control_session, str)
                        or len(viewer.control_session) != 16 or any(c not in "0123456789abcdef" for c in viewer.control_session)):
                    raise InvalidDirectProbe("input_peer_not_admitted")
                binding["control_session"] = viewer.control_session
            if viewer.history_session is not None:
                if (not viewer.video or not isinstance(viewer.history_session, str)
                        or len(viewer.history_session) != 16
                        or any(c not in "0123456789abcdef" for c in viewer.history_session)):
                    raise InvalidDirectProbe("invalid_history_session")
                # Diagnostic correlation is separate from input admission. The
                # journal independently verifies the authenticated user/record.
                binding["history_session"] = viewer.history_session
            acquired = (await self.shared.acquire(binding, self.encode(binding)) if binding.get("shared") else
                        await self.redis.set(self.key(viewer.device), self.encode(binding), nx=True, px=SESSION_MS))
            if not acquired:
                raise InvalidDirectProbe("device_probe_busy")
            viewer.binding = binding
            # stop/retire may run while Redis is accepting this reservation. Publish
            # no credentials or SDP for a retired socket, and release its exact lease.
            if not self.available or viewer.retired:
                await self.retire(viewer)
                raise InvalidDirectProbe("probe_unavailable")
            self.viewers[viewer.session] = viewer

    async def renew(self, viewer: ProbeViewer, sequence: int) -> None:
        """Extend only this authenticated, answered, still-current owner. No SDP replay."""
        now = asyncio.get_running_loop().time()
        if (type(sequence) is not int or sequence != viewer.renewal + 1 or sequence > 1000000
                or not viewer.live or not viewer.answered or viewer.retired or not self.available
                or self.viewers.get(viewer.session) is not viewer or not viewer.binding
                or viewer.renewed_at and now - viewer.renewed_at < 1):
            raise InvalidDirectProbe("invalid_video_renewal")
        async with asyncio.timeout(OPERATION_SECONDS):
            status = await DeviceStatusCache(self.redis).get_status(viewer.device)
            if (not settings.DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED
                    or viewer.device not in settings.DIRECT_TRANSPORT_PROBE_DEVICE_IDS
                    or not status or not status.agent_version_code or status.agent_version_code < LIVE_VIDEO_MIN_AGENT_CODE
                    or not await self.remaining(viewer.binding)
                    or not (await self.shared.renew(viewer.binding, self.encode(viewer.binding)) if viewer.binding.get("shared") else
                            await self.redis.eval(RENEW_EXACT, 1, self.key(viewer.device), self.encode(viewer.binding), SESSION_MS))):
                raise InvalidDirectProbe("video_renewal_rejected")
            viewer.renewal = sequence
            viewer.renewed_at = now
            await self.publish(f"{self.namespace}:agent:{viewer.device}",
                               dict(kind="renew", binding=viewer.binding, sequence=sequence))

    async def _publish_offer(self, viewer: ProbeViewer, sdp: str) -> None:
        if viewer.offered or viewer.retired or not self.available or not viewer.binding:
            raise InvalidDirectProbe("probe_already_offered")
        viewer.offered = True  # A publication failure must not enable replay.
        try:
            sdp = await resolve_offer(sdp, viewer.session)
            # The helper await cannot borrow a replaced/expired device owner.
            if (viewer.retired or not self.available or self.viewers.get(viewer.session) is not viewer
                    or not await self.remaining(viewer.binding)):
                raise InvalidDirectProbe("probe_expired")
            data = dict(kind="offer", binding=viewer.binding, sdp=sdp)
            if viewer.ice is not None:
                data["ice"] = validate_turn_grant(viewer.ice, viewer.session, "agent")
            await self.publish(f"{self.namespace}:agent:{viewer.device}", data)
        except BaseException:
            await self.retire(viewer)
            raise

    async def agent_message(self, device: str, agent_session: str, data: dict) -> None:
        if not isinstance(data, dict):
            raise InvalidDirectProbe("invalid_answer")
        sid = session_id(data.get("session_id"))
        pending = self.pending.get(sid)
        if not pending:
            return
        _, sdp = agent_answer(data, video=pending.binding.get("media") in {VIDEO_MODE, LIVE_VIDEO_MODE})
        binding, deadline = pending.binding, pending.deadline
        snapshot = self.manager.connection_snapshot(device)
        async with asyncio.timeout(OPERATION_SECONDS):
            if (not self.available or deadline <= asyncio.get_running_loop().time()
                    or binding["device"] != device or binding["agent_session"] != agent_session
                    or snapshot is None or snapshot.session_id != agent_session
                    or snapshot.org_id != binding["org"] or not await self.remaining(binding)):
                return
            # Keep the exact pending binding for close, but reject duplicate answers.
            if pending.answered:
                return
            pending.answered = True  # Before publication await; failure must not enable replay.
            await self.publish(f"{self.namespace}:viewer:{binding['worker']}",
                               dict(kind="answer", binding=binding, sdp=sdp))

    def observe_native(self, device: str, agent_session: str, data: Any) -> bool:
        """No Redis await in the agent's input/ACK receive loop; never replay telemetry."""
        parsed = native_peer_report(data)
        if parsed is None or not self.available:
            return False
        sid, sample = parsed
        pending = self.pending.get(sid)
        snapshot = self.manager.connection_snapshot(device)
        now = asyncio.get_running_loop().time()
        if (pending is None or pending.deadline <= now or pending.diagnostic_closed
                or pending.binding.get("history_session") is None
                or pending.binding["device"] != device or pending.binding["agent_session"] != agent_session
                or snapshot is None or snapshot.session_id != agent_session
                or snapshot.org_id != pending.binding["org"] or snapshot.agent_type != "android"
                or sample.sequence <= pending.diagnostic_sequence or sample.elapsed_ms < pending.diagnostic_elapsed):
            return False
        pending.diagnostic_sequence = sample.sequence
        pending.diagnostic_elapsed = sample.elapsed_ms
        if sample.kind == "final":
            pending.diagnostic_closed = True
        elif now - pending.diagnostic_at < .75:
            return False
        pending.diagnostic_at = now
        if self.diagnostics.full():
            return False
        self.diagnostics.put_nowait((pending, sample.model_dump() | {
            "peer_id": sid, "received_at": utc_now(),
        }))
        return True

    async def write_diagnostics(self) -> None:
        history = StreamSessionHistory(self.redis)
        while True:
            pending, sample = await self.diagnostics.get()
            try:
                binding = pending.binding
                # Drop queued observations after reconnect/retirement. Their
                # timestamp is reception time, never this later storage time.
                async with asyncio.timeout(OPERATION_SECONDS):
                    if (not self.available or self.pending.get(binding["session"]) is not pending
                            or not await self.remaining(binding)):
                        continue
                    if not self.available or self.pending.get(binding["session"]) is not pending:
                        continue
                    await history.native_direct(binding["org"], binding["device"], binding["history_session"],
                                                binding["user"], sample)
            except Exception:
                pass  # Optional journal failure cannot retire media or input.
            finally:
                self.diagnostics.task_done()

    async def route(self, channel: str, raw: bytes | str) -> None:
        if len(raw) > MAX_WIRE_BYTES:
            return
        data = json.loads(raw)
        if not isinstance(data, dict) or data.keys() not in ({"kind", "binding", "sdp"}, {"kind", "binding"}, {"kind", "binding", "sdp", "ice"}, {"kind", "binding", "sequence"}):
            return
        binding = data["binding"]
        binding_keys = {"session", "device", "org", "user", "worker", "agent_session"}
        if (not isinstance(binding, dict) or not binding_keys <= binding.keys()
                or binding.keys() - binding_keys - {"media", "control_session", "history_session", "shared", "shared_control"}
                or "shared" in binding and binding["shared"] is not True
                or "shared_control" in binding and (binding["shared_control"] is not True or binding.get("shared") is not True
                    or "control_session" not in binding or binding.get("media") != LIVE_VIDEO_MODE)
                or "media" in binding and binding["media"] not in {VIDEO_MODE, LIVE_VIDEO_MODE}):
            return
        if "control_session" in binding and (binding.get("media") != LIVE_VIDEO_MODE
                or not isinstance(binding["control_session"], str) or len(binding["control_session"]) != 16
                or any(c not in "0123456789abcdef" for c in binding["control_session"])):
            return
        if "history_session" in binding and (binding.get("media") not in {VIDEO_MODE, LIVE_VIDEO_MODE}
                or not isinstance(binding["history_session"], str) or len(binding["history_session"]) != 16
                or any(c not in "0123456789abcdef" for c in binding["history_session"])):
            return
        sid = session_id(binding["session"])
        session_id(binding["worker"])
        if channel == self.viewer_channel:
            viewer = self.viewers.get(sid)
            if (data["kind"] != "answer" or viewer is None or viewer.binding != binding or viewer.answered
                    or not await self.remaining(binding)):
                return
            sdp = description(data.get("sdp"), video=viewer.video, offer=False)
            try:
                async with asyncio.timeout(1):
                    await viewer.ws.send_json(dict(type="direct_probe_answer", session_id=sid, sdp=sdp))
            except Exception:
                # This socket failure must not poison the shared worker listener.
                await self.retire(viewer)
                try:
                    async with asyncio.timeout(.5):
                        await viewer.ws.close(code=1013, reason="probe_viewer_unavailable")
                except Exception:
                    pass
                return
            viewer.answered = True
            return
        if channel != f"{self.namespace}:agent:{binding['device']}":
            return
        snapshot = self.manager.connection_snapshot(binding["device"])
        if (snapshot is None or snapshot.session_id != binding["agent_session"]
                or snapshot.org_id != binding["org"] or snapshot.agent_type != "android"):
            return
        if data["kind"] == "close":
            pending = self.pending.get(sid)
            if pending and pending.binding == binding:
                self.pending.pop(sid, None)
                await self.manager.send_to_session(binding["device"], snapshot.session_id,
                                                   dict(type="direct_probe_close", session_id=sid))
            return
        if data["kind"] == "renew":
            pending = self.pending.get(sid)
            sequence = data.get("sequence")
            if (binding.get("media") != LIVE_VIDEO_MODE or not pending or not pending.answered
                    or pending.binding != binding or type(sequence) is not int or not 1 <= sequence <= 1000000):
                return
            status = await DeviceStatusCache(self.redis).get_status(binding["device"])
            if (not settings.DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED
                    or binding["device"] not in settings.DIRECT_TRANSPORT_PROBE_DEVICE_IDS
                    or not status or status.ws_session_id != binding["agent_session"]
                    or not status.agent_version_code or status.agent_version_code < LIVE_VIDEO_MIN_AGENT_CODE):
                return
            remaining = await self.remaining(binding)
            if not remaining:
                return
            pending.deadline = asyncio.get_running_loop().time() + remaining / 1000
            message = dict(type="direct_probe_renew", session_id=sid, sequence=sequence, ttl_ms=remaining)
            if status.agent_version_code >= LEGACY_HANDOVER_MIN_AGENT_CODE:
                message.update(legacy_video_enabled=await self.legacy_video_required(binding["device"]),
                               legacy_ttl_ms=min(remaining, 10000))
            await self.manager.send_to_session(binding["device"], snapshot.session_id, message)
            return
        if data["kind"] != "offer":
            return
        ice = validate_turn_grant(data["ice"], sid, "agent") if "ice" in data else None
        remaining = await self.remaining(binding)
        now = asyncio.get_running_loop().time()
        self.pending = {k: v for k, v in self.pending.items() if v.deadline > now}
        if not remaining or sid in self.pending or len(self.pending) >= MAX_PEERS:
            return
        live = binding.get("media") == LIVE_VIDEO_MODE
        video = binding.get("media") in {VIDEO_MODE, LIVE_VIDEO_MODE}
        if video:
            status = await DeviceStatusCache(self.redis).get_status(binding["device"])
            admitted = settings.DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED if live else settings.DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED
            minimum = LIVE_VIDEO_MIN_AGENT_CODE if live else VIDEO_MIN_AGENT_CODE
            if (not admitted
                    or binding["device"] not in settings.DIRECT_TRANSPORT_PROBE_DEVICE_IDS
                    or not status or status.ws_session_id != binding["agent_session"]
                    or not status.agent_version_code or status.agent_version_code < minimum):
                return
        sdp = description(data.get("sdp"), video=video)
        self.pending[sid] = PendingProbe(binding, now + remaining / 1000)
        message = dict(type="direct_probe_offer", session_id=sid, sdp=sdp, ttl_ms=remaining)
        if video:
            message["media"] = LIVE_VIDEO_MODE if live else VIDEO_MODE
        if binding.get("shared_control") is True:
            message["shared_control"] = True
        if ice is not None:
            message["ice"] = ice
        await self.manager.send_to_session(binding["device"], snapshot.session_id, message)

    async def retire(self, viewer: ProbeViewer) -> None:
        viewer.retired = True
        binding, viewer.binding = viewer.binding, None
        viewer.ice = None
        if self.viewers.get(viewer.session) is viewer:
            self.viewers.pop(viewer.session, None)
        if binding:
            try:
                async with asyncio.timeout(OPERATION_SECONDS):
                    # Close references an exact nonce; late close cannot retire a newer peer.
                    await self.publish(f"{self.namespace}:agent:{viewer.device}", dict(kind="close", binding=binding))
            except Exception:
                pass  # Native monotonic TTL still retires the peer.
            try:
                async with asyncio.timeout(OPERATION_SECONDS):
                    if binding.get("shared"):
                        await self.shared.release(binding, self.encode(binding))
                    else:
                        await self.redis.eval(DELETE_EXACT, 1, self.key(viewer.device), self.encode(binding))
            except Exception:
                pass  # Redis TTL bounds any orphan, never delete another owner.

    async def listen(self) -> None:
        try:
            while self.available:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if message and message["type"] in {"message", "pmessage"}:
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode("ascii")
                    try:
                        async with asyncio.timeout(OPERATION_SECONDS):
                            await self.route(channel, message["data"])
                    except (InvalidDirectProbe, ValueError, TypeError, KeyError, TimeoutError):
                        continue
        except asyncio.CancelledError:
            pass
        except Exception:
            self.available = False  # No reconnect/replay of obsolete SDP.
            for viewer in list(self.viewers.values()):
                await self.retire(viewer)
                try:
                    async with asyncio.timeout(OPERATION_SECONDS):
                        await viewer.ws.close(code=1013, reason="probe_transport_unavailable")
                except Exception:
                    pass

    async def stop(self) -> None:
        self.available = False
        if self.diagnostic_task:
            self.diagnostic_task.cancel()
            await asyncio.gather(self.diagnostic_task, return_exceptions=True)
        while not self.diagnostics.empty():
            self.diagnostics.get_nowait()
            self.diagnostics.task_done()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        for viewer in list(self.viewers.values()):
            await self.retire(viewer)
        self.pending.clear()
        if self.pubsub:
            await self.pubsub.aclose()
        await self.redis.aclose()


_runtime: DirectProbeRuntime | None = None


def get_direct_probe_runtime() -> DirectProbeRuntime | None:
    return _runtime


async def start_direct_probe_runtime(manager: ConnectionManager, url: str) -> None:
    global _runtime
    runtime = DirectProbeRuntime(no_replay_redis(url, decode_responses=False), manager)
    try:
        await runtime.start()
    except Exception:
        await runtime.stop()
        return
    _runtime = runtime


async def stop_direct_probe_runtime() -> None:
    global _runtime
    runtime, _runtime = _runtime, None
    if runtime:
        await runtime.stop()
