"""Fixed-cardinality inclusive timings; no payload, IDs, per-event log or queue.

These spans measure local coroutine execution, including its awaits. They do
not measure time waiting in Pub/Sub before dispatch, APK/native execution or
browser receipt. Nested spans must not be added as independent latency phases.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from backend.metrics import continuous_stage_duration_seconds

STAGES = frozenset({
    "viewer_admission", "redis_lease_operation", "pubsub_dispatch",
    "agent_delivery", "agent_reply_relay", "viewer_receipt_validation", "viewer_socket_send",
})
OUTCOMES = frozenset({"returned", "raised", "cancelled"})
P = ParamSpec("P")
R = TypeVar("R")


def _clock() -> float | None:
    try:
        value = time.monotonic()
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _observe(stage: str, outcome: str, start: float | None) -> None:
    # Instrumentation failure must not alter native ownership, return values,
    # exceptions or cancellation. Do not log metric errors on the hot path.
    try:
        end = _clock()
        if start is None or end is None or end < start:
            return
        duration = end - start
        if math.isfinite(duration):
            continuous_stage_duration_seconds.labels(stage=stage, outcome=outcome).observe(duration)
    except Exception:
        pass


def timed_stage(stage: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Names are source-defined; wire values never become metric labels.

    Returned means only that the coroutine returned, including rejected or
    unknown results. It must never be interpreted as an Android ACK.
    """
    if stage not in STAGES:
        raise ValueError("Unknown continuous timing stage")

    def decorate(operation: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(operation)
        async def measured(*args: P.args, **kwargs: P.kwargs) -> R:
            start = _clock()
            outcome = "returned"
            try:
                return await operation(*args, **kwargs)
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except BaseException:
                outcome = "raised"
                raise
            finally:
                _observe(stage, outcome, start)

        return measured

    return decorate
