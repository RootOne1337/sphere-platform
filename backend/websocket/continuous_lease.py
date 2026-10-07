"""Single Redis authority for a *future* continuous-input canary.

No startup hook, public route, capability advertisement or offline queue.
Authorization is supplied by the caller after a fresh tenant/RBAC check.
Native readiness and known release require a receipt from the bound APK socket.
Redis/PubSub acceptance never means Android execution or browser rendering.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import asdict, dataclass
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from backend.websocket.continuous_protocol import (
    CaptureBinding,
    InputReceipt,
    InvalidContinuousInput,
    TouchEvent,
    identifier,
)

LEASE_MS = 1500
AUTH_MS = 1500
DELIVERY_MS = 500
MAX_WIRE_BYTES = 2048
OPERATION_SECONDS = 0.25


class InputLeaseUnavailable(RuntimeError):
    """Outcome may be unknown. The caller must retire locally, never replay."""

    def __init__(self) -> None:
        super().__init__("continuous_input_transport_unavailable")


def no_replay_redis(url: str) -> Redis:
    """Owned small pool. Do not borrow the application's retrying Redis client.

    Query parameters cannot override critical transport options. Redis URL
    parsing normally takes precedence over kwargs, so reject query options.
    """
    from urllib.parse import urlsplit

    if urlsplit(url).query:
        raise ValueError("Continuous input Redis URL cannot contain query options")
    return Redis.from_url(url, decode_responses=True, max_connections=8,
                          socket_timeout=OPERATION_SECONDS,
                          socket_connect_timeout=OPERATION_SECONDS,
                          retry=Retry(NoBackoff(), 0), retry_on_timeout=False,
                          retry_on_error=[], health_check_interval=0)


@dataclass(frozen=True)
class LeaseBinding:
    org: str
    device: str
    user: str
    viewer_worker: str
    viewer_session: str
    agent_session: str
    capture: CaptureBinding

    def __post_init__(self) -> None:
        for value in (self.org, self.device, self.user, self.viewer_worker,
                      self.viewer_session, self.agent_session):
            identifier(value)
        if not isinstance(self.capture, CaptureBinding):
            raise ValueError("Missing capture binding")


@dataclass(frozen=True)
class InputLease:
    owner: str
    binding: LeaseBinding

    def __post_init__(self) -> None:
        identifier(self.owner)
        if not isinstance(self.binding, LeaseBinding):
            raise ValueError("Missing lease binding")

    @property
    def identity(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_identity(cls, identity: Any) -> InputLease:
        if not isinstance(identity, str) or len(identity) > MAX_WIRE_BYTES:
            raise InvalidContinuousInput()
        try:
            raw = json.loads(identity)
            binding = raw["binding"]
            capture = binding["capture"]
            lease = cls(raw["owner"], LeaseBinding(**{**binding, "capture": CaptureBinding(**capture)}))
        except (ValueError, TypeError, KeyError, RecursionError):
            raise InvalidContinuousInput() from None
        if lease.identity != identity:
            raise InvalidContinuousInput()
        return lease


# A single static script, with explicit key and arguments. There is no script
# generation, EVALSHA fallback or retry loop that can repeat a publication.
_LEASE_SCRIPT = """
local key, op, identity = KEYS[1], ARGV[1], ARGV[2]
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local lease, auth, age = tonumber(ARGV[5]), tonumber(ARGV[6]), tonumber(ARGV[7])
if op == 'acquire' then
    if redis.call('EXISTS', key) ~= 0 then return 'busy' end
    redis.call('HSET', key, 'identity', identity, 'phase', 'opening',
               'auth_until', now + auth, 'sequence', 0,
               'held', 0, 'gesture', 0, 'last_gesture', 0)
    redis.call('PEXPIRE', key, lease)
    return 'acquired'
end
if redis.call('HGET', key, 'identity') ~= identity or redis.call('PTTL', key) <= 0 then
    return 'stale'
end
local phase = redis.call('HGET', key, 'phase')
if op == 'released' then redis.call('DEL', key); return 'released' end
if op == 'fence' then redis.call('HSET', key, 'phase', 'closing'); return 'fenced' end
if op == 'guard' then
    local envelope = cjson.decode(ARGV[3])
    local command = envelope.command
    if now >= envelope.expires_at_ms or envelope.expires_at_ms > now + age then return 'expired' end
    if command.type == 'continuous_input_close' then
        if phase == 'closing' then return 'admitted' end
        return 'stale'
    end
    if phase == 'closing' or now >= tonumber(redis.call('HGET', key, 'auth_until') or '0') then
        return 'stale'
    end
    if command.type == 'continuous_input_open' then
        if phase == 'opening_sent' or phase == 'ready' then return 'admitted' end
    elseif command.type == 'continuous_input_event' then
        if command.sequence <= tonumber(redis.call('HGET', key, 'sequence')) and
           (phase == 'ready' or (phase == 'opening_sent' and command.action == 4)) then
            return 'admitted'
        end
    end
    return 'stale'
end
if op == 'close' then
    if redis.call('HGET', key, 'close_sent') == '1' then return 'closing' end
    redis.call('HSET', key, 'phase', 'closing', 'close_sent', 1)
elseif phase == 'closing' then return 'closing'
elseif op == 'authorize' then
    redis.call('HSET', key, 'auth_until', now + auth)
    return 'authorized'
elseif now >= tonumber(redis.call('HGET', key, 'auth_until') or '0') then
    redis.call('HSET', key, 'phase', 'closing')
    return 'auth_expired'
elseif op == 'ready' then
    if phase ~= 'opening_sent' then return 'not_opening' end
    redis.call('HSET', key, 'phase', 'ready')
    return 'ready'
elseif op == 'open' then
    if phase ~= 'opening' then return 'already_sent' end
    redis.call('HSET', key, 'phase', 'opening_sent')
elseif op == 'event' then
    local event = cjson.decode(ARGV[3])
    if phase ~= 'ready' and not (phase == 'opening_sent' and event.action == 4) then
        return 'not_ready'
    end
    local sequence = tonumber(redis.call('HGET', key, 'sequence'))
    local held = redis.call('HGET', key, 'held') == '1'
    local gesture = tonumber(redis.call('HGET', key, 'gesture'))
    local last_gesture = tonumber(redis.call('HGET', key, 'last_gesture'))
    if event.sequence <= sequence or
       (event.action == 0 and (held or event.gesture <= last_gesture)) or
       (event.action == 4 and event.gesture ~= (held and gesture or 0)) or
       (event.action ~= 0 and event.action ~= 4 and (not held or event.gesture ~= gesture)) then
        redis.call('HSET', key, 'phase', 'closing')
        return 'invalid_order'
    end
    redis.call('HSET', key, 'sequence', event.sequence)
    if event.action == 0 then
        redis.call('HSET', key, 'held', 1, 'gesture', event.gesture, 'last_gesture', event.gesture)
    elseif event.action == 1 or event.action == 3 then
        redis.call('HSET', key, 'held', 0)
    end
else return 'invalid_operation' end
local envelope = {type='_continuous_input_v1', identity=identity,
                  expires_at_ms=now + age, command=cjson.decode(ARGV[3])}
local subscribers = redis.call('PUBLISH', ARGV[4], cjson.encode(envelope))
if subscribers < 1 then
    redis.call('HSET', key, 'phase', 'closing')
    return 'no_subscriber'
end
if op ~= 'close' then redis.call('PEXPIRE', key, lease) end
return 'published'
"""


class ContinuousLeaseStore:
    """Caller owns lifecycle, auth checks, WS tasks and pool closure.

    One short-lived hash per device, across tenants and workers. Missing Redis
    state is not proof of native reset; APK ownership/watchdog still applies.
    A supplied client is a test seam and must not be a production retrying pool.
    """

    def __init__(self, redis: Any, *, namespace: str = "input:continuous:v1") -> None:
        if not namespace or len(namespace) > 160 or not all(c.isascii() and (c.isalnum() or c in ":_-") for c in namespace):
            raise ValueError("Invalid continuous input namespace")
        if isinstance(redis, Redis):
            pool = redis.connection_pool
            options = pool.connection_kwargs
            timeout = options.get("socket_timeout")
            connect_timeout = options.get("socket_connect_timeout")
            if (getattr(options.get("retry"), "_retries", None) != 0
                    or options.get("retry_on_timeout", False)
                    or options.get("retry_on_error", [])
                    or not isinstance(timeout, (int, float)) or not 0 < timeout <= OPERATION_SECONDS
                    or not isinstance(connect_timeout, (int, float)) or not 0 < connect_timeout <= OPERATION_SECONDS
                    or not 1 <= pool.max_connections <= 8):
                raise ValueError("Continuous input requires a bounded non-retrying Redis pool")
        self.redis = redis
        self.namespace = namespace

    def key(self, binding: LeaseBinding) -> str:
        # Device is globally unique: re-tenanting cannot create two owners.
        return f"{self.namespace}:{{{binding.device}}}"

    def channel(self, binding: LeaseBinding) -> str:
        # Separate from offline/retrying legacy command routing.
        return f"{self.namespace}:agent:{binding.device}"

    async def _operation(self, op: str, lease: InputLease, command: dict | None = None) -> str:
        payload = json.dumps(command or {}, separators=(",", ":"))
        max_envelope = {"type": "_continuous_input_v1", "identity": lease.identity,
                        "expires_at_ms": 9_007_199_254_740_991, "command": command or {}}
        if len(json.dumps(max_envelope, separators=(",", ":")).encode()) > MAX_WIRE_BYTES:
            raise ValueError("Continuous input envelope exceeds byte budget")
        try:
            async with asyncio.timeout(OPERATION_SECONDS):
                result = await self.redis.eval(_LEASE_SCRIPT, 1, self.key(lease.binding),
                                               op, lease.identity, payload, self.channel(lease.binding),
                                               LEASE_MS, AUTH_MS, DELIVERY_MS)
        except (RedisError, TimeoutError):
            raise InputLeaseUnavailable() from None
        if isinstance(result, bytes):
            try:
                result = result.decode("ascii")
            except UnicodeDecodeError:
                raise InputLeaseUnavailable() from None
        if not isinstance(result, str) or result not in {"acquired", "busy", "stale", "released", "closing", "authorized",
                          "auth_expired", "not_opening", "ready", "already_sent", "not_ready",
                          "invalid_order", "invalid_operation", "no_subscriber", "published",
                          "admitted", "expired", "fenced"}:
            raise InputLeaseUnavailable()
        return result

    async def acquire(self, binding: LeaseBinding) -> InputLease | None:
        # Fresh authorization is a required caller precondition, not a browser claim.
        candidate = InputLease(secrets.token_hex(16), binding)
        return candidate if await self._operation("acquire", candidate) == "acquired" else None

    async def authorize(self, lease: InputLease) -> bool:
        """After a fresh permission check. Does NOT extend the browser/native lease."""
        return await self._operation("authorize", lease) == "authorized"

    async def open(self, lease: InputLease) -> str:
        capture = lease.binding.capture
        return await self._operation("open", lease, {
            "type": "continuous_input_open", "owner": lease.owner,
            "session_id": lease.binding.viewer_session, "capture_epoch": capture.epoch,
            "frame_width": capture.width, "frame_height": capture.height,
        })

    async def event(self, lease: InputLease, event: TouchEvent) -> str:
        if not event.inside(lease.binding.capture):
            raise ValueError("Point is outside the bound capture")
        return await self._operation("event", lease, {"type": "continuous_input_event",
            "owner": lease.owner, "capture_epoch": lease.binding.capture.epoch, **asdict(event)})

    async def close(self, lease: InputLease) -> str:
        # Revocation can close even after authorization expiry. Never renew/delete.
        return await self._operation("close", lease, {"type": "continuous_input_close", "owner": lease.owner})

    async def fence(self, lease: InputLease) -> None:
        """No publication or deletion. Unknown outcomes cannot enable another send."""
        await self._operation("fence", lease)

    async def delivery_command(self, envelope: Any, *, device_id: str, org_id: str,
                               agent_session: str) -> dict[str, Any] | None:
        """Receiver gate. Scope comes from its current ConnectionInfo, not JSON.

        Caller must use send_to_session with the same socket snapshot, bound
        its send, and never retry an uncertain result. This gate does not send.
        """
        try:
            if not isinstance(envelope, dict) or envelope.keys() != {"type", "identity", "expires_at_ms", "command"}:
                return None
            if envelope["type"] != "_continuous_input_v1":
                return None
            lease = InputLease.from_identity(envelope["identity"])
            binding = lease.binding
            if (device_id != binding.device or org_id != binding.org or agent_session != binding.agent_session):
                return None
            expires = envelope["expires_at_ms"]
            if type(expires) is not int or not 0 < expires <= 9_007_199_254_740_991:
                return None
            command = envelope["command"]
            if not isinstance(command, dict) or command.get("owner") != lease.owner:
                return None
            kind = command.get("type")
            if kind == "continuous_input_open":
                capture = binding.capture
                expected = {"type": kind, "owner": lease.owner, "session_id": binding.viewer_session,
                            "capture_epoch": capture.epoch, "frame_width": capture.width, "frame_height": capture.height}
                if command != expected or type(command.get("frame_width")) is not int or type(command.get("frame_height")) is not int:
                    return None
            elif kind == "continuous_input_event":
                if command.keys() != {"type", "owner", "capture_epoch", "sequence", "gesture", "action", "x", "y"} or command["capture_epoch"] != binding.capture.epoch:
                    return None
                event = TouchEvent(**{name: command[name] for name in ("sequence", "gesture", "action", "x", "y")})
                if not event.inside(binding.capture):
                    return None
            elif kind != "continuous_input_close" or command != {"type": kind, "owner": lease.owner}:
                return None
            if len(json.dumps(envelope, separators=(",", ":")).encode()) > MAX_WIRE_BYTES:
                return None
        except (InvalidContinuousInput, TypeError, ValueError, UnicodeError):
            return None
        return dict(command) if await self._operation("guard", lease, {
            "command": command, "expires_at_ms": expires,
        }) == "admitted" else None

    async def receipt(self, lease: InputLease, message: Any, *, agent_session: str) -> bool:
        """agent_session must come from the authenticated WS handler, never JSON."""
        receipt = InputReceipt.parse(message)
        if (agent_session != lease.binding.agent_session or receipt.session != lease.binding.viewer_session
                or receipt.owner != lease.owner or receipt.epoch != lease.binding.capture.epoch):
            return False
        if receipt.ready:
            return await self._operation("ready", lease) == "ready"
        if receipt.released:
            return await self._operation("released", lease) == "released"
        if receipt.failed:
            await self.fence(lease)
        return False  # Execution/unknown receipts do not grant readiness or release.
