"""Bound upload intake and keep filesystem work outside the HTTP event loop."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
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


class LogOwnershipLookupRequired(Exception):
    def __init__(self, directory_keys: frozenset[str]) -> None:
        self.directory_keys = directory_keys
        super().__init__("Legacy journal ownership requires lookup")


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


async def _run_with_storage_slot(
    writer: Callable[..., None], request: Request | None = None,
    resolve_legacy: Callable[[frozenset[str]], Awaitable[None]] | None = None,
) -> None:
    slots = _slots
    if not slots.acquire(blocking=False):
        raise LogUploadBusy()
    future: Future[None] | None = None
    try:
        args = () if request is None else (await _receive_body(request),)
        future = _executor.submit(copy_context().run, writer, *args)
        try:
            await asyncio.wrap_future(future)
        except LogOwnershipLookupRequired as exc:
            if resolve_legacy is None:
                raise LogUploadUnavailable() from exc
            await resolve_legacy(exc.directory_keys)
            future = _executor.submit(copy_context().run, writer, *args)
            try:
                await asyncio.wrap_future(future)
            except LogOwnershipLookupRequired as raced:
                # A concurrent restore or legacy writer changed the catalog.
                raise LogUploadBusy() from raced
    except OSError as exc:
        raise LogUploadUnavailable() from exc
    finally:
        if future is None:
            slots.release()
        else:
            # Cancellation cannot release capacity while a writer still runs.
            future.add_done_callback(lambda completed: slots.release())


async def receive_and_store_log(
    request: Request, writer: Callable[[bytes], None],
    *, resolve_legacy: Callable[[frozenset[str]], Awaitable[None]] | None = None,
) -> None:
    await _run_with_storage_slot(writer, request, resolve_legacy)


async def run_log_storage_write(writer: Callable[[], None]) -> None:
    await _run_with_storage_slot(writer)
