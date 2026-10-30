"""Bound upload intake and keep filesystem work outside the HTTP event loop."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from starlette.requests import ClientDisconnect, Request

MAX_BODY_BYTES = 512 * 1024
RECEIVE_TIMEOUT_SECONDS = 60.0
CONCURRENT_UPLOADS = 4
_slots = threading.BoundedSemaphore(CONCURRENT_UPLOADS)
_executor = ThreadPoolExecutor(max_workers=CONCURRENT_UPLOADS, thread_name_prefix="sphere-log-upload")


class LogUploadBusy(Exception):
    pass


class LogUploadTooLarge(Exception):
    pass


class LogUploadInvalidBody(Exception):
    pass


class LogUploadTimeout(Exception):
    pass


class LogUploadUnavailable(Exception):
    pass


def _declared_length(request: Request) -> int | None:
    lengths = request.headers.getlist("content-length")
    if not lengths:
        return None
    if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
        raise LogUploadInvalidBody()
    normalized = lengths[0].lstrip("0") or "0"
    maximum = str(MAX_BODY_BYTES)
    # Compare decimal strings first: no unbounded/overflowing integer conversion.
    if len(normalized) > len(maximum) or (len(normalized) == len(maximum) and normalized > maximum):
        raise LogUploadTooLarge()
    return int(normalized)


async def _receive_body(request: Request) -> bytes:
    declared = _declared_length(request)
    body = bytearray()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RECEIVE_TIMEOUT_SECONDS
    try:
        async with asyncio.timeout(RECEIVE_TIMEOUT_SECONDS):
            async for chunk in request.stream():
                # Already-buffered ASGI chunks may not suspend for timeout delivery.
                if loop.time() >= deadline:
                    raise LogUploadTimeout()
                if len(chunk) > MAX_BODY_BYTES - len(body):
                    raise LogUploadTooLarge()
                body.extend(chunk)
    except TimeoutError as exc:
        raise LogUploadTimeout() from exc
    except ClientDisconnect as exc:
        raise LogUploadInvalidBody() from exc
    if declared is not None and declared != len(body):
        raise LogUploadInvalidBody()
    return bytes(body)


async def receive_and_store_log(request: Request, writer: Callable[[bytes], None]) -> None:
    slots = _slots
    if not slots.acquire(blocking=False):
        raise LogUploadBusy()
    delegated = False
    try:
        body = await _receive_body(request)
        context = copy_context()
        future = _executor.submit(context.run, writer, body)
        # An HTTP cancellation cannot release capacity while its writer still runs.
        future.add_done_callback(lambda completed: slots.release())
        delegated = True
        try:
            await asyncio.wrap_future(future)
        except OSError as exc:
            raise LogUploadUnavailable() from exc
    finally:
        if not delegated:
            slots.release()
