"""Bounded browser transfers for an Android agent's dedicated workspace."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import LockNotOwnedError, RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_tenant_db, require_permission
from backend.database.redis_client import get_redis_binary
from backend.models.device import Device
from backend.models.user import User
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.pubsub_router import get_pubsub_publisher

router = APIRouter(prefix="/devices", tags=["device-files"])

MAX_BYTES = 256 * 1024
MAX_FILES = 100
MAX_ENCODED_BYTES = (MAX_BYTES + 2) // 3 * 4
TIMEOUT = 12
BINARY_TYPE = "application/octet-stream"
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$"
SHA_PATTERN = r"^[0-9a-f]{64}$"
FileName = Annotated[str, Field(pattern=NAME_PATTERN, max_length=120)]
Digest = Annotated[str, Field(pattern=SHA_PATTERN)]
ERROR_CODES = {
    "file_exists": 409,
    "file_not_found": 404,
    "file_quota_exceeded": 507,
    "file_too_large": 413,
    "file_invalid_name": 422,
    "file_integrity_failed": 502,
    "file_exchange_busy": 409,
    "file_exchange_failed": 502,
}


class FileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: FileName
    size: int = Field(ge=0, le=MAX_BYTES)
    modified_at_ms: int = Field(ge=0, le=2**53 - 1)


class FileDirectory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    max_bytes: Literal[262144]
    files: list[FileEntry] = Field(max_length=MAX_FILES)


class FileReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: FileName
    size: int = Field(ge=0, le=MAX_BYTES)
    sha256: Digest


class FileDownload(FileReceipt):
    data: str = Field(max_length=MAX_ENCODED_BYTES)


def checked_name(name: str) -> str:
    if re.fullmatch(NAME_PATTERN, name) is None or name.endswith((".", " ")):
        raise HTTPException(422, "file_invalid_name")
    return name


async def active_target(device_id: uuid.UUID, db: AsyncSession, user: User, redis) -> str:
    owned = await db.scalar(select(Device.id).where(
        Device.id == device_id, Device.org_id == user.org_id, Device.is_active.is_(True),
    ))
    if owned is None:
        raise HTTPException(404, "Device not found")
    # Release the DB connection before receiving bytes or waiting on the agent.
    await db.commit()
    try:
        status = await DeviceStatusCache(redis).get_status(str(device_id))
    except RedisError:
        raise HTTPException(503, "file_exchange_failed") from None
    if status is None or not status.has_fresh_presence(datetime.now(timezone.utc)):
        raise HTTPException(409, "file_exchange_offline")
    if status.file_exchange_version != 1 or not status.ws_session_id:
        raise HTTPException(409, "file_exchange_unsupported")
    return status.ws_session_id


async def command(device_id: uuid.UUID, session_id: str, redis, payload: dict) -> dict:
    publisher = get_pubsub_publisher()
    if publisher is None:
        raise HTTPException(503, "file_exchange_failed")
    lock = redis.lock(f"sphere:device-files:lock:{device_id}", timeout=TIMEOUT + 4, blocking=False)
    try:
        if not await lock.acquire(blocking=False):
            raise HTTPException(409, "file_exchange_busy")
    except RedisError:
        raise HTTPException(503, "file_exchange_failed") from None
    try:
        command_id = f"interactive_{uuid.uuid4()}"
        result = await publisher.send_command_wait_result(str(device_id), {
            "type": "FILE_EXCHANGE", "command_id": command_id, "payload": payload,
            "signed_at": int(time.time()), "ttl_seconds": TIMEOUT,
            "_target_agent_session": session_id,
        }, timeout=TIMEOUT, live_only=True)
    except HTTPException as exc:
        if exc.status_code == 504:
            raise HTTPException(504, "file_exchange_unknown") from None
        if exc.status_code == 503:
            raise HTTPException(409, "file_exchange_offline") from None
        raise
    except (RedisError, ValueError, TypeError):
        code = "file_exchange_unknown" if payload["action"] == "write" else "file_exchange_failed"
        raise HTTPException(502, code) from None
    finally:
        try:
            await lock.release()
        except (RedisError, LockNotOwnedError):
            pass  # The lease expires even if Redis is unavailable after dispatch.
    if not isinstance(result, dict):
        raise HTTPException(502, "file_exchange_unknown" if payload["action"] == "write" else "file_exchange_failed")
    if result.get("status") == "failed":
        reason = result.get("error")
        if isinstance(reason, str) and reason in ERROR_CODES:
            raise HTTPException(ERROR_CODES[reason], reason)
    value = result.get("result")
    if result.get("status") != "completed" or not isinstance(value, dict):
        raise HTTPException(502, "file_exchange_unknown" if payload["action"] == "write" else "file_exchange_failed")
    return value


@router.get("/{device_id}/files", response_model=FileDirectory)
async def list_files(
    device_id: uuid.UUID, response: Response, user: User = require_permission("device:write"),
    db: AsyncSession = Depends(get_tenant_db), redis=Depends(get_redis_binary),
) -> FileDirectory:
    session = await active_target(device_id, db, user, redis)
    try:
        directory = FileDirectory.model_validate(await command(device_id, session, redis, {"action": "list"}))
        names = [file.name for file in directory.files]
        if len(names) != len(set(names)) or any(name.endswith((".", " ")) for name in names):
            raise ValueError("Duplicate files")
    except ValueError:
        raise HTTPException(502, "file_exchange_failed") from None
    response.headers["Cache-Control"] = "private, no-store"
    return directory


@router.get(
    "/{device_id}/files/{name}", response_class=Response,
    responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def download_file(
    device_id: uuid.UUID, name: str, user: User = require_permission("device:write"),
    db: AsyncSession = Depends(get_tenant_db), redis=Depends(get_redis_binary),
) -> Response:
    checked_name(name)
    session = await active_target(device_id, db, user, redis)
    try:
        file = FileDownload.model_validate(await command(device_id, session, redis, {"action": "read", "name": name}))
        contents = base64.b64decode(file.data, validate=True)
        if (file.name != name or len(contents) != file.size
                or hashlib.sha256(contents).hexdigest() != file.sha256):
            raise ValueError("File mismatch")
    except ValueError:
        raise HTTPException(502, "file_integrity_failed") from None
    return Response(contents, media_type=BINARY_TYPE, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Content-SHA256": file.sha256,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })


@router.post(
    "/{device_id}/files/{name}", response_model=FileReceipt, status_code=201,
    openapi_extra={"requestBody": {"required": True, "content": {
        "application/octet-stream": {"schema": {"type": "string", "format": "binary", "maxLength": MAX_BYTES}},
    }}},
)
async def upload_file(
    device_id: uuid.UUID, name: str, request: Request, response: Response,
    user: User = require_permission("device:write"),
    db: AsyncSession = Depends(get_tenant_db), redis=Depends(get_redis_binary),
) -> FileReceipt:
    checked_name(name)
    if request.headers.get("content-type") != BINARY_TYPE or request.headers.get("content-encoding"):
        raise HTTPException(415, "file_exchange_failed")
    digest = request.headers.get("x-content-sha256", "")
    if re.fullmatch(SHA_PATTERN, digest) is None:
        raise HTTPException(422, "file_integrity_failed")
    length = request.headers.get("content-length")
    if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 9):
        raise HTTPException(413, "file_too_large")
    if length is not None and int(length) > MAX_BYTES:
        raise HTTPException(413, "file_too_large")
    session = await active_target(device_id, db, user, redis)
    contents = bytearray()
    try:
        async with asyncio.timeout(TIMEOUT):
            async for chunk in request.stream():
                if len(contents) + len(chunk) > MAX_BYTES:
                    raise HTTPException(413, "file_too_large")
                contents.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "file_exchange_failed") from None
    if hashlib.sha256(contents).hexdigest() != digest:
        raise HTTPException(422, "file_integrity_failed")
    try:
        receipt = FileReceipt.model_validate(await command(device_id, session, redis, {
            "action": "write", "name": name, "data": base64.b64encode(contents).decode("ascii"), "sha256": digest,
        }))
        if (receipt.name, receipt.size, receipt.sha256) != (name, len(contents), digest):
            raise ValueError("File mismatch")
    except ValueError:
        raise HTTPException(502, "file_exchange_unknown") from None
    response.headers["Cache-Control"] = "private, no-store"
    return receipt
