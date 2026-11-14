"""Run bounded journal maintenance on the existing background lifecycle."""
from __future__ import annotations

import asyncio
import time

import structlog

from backend.core.lifespan_registry import register_shutdown, register_startup
from backend.services.device_log_storage import (
    DEVICE_LOG_ROOT,
    MAINTENANCE_INTERVAL_SECONDS,
    sweep_device_journals,
)
from backend.services.device_log_upload import (
    LogUploadBusy,
    LogUploadUnavailable,
    run_log_storage_write,
)

logger = structlog.get_logger()
_task: asyncio.Task[None] | None = None
_WARNING_INTERVAL_SECONDS = 900


async def _maintain_device_journals() -> None:
    next_warning = 0.0
    while True:
        # Leave startup I/O to the application and share the marker across workers.
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
        try:
            await run_log_storage_write(lambda: sweep_device_journals(DEVICE_LOG_ROOT))
        except LogUploadBusy:
            # A writer holding the storage lock also checks expiry.
            continue
        except LogUploadUnavailable:
            now = time.monotonic()
            if now >= next_warning:
                logger.warning("device_logs.retention_storage_unavailable")
                next_warning = now + _WARNING_INTERVAL_SECONDS


async def _start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_maintain_device_journals(), name="device_log_maintenance")


async def _stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        finally:
            _task = None


register_startup("device_log_maintenance", _start)
register_shutdown("device_log_maintenance", _stop)
