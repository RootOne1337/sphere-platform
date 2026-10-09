"""Ephemeral, generation-bound SDP routing. No offline queue or signal replay."""
from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from typing import Any

from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.continuous_lease import no_replay_redis
from backend.websocket.direct_probe_protocol import (
    MAX_PEERS,
    MAX_WIRE_BYTES,
    SESSION_MS,
    InvalidDirectProbe,
    agent_answer,
    description,
    session_id,
)

OPERATION_SECONDS = 2.0
DELETE_EXACT = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"
REMAINING_EXACT = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('PTTL', KEYS[1]) else return 0 end"


@dataclass
class ProbeViewer:
    device: str
    org: str
    user: str
    ws: Any
    session: str = ""
    binding: dict | None = None
    answered: bool = False


@dataclass
class PendingProbe:
    binding: dict
    deadline: float
    answered: bool = False


class DirectProbeRuntime:
    def __init__(self, redis: Any, manager: ConnectionManager, namespace: str = "sphere:direct-probe:v1") -> None:
        self.redis, self.manager, self.namespace = redis, manager, namespace
        self.worker = secrets.token_hex(16)
        self.viewers: dict[str, ProbeViewer] = {}
        self.pending: dict[str, PendingProbe] = {}
        self.available = False
        self.pubsub: Any = None
        self.task: asyncio.Task | None = None
        self.reservations = 0

    @property
    def viewer_channel(self) -> str:
        return f"{self.namespace}:viewer:{self.worker}"

    def key(self, device: str) -> str:
        return f"{self.namespace}:lease:{device}"

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

    async def topology(self, binding: dict) -> bool:
        status = await DeviceStatusCache(self.redis).get_status(binding["device"])
        return bool(status and status.ws_session_id == binding["agent_session"]
                    and status.status in {"online", "busy", "connecting"})

    async def remaining(self, binding: dict) -> int:
        if not await self.topology(binding):
            return 0
        # GET + PTTL must be atomic: an expired owner's GET cannot borrow a newer owner's TTL.
        ttl = await self.redis.eval(REMAINING_EXACT, 1, self.key(binding["device"]), self.encode(binding))
        return ttl if 0 < ttl <= SESSION_MS else 0

    async def publish(self, channel: str, data: dict) -> None:
        if await self.redis.publish(channel, self.encode(data)) < 1:
            raise InvalidDirectProbe("transport_unavailable")

    async def open(self, viewer: ProbeViewer, sdp: str) -> None:
        if not self.available or viewer.binding or len(self.viewers) + self.reservations >= MAX_PEERS:
            raise InvalidDirectProbe("probe_unavailable")
        description(sdp)
        self.reservations += 1
        try:
            await self._open(viewer, sdp)
        finally:
            self.reservations -= 1

    async def _open(self, viewer: ProbeViewer, sdp: str) -> None:
        async with asyncio.timeout(OPERATION_SECONDS):
            status = await DeviceStatusCache(self.redis).get_status(viewer.device)
            if not status or not status.ws_session_id or status.status not in {"online", "busy", "connecting"}:
                raise InvalidDirectProbe("agent_unavailable")
            viewer.session = secrets.token_hex(16)
            binding = dict(session=viewer.session, device=viewer.device, org=viewer.org,
                           user=viewer.user, worker=self.worker, agent_session=status.ws_session_id)
            if not await self.redis.set(self.key(viewer.device), self.encode(binding), nx=True, px=SESSION_MS):
                raise InvalidDirectProbe("device_probe_busy")
            viewer.binding = binding
            self.viewers[viewer.session] = viewer
            try:
                await self.publish(f"{self.namespace}:agent:{viewer.device}",
                                   dict(kind="offer", binding=binding, sdp=sdp))
            except BaseException:
                await self.retire(viewer)
                raise

    async def agent_message(self, device: str, agent_session: str, data: dict) -> None:
        sid, sdp = agent_answer(data)
        pending = self.pending.get(sid)
        if not pending:
            return
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

    async def route(self, channel: str, raw: bytes | str) -> None:
        if len(raw) > MAX_WIRE_BYTES:
            return
        data = json.loads(raw)
        if not isinstance(data, dict) or data.keys() not in ({"kind", "binding", "sdp"}, {"kind", "binding"}):
            return
        binding = data["binding"]
        if not isinstance(binding, dict) or binding.keys() != {"session", "device", "org", "user", "worker", "agent_session"}:
            return
        sid = session_id(binding["session"])
        session_id(binding["worker"])
        if channel == self.viewer_channel:
            viewer = self.viewers.get(sid)
            if (data["kind"] != "answer" or viewer is None or viewer.binding != binding or viewer.answered
                    or not await self.remaining(binding)):
                return
            sdp = description(data.get("sdp"))
            await viewer.ws.send_json(dict(type="direct_probe_answer", session_id=sid, sdp=sdp))
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
        if data["kind"] != "offer":
            return
        remaining = await self.remaining(binding)
        now = asyncio.get_running_loop().time()
        self.pending = {k: v for k, v in self.pending.items() if v.deadline > now}
        if not remaining or sid in self.pending or len(self.pending) >= MAX_PEERS:
            return
        sdp = description(data.get("sdp"))
        self.pending[sid] = PendingProbe(binding, now + remaining / 1000)
        await self.manager.send_to_session(binding["device"], snapshot.session_id,
                                          dict(type="direct_probe_offer", session_id=sid, sdp=sdp, ttl_ms=remaining))

    async def retire(self, viewer: ProbeViewer) -> None:
        binding, viewer.binding = viewer.binding, None
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
                    except (InvalidDirectProbe, ValueError, TypeError, KeyError):
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
