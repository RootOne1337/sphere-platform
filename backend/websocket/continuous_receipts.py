"""Scoped transient receipt boundary. No startup hook/subscription/public route.

The native handler supplies its authenticated socket session. The receiving
worker supplies its own ID and exact locally-owned InputLease. Pub/Sub receipt
publication is not proof that the viewer received it; missing delivery fences
readiness without replay. No org-wide broadcast, persistent queue or callback
registry is introduced here.
"""
from __future__ import annotations

import asyncio
import json
from enum import StrEnum
from typing import Any

from redis.exceptions import RedisError

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.continuous_lease import (
    DELIVERY_MS,
    MAX_WIRE_BYTES,
    OPERATION_SECONDS,
    ContinuousLeaseStore,
    InputLease,
    InputLeaseUnavailable,
)
from backend.websocket.continuous_protocol import InputReceipt, InvalidContinuousInput


class ReceiptRelay(StrEnum):
    REJECTED = "rejected"
    PUBLISHED = "published"  # Neither browser delivery nor rendered output.
    UNKNOWN = "unknown"


async def relay_native_receipt(store: ContinuousLeaseStore, manager: ConnectionManager,
                               device_id: str, message: Any, *, agent_session: str) -> ReceiptRelay:
    """Never use session_id from JSON as socket identity or choose its tenant."""
    snapshot = manager.connection_snapshot(device_id)
    if (snapshot is None or snapshot.agent_type != "android" or snapshot.session_id != agent_session
            or snapshot.device_id != device_id):
        return ReceiptRelay.REJECTED
    org_id = snapshot.org_id  # Copy before yielding; ConnectionInfo is mutable.
    try:
        InputReceipt.parse(message)
    except (InvalidContinuousInput, TypeError, ValueError):
        return ReceiptRelay.REJECTED
    lease = None
    try:
        lease = await store.current_lease(device_id=device_id, org_id=org_id, agent_session=agent_session)
        current = manager.connection_snapshot(device_id)
        if (lease is None or current is not snapshot or current.org_id != org_id or current.session_id != agent_session
                or current.agent_type != "android" or current.device_id != device_id):
            return ReceiptRelay.REJECTED
        result = await store.relay_receipt(lease, message, agent_session=agent_session)
        return ReceiptRelay.PUBLISHED if result == "relayed" else ReceiptRelay.REJECTED
    except asyncio.CancelledError:
        if lease is not None:
            await _fence_once(store, lease)
        raise
    except InputLeaseUnavailable:
        if lease is not None:
            await _fence_once(store, lease)
        return ReceiptRelay.UNKNOWN


async def _fence_once(store: ContinuousLeaseStore, lease: InputLease) -> None:
    try:
        await store.fence(lease)
    except (InputLeaseUnavailable, asyncio.CancelledError):
        pass  # Repeated cancellation/outage may prevent fencing; TTL/native watchdog remain required.


async def viewer_receipt(store: ContinuousLeaseStore, lease: InputLease, envelope: Any,
                         *, viewer_worker: str) -> dict[str, Any] | None:
    """One scoped reply. Caller still owns current auth/WS/callback lifetime.

    Known RELEASE deletes the device key before publication; validate against
    the exact local lease instead of reconstructing a new owner from Redis.
    This never opens a session or looks up a different callback on failure.
    """
    if viewer_worker != lease.binding.viewer_worker:
        return None
    try:
        if isinstance(envelope, (str, bytes)):
            if len(envelope.encode() if isinstance(envelope, str) else envelope) > MAX_WIRE_BYTES:
                return None
            envelope = json.loads(envelope)
        if not isinstance(envelope, dict) or envelope.keys() != {"type", "identity", "expires_at_ms", "receipt_json"}:
            return None
        if envelope["type"] != "_continuous_receipt_v1" or envelope["identity"] != lease.identity:
            return None
        expires = envelope["expires_at_ms"]
        if type(expires) is not int or not 0 < expires <= 9_007_199_254_740_991:
            return None
        raw_receipt = envelope["receipt_json"]
        if not isinstance(raw_receipt, str) or len(raw_receipt.encode()) > MAX_WIRE_BYTES:
            return None
        payload = json.loads(raw_receipt)
        if not isinstance(payload, dict) or payload.keys() != {"receipt"}:
            return None
        message = payload["receipt"]
        receipt = InputReceipt.parse(message)
        if (receipt.session != lease.binding.viewer_session or receipt.owner != lease.owner
                or receipt.epoch != lease.binding.capture.epoch):
            return None
        if len(json.dumps(envelope, separators=(",", ":")).encode()) > MAX_WIRE_BYTES:
            return None
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return None
    try:
        async with asyncio.timeout(OPERATION_SECONDS):
            seconds, micros = await store.redis.time()
            now = int(seconds) * 1000 + int(micros) // 1000
    except (RedisError, TimeoutError, UnicodeError, ValueError, TypeError):
        raise InputLeaseUnavailable() from None
    if expires <= now or expires > now + DELIVERY_MS:
        return None
    return dict(message)
