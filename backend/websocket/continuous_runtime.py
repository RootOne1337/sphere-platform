"""Bounded, transient live-touch routing across workers. Never offline/retry input."""
from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from typing import Any

from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.continuous_delivery import ContinuousDelivery, deliver_continuous
from backend.websocket.continuous_lease import (
    MAX_WIRE_BYTES,
    OPERATION_SECONDS,
    ContinuousLeaseStore,
    InputLease,
    InputLeaseUnavailable,
    LeaseBinding,
    no_replay_redis,
)
from backend.websocket.continuous_protocol import (
    CaptureBinding,
    CloseInput,
    InvalidContinuousInput,
    TouchEvent,
    identifier,
    viewer_continuous,
)
from backend.websocket.continuous_receipts import relay_native_receipt, viewer_receipt

MAX_VIEWERS = 64
OFFER_MS = 5000


@dataclass
class TouchViewer:
    device: str
    org: str
    user: str
    session: str
    ws: Any
    offer: dict | None = None
    lease: InputLease | None = None
    closing: bool = False


class ContinuousRuntime:
    def __init__(self, store: ContinuousLeaseStore, manager: ConnectionManager) -> None:
        self.store, self.manager = store, manager
        self.worker = secrets.token_hex(16)
        self.viewers: dict[str, TouchViewer] = {}
        self.probes: dict[str, dict] = {}
        self.pubsub: Any = None
        self.task: asyncio.Task | None = None
        self.available = False

    @property
    def viewer_channel(self) -> str:
        return f"{self.store.namespace}:viewer:{self.worker}"

    async def start(self) -> None:
        self.pubsub = self.store.redis.pubsub()
        async with asyncio.timeout(OPERATION_SECONDS):
            await self.pubsub.psubscribe(f"{self.store.namespace}:agent:*")
            await self.pubsub.subscribe(self.viewer_channel)
        self.available = True
        self.task = asyncio.create_task(self.listen())

    async def now(self) -> int:
        async with asyncio.timeout(OPERATION_SECONDS):
            sec, micro = await self.store.redis.time()
        return int(sec) * 1000 + int(micro) // 1000

    async def topology(self, device: str, session: str) -> bool:
        async with asyncio.timeout(OPERATION_SECONDS):
            status = await DeviceStatusCache(self.store.redis).get_status(device)
        return bool(status and status.ws_session_id == session and status.status in {"online", "busy", "connecting"})

    async def send(self, viewer: TouchViewer, data: dict) -> None:
        if self.viewers.get(viewer.session) is not viewer:
            return
        async with asyncio.timeout(OPERATION_SECONDS):
            await viewer.ws.send_json(data)

    async def publish(self, channel: str, data: dict) -> None:
        raw = json.dumps(data, separators=(",", ":"))
        if len(raw.encode()) > MAX_WIRE_BYTES:
            raise InvalidContinuousInput()
        async with asyncio.timeout(OPERATION_SECONDS):
            if await self.store.redis.publish(channel, raw) < 1:
                raise InputLeaseUnavailable()

    def register(self, viewer: TouchViewer) -> bool:
        if not self.available or len(self.viewers) >= MAX_VIEWERS:
            return False
        self.viewers[viewer.session] = viewer
        return True

    async def probe(self, viewer: TouchViewer) -> None:
        viewer.offer = None
        await self.publish(f"{self.store.namespace}:agent:{viewer.device}", {
            "type": "_continuous_probe_v1", "org": viewer.org, "device": viewer.device,
            "session": viewer.session, "worker": self.worker,
            "expires": await self.now() + OFFER_MS,
        })

    async def handle(self, viewer: TouchViewer, data: Any) -> None:
        if not self.available or self.viewers.get(viewer.session) is not viewer:
            raise InputLeaseUnavailable()
        if data == {"type": "touch_probe"}:
            if viewer.lease is not None:
                raise InvalidContinuousInput()
            await self.probe(viewer)
            return
        message = viewer_continuous(data)
        if isinstance(message, CaptureBinding):
            offer = viewer.offer
            if (viewer.lease or viewer.closing or not offer or offer["expires"] <= await self.now()
                    or message != CaptureBinding(offer["capture_epoch"], offer["frame_width"], offer["frame_height"])
                    or not await self.topology(viewer.device, offer["agent_session"])):
                raise InvalidContinuousInput()
            lease = await self.store.acquire(LeaseBinding(viewer.org, viewer.device, viewer.user,
                self.worker, viewer.session, offer["agent_session"], message))
            if lease is None:
                raise InvalidContinuousInput()
            viewer.lease = lease
            await self.send(viewer, {"type": "touch_session", "session_id": viewer.session,
                "owner": lease.owner, "capture_epoch": message.epoch,
                "frame_width": message.width, "frame_height": message.height})
            if await self.store.open(lease) != "published":
                raise InputLeaseUnavailable()
        elif isinstance(message, TouchEvent):
            if not viewer.lease or viewer.closing:
                raise InvalidContinuousInput()
            if await self.store.event(viewer.lease, message) != "published":
                raise InputLeaseUnavailable()
        elif isinstance(message, CloseInput):
            await self.retire(viewer)

    async def authorize(self, viewer: TouchViewer) -> bool:
        if not viewer.lease or viewer.closing:
            return True
        return (await self.topology(viewer.device, viewer.lease.binding.agent_session)
                and await self.store.authorize(viewer.lease))

    async def retire(self, viewer: TouchViewer) -> None:
        viewer.closing = viewer.lease is not None
        viewer.offer = None
        if viewer.lease:
            try:
                await self.store.close(viewer.lease)
            except (InputLeaseUnavailable, asyncio.CancelledError):
                pass  # Native watchdog applies; never claim known release or retry input.

    async def unregister(self, viewer: TouchViewer) -> None:
        await self.retire(viewer)
        if self.viewers.get(viewer.session) is viewer:
            self.viewers.pop(viewer.session)

    async def agent_message(self, device: str, session: str, data: dict) -> None:
        snapshot = self.manager.connection_snapshot(device)
        if (not self.available or snapshot is None or snapshot.session_id != session
                or not await self.topology(device, session)):
            return
        if data.get("type") == "continuous_input_status":
            await relay_native_receipt(self.store, self.manager, device, data, agent_session=session)
        elif data.get("type") == "continuous_input_offer":
            pending = self.probes.pop(data.get("session_id", ""), None)
            if not pending or pending["device"] != device or pending["agent_session"] != session:
                return
            expected = {"type", "session_id", "protocol_version", "injector_ready", "frame_protocol_version",
                "display_id", "max_pointers", "capture_epoch", "frame_width", "frame_height",
                "physical_width", "physical_height", "rotation"}
            if (data.keys() != expected or data["protocol_version"] != 1 or data["frame_protocol_version"] != 2
                    or data["injector_ready"] is not False or data["max_pointers"] != 1 or data["display_id"] != 0):
                return
            capture = CaptureBinding(data["capture_epoch"], data["frame_width"], data["frame_height"])
            await self.publish(f"{self.store.namespace}:viewer:{pending['worker']}", {
                "type": "_continuous_offer_v1", **pending,
                "capture_epoch": capture.epoch, "frame_width": capture.width, "frame_height": capture.height,
            })

    async def route(self, channel: str, raw: bytes | str) -> None:
        if len(raw) > MAX_WIRE_BYTES:
            return
        data = json.loads(raw)
        if not isinstance(data, dict):
            return
        if channel == self.viewer_channel:
            if data.get("type") == "_continuous_offer_v1":
                if data.keys() != {"type", "org", "device", "session", "worker", "expires", "agent_session",
                        "capture_epoch", "frame_width", "frame_height"}:
                    return
                viewer = self.viewers.get(data["session"])
                if (viewer is None or viewer.lease or data["worker"] != self.worker
                        or data["org"] != viewer.org or data["device"] != viewer.device
                        or not await self.valid_expiry(data["expires"], OFFER_MS)
                        or not await self.topology(viewer.device, data["agent_session"])):
                    return
                CaptureBinding(data["capture_epoch"], data["frame_width"], data["frame_height"])
                viewer.offer = data
                await self.send(viewer, {"type": "touch_capability", "capture_epoch": data["capture_epoch"],
                    "frame_width": data["frame_width"], "frame_height": data["frame_height"]})
                return
            if data.get("type") == "_continuous_receipt_v1":
                identity = InputLease.from_identity(data.get("identity"))
                viewer = self.viewers.get(identity.binding.viewer_session)
                if viewer is None or viewer.lease != identity:
                    return
                receipt = await viewer_receipt(self.store, identity, data, viewer_worker=self.worker)
                if receipt:
                    if receipt["stage"] == "startup" and not await self.topology(viewer.device, identity.binding.agent_session):
                        await self.retire(viewer)
                        return
                    await self.send(viewer, receipt)
                    if receipt["stage"] == "release" and receipt["status"] == 3:
                        viewer.lease = None
                        viewer.offer = None
                        viewer.closing = False
                return
        prefix = f"{self.store.namespace}:agent:"
        if not channel.startswith(prefix):
            return
        device = channel.removeprefix(prefix)
        snapshot = self.manager.connection_snapshot(device)
        if snapshot is None or snapshot.agent_type != "android":
            return
        if data.get("type") == "_continuous_probe_v1":
            if data.keys() != {"type", "org", "device", "session", "worker", "expires"}:
                return
            if (data["device"] != device or data["org"] != snapshot.org_id
                    or not await self.valid_expiry(data["expires"], OFFER_MS)
                    or not await self.topology(device, snapshot.session_id)):
                return
            identifier(data["session"])
            identifier(data["worker"])
            now = await self.now()
            self.probes = {k: v for k, v in self.probes.items() if v["expires"] > now}
            if len(self.probes) >= MAX_VIEWERS:
                return
            pending = {k: v for k, v in data.items() if k != "type"} | {"agent_session": snapshot.session_id}
            self.probes[data["session"]] = pending
            async with asyncio.timeout(OPERATION_SECONDS):
                await self.manager.send_to_session(device, snapshot.session_id,
                    {"type": "continuous_input_probe", "session_id": data["session"]})
        elif data.get("type") == "_continuous_input_v1":
            if not await self.topology(device, snapshot.session_id):
                return
            result = await deliver_continuous(self.store, self.manager, device, data)
            if result is not ContinuousDelivery.SOCKET_SENT:
                lease = InputLease.from_identity(data.get("identity"))
                await self.store.fence(lease)

    async def valid_expiry(self, expires: Any, limit: int) -> bool:
        now = await self.now()
        return type(expires) is int and now < expires <= now + limit

    async def listen(self) -> None:
        try:
            while self.available:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if message and message["type"] in {"message", "pmessage"}:
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode("ascii")
                    try:
                        await self.route(channel, message["data"])
                    except (InvalidContinuousInput, ValueError, TypeError, KeyError):
                        continue
        except asyncio.CancelledError:
            pass
        except Exception:
            # No resubscribe/replay with stale owners. Video remains independent.
            self.available = False
            for viewer in list(self.viewers.values()):
                await self.retire(viewer)
                try:
                    await self.send(viewer, {"type": "touch_error", "error": "transport_unavailable"})
                except Exception:
                    pass

    async def stop(self) -> None:
        for viewer in list(self.viewers.values()):
            await self.retire(viewer)
        self.available = False
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.pubsub:
            await self.pubsub.aclose()
        self.viewers.clear()
        self.probes.clear()
        await self.store.redis.aclose()


_runtime: ContinuousRuntime | None = None


def get_continuous_runtime() -> ContinuousRuntime | None:
    return _runtime


async def start_continuous_runtime(manager: ConnectionManager, url: str) -> None:
    global _runtime
    runtime = ContinuousRuntime(ContinuousLeaseStore(no_replay_redis(url, decode_responses=False)), manager)
    try:
        await runtime.start()
    except Exception:
        await runtime.stop()
        return  # A failed experimental transport must not prevent video startup.
    _runtime = runtime


async def stop_continuous_runtime() -> None:
    global _runtime
    runtime, _runtime = _runtime, None
    if runtime:
        await runtime.stop()
