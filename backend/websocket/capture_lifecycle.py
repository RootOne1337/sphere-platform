"""Bounded read-only source admission; no media subscription or input grant."""
from __future__ import annotations

import asyncio

from backend.services.stream_quality import quality_rpc


async def await_capture_ready(device: str) -> dict:
    # A command-publication ACK is not source readiness. Read the APK's live
    # synchronized source snapshot; only inactive reads may be retried. Lost or
    # invalid RPC receipts fail closed. SV1 still binds the exact capture epoch
    # over DTLS before any observation/control can be admitted by the client.
    async with asyncio.timeout(10):
        for _ in range(40):
            snapshot = await quality_rpc(device, None)
            if not snapshot.supported:
                raise ValueError("capture_readiness_unsupported")
            if snapshot.active is not None:
                return {"width": snapshot.active.width, "height": snapshot.active.height}
            await asyncio.sleep(.25)
    raise TimeoutError("capture_start_deadline")
