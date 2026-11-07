"""One bounded attempt to the exact authenticated APK socket; no subscriptions.

Future canary routing calls this serially. It must not spawn a task per MOVE,
route through the ordinary command publisher or replay UNKNOWN outcomes.
"""
from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.continuous_lease import (
    OPERATION_SECONDS,
    ContinuousLeaseStore,
    InputLease,
    InputLeaseUnavailable,
)
from backend.websocket.continuous_observability import timed_stage
from backend.websocket.continuous_protocol import InvalidContinuousInput


class ContinuousDelivery(Enum):
    REJECTED = "rejected"
    SOCKET_SENT = "socket_sent"  # Not an injector ACK or a displayed frame.
    UNKNOWN = "unknown"


@timed_stage("agent_delivery")
async def deliver_continuous(store: ContinuousLeaseStore, manager: ConnectionManager,
                             device_id: str, envelope: Any) -> ContinuousDelivery:
    snapshot = manager.connection_snapshot(device_id)
    if snapshot is None or snapshot.agent_type != "android":
        return ContinuousDelivery.REJECTED
    # Copy immutable origin values before an await; ConnectionInfo itself is
    # an in-process object, not the authority supplied by a wire envelope.
    org_id, agent_session = snapshot.org_id, snapshot.session_id
    try:
        command = await store.delivery_command(envelope, device_id=device_id,
                                               org_id=org_id, agent_session=agent_session)
    except InputLeaseUnavailable:
        return ContinuousDelivery.UNKNOWN
    if command is None:
        return ContinuousDelivery.REJECTED
    try:
        async with asyncio.timeout(OPERATION_SECONDS):
            if await manager.send_to_session(device_id, agent_session, command):
                return ContinuousDelivery.SOCKET_SENT
    except asyncio.CancelledError:
        # Cancellation can happen after the socket consumed the write. Make
        # one bounded fence attempt, then preserve cancellation for the caller.
        try:
            await store.fence(InputLease.from_identity(envelope["identity"]))
        except (InputLeaseUnavailable, InvalidContinuousInput):
            pass
        raise
    except Exception:
        pass  # Never expose payloads/errors or retry an uncertain socket write.
    # A send may have been consumed before failure. Retire this owner, but do
    # not assert native cancellation or delete its lease. If Redis is also
    # unavailable, TTL and the independent APK watchdog still apply.
    try:
        await store.fence(InputLease.from_identity(envelope["identity"]))
    except (InputLeaseUnavailable, InvalidContinuousInput):
        pass
    return ContinuousDelivery.UNKNOWN
