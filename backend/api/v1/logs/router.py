# backend/api/v1/logs/router.py
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# Device log management:
#  POST /logs/upload       — агент загружает накопленные логи   (X-API-Key auth)
#  GET  /logs/{device_id}  — просмотр логов устройства         (JWT или API-Key)
#  DELETE /logs/{device_id} — очистка логов устройства         (только admin)
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

import backend.services.device_log_maintenance  # noqa: F401 — registers lifecycle hooks
from backend.core.config import settings
from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.device import Device
from backend.schemas.device_logs import (
    DeviceLogDatesResponse,
    DeviceLogReadError,
    DeviceLogsResponse,
)
from backend.services.device_log_reader import (
    LogReadBusy,
    LogReadUnavailable,
    read_log_dates_async,
    read_log_tail_async,
    validate_date,
)
from backend.services.device_log_storage import (
    DEVICE_LOG_ROOT,
    JOURNAL_RETENTION_DAYS,
    LegacyJournalOwnership,
    LogStorageQuotaExceeded,
    append_device_journal,
    delete_device_journal,
    device_journal_key,
)
from backend.services.device_log_upload import (
    MAX_BODY_BYTES,
    LogUploadBusy,
    LogUploadInvalidBody,
    LogUploadTimeout,
    LogUploadTooLarge,
    LogUploadUnavailable,
    receive_and_store_log,
    run_log_storage_write,
)

logger = structlog.get_logger()


async def _owned_device(db: AsyncSession, device_id: str, principal) -> Device:
    try:
        device = await db.get(Device, uuid.UUID(device_id))
    except ValueError:
        device = None
    if (not device or not device.is_active or device.org_id != principal.org_id
            or getattr(principal, "device_id", device.id) != device.id):
        raise HTTPException(status_code=404, detail="Device not found")
    return device

router = APIRouter(prefix="/logs", tags=["logs"])

# Лог-файлы хранятся на диске в /tmp/sphere_device_logs/<device_id>/
# В production заменяется на путь из env-переменной SPHERE_LOGS_DIR
_LOGS_DIR = DEVICE_LOG_ROOT
_LOG_TTL_DAYS = JOURNAL_RETENTION_DAYS


def _device_log_path(device_id: str) -> Path:
    return _LOGS_DIR / device_journal_key(device_id)


_LEGACY_OWNER_KEYS = text("""
    SELECT owned.directory_key
    FROM (
        SELECT left(encode(sha256(convert_to(id::text, 'UTF8')), 'hex'), 32) AS directory_key
        FROM devices WHERE org_id = :org_id
    ) AS owned
    WHERE owned.directory_key = ANY(:directory_keys)
""").bindparams(bindparam("directory_keys", type_=ARRAY(String)))
_LEGACY_LOOKUP_TIMEOUT_SECONDS = 3.0


async def _legacy_organization_journals(
    db: AsyncSession, org_id: uuid.UUID, directory_keys: frozenset[str],
) -> LegacyJournalOwnership:
    # The device registry keeps retired devices, so their retained journals
    # continue to consume the organization's quota until the independent sweep.
    try:
        async with asyncio.timeout(_LEGACY_LOOKUP_TIMEOUT_SECONDS):
            owned = await db.scalars(_LEGACY_OWNER_KEYS, {"org_id": org_id, "directory_keys": sorted(directory_keys)})
        return LegacyJournalOwnership(directory_keys, frozenset(owned))
    except (SQLAlchemyError, TimeoutError) as exc:
        raise LogUploadUnavailable() from exc


def _get_log_file(device_id: str, *, create_directory: bool = True) -> Path:
    device_dir = _device_log_path(device_id)
    if create_directory:
        device_dir.mkdir(parents=True, exist_ok=True)
    # One log file per day
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return device_dir / f"agent_{date_str}.log"


def _get_device_id_from_header(
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
) -> Optional[str]:
    return x_device_id


# ── Upload (called by LogUploadWorker on the Android agent) ──────────────────

@router.post("/upload", status_code=204, responses={
    400: {"description": "Invalid or incomplete log body"},
    408: {"description": "Log body receive deadline exceeded"},
    413: {"description": "Log body exceeds 512 KiB"},
    503: {"description": "Upload capacity is busy or log storage unavailable"},
    507: {"description": "Device journal storage budget is full"},
})
async def upload_logs(
    request: Request,
    device_id: str | None = Query(default=None, description="Device ID (legacy clients)"),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Принимает текстовые логи от агента (Android / PC).
    Аутентификация — только X-API-Key (агент получает его при энролменте).
    """
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-API-Key required")

    # Verify API key belongs to this device
    from backend.api.ws.android.router import authenticate_ws_token
    principal = await authenticate_ws_token(x_api_key, db)
    if device_id and x_device_id and device_id != x_device_id:
        raise HTTPException(status_code=400, detail="Conflicting device identifiers")
    device_id = x_device_id or device_id
    if not device_id:
        raise HTTPException(status_code=400, detail="X-Device-Id required")
    device = await _owned_device(db, device_id, principal)
    device_id = str(device.id)
    org_id = device.org_id
    legacy: LegacyJournalOwnership | None = None

    async def resolve_legacy(directory_keys: frozenset[str]) -> None:
        nonlocal legacy
        legacy = await _legacy_organization_journals(db, org_id, directory_keys)

    def append_entry(body: bytes) -> None:
        upload_ts = datetime.now(timezone.utc).isoformat()
        separator = f"\n--- Uploaded at {upload_ts} ---\n"
        append_device_journal(
            _get_log_file(device_id, create_directory=False), separator.encode() + body,
            daily_limit=settings.DEVICE_LOG_DAILY_MAX_BYTES, volume_limit=settings.DEVICE_LOG_STORAGE_MAX_BYTES,
            ttl_days=_LOG_TTL_DAYS, org_id=str(org_id), org_limit=settings.DEVICE_LOG_ORG_MAX_BYTES,
            legacy=legacy,
        )

    try:
        await receive_and_store_log(request, append_entry, resolve_legacy=resolve_legacy)
    except LogUploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=f"Log body exceeds {MAX_BODY_BYTES // 1024} KB limit") from exc
    except LogUploadInvalidBody as exc:
        raise HTTPException(status_code=400, detail="Invalid or incomplete log body") from exc
    except LogUploadTimeout as exc:
        raise HTTPException(status_code=408, detail="Log body receive deadline exceeded") from exc
    except LogUploadBusy as exc:
        raise HTTPException(status_code=503, detail="Log upload capacity is busy", headers={"Retry-After": "1"}) from exc
    except LogUploadUnavailable as exc:
        raise HTTPException(status_code=503, detail="Log storage is unavailable", headers={"Retry-After": "1"}) from exc
    except LogStorageQuotaExceeded as exc:
        raise HTTPException(status_code=507, detail="Device journal storage budget is full", headers={"Retry-After": "900"}) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Get logs for a device ─────────────────────────────────────────────────────

_READ_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    503: {
        "model": DeviceLogReadError,
        "description": "Log read capacity is busy or log source is unavailable",
        "headers": {
            "Retry-After": {"description": "Delay in seconds when read capacity is busy", "schema": {"type": "integer"}},
            "X-Request-ID": {"description": "Correlation ID for the request", "schema": {"type": "string"}},
        },
    },
}


def _read_failure(error: LogReadBusy | LogReadUnavailable) -> JSONResponse:
    if isinstance(error, LogReadBusy):
        return JSONResponse(
            {"detail": "Log read capacity is busy", "reason": "log_read_busy"},
            status_code=503, headers={"Retry-After": "1"},
        )
    logger.debug("device_logs.source_unavailable")
    return JSONResponse(
        {"detail": "Log source is unavailable", "reason": "log_source_unavailable"},
        status_code=503,
    )


@router.get("/{device_id}/dates", response_model=DeviceLogDatesResponse, responses=_READ_ERROR_RESPONSES)
async def get_device_log_dates(
    device_id: str,
    _principal=require_permission("device:read"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List retained UTC journal dates without reading their contents."""
    device = await _owned_device(db, device_id, _principal)
    try:
        dates = await read_log_dates_async(_device_log_path(str(device.id)))
    except (LogReadBusy, LogReadUnavailable) as exc:
        return _read_failure(exc)
    return JSONResponse({"device_id": device_id, "dates": dates})


@router.get("/{device_id}", response_model=DeviceLogsResponse, responses=_READ_ERROR_RESPONSES)
async def get_device_logs(
    device_id: str,
    lines: int = Query(default=500, ge=1, le=10000, description="Max lines to return"),
    date: Optional[str] = Query(default=None, max_length=10, description="UTC date YYYY-MM-DD; default: recent three daily files"),
    search: Optional[str] = Query(default=None, max_length=512, description="Substring search within the bounded recent-file tail"),
    _principal=require_permission("device:read"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Возвращает последние N строк логов для устройства.
    Поддерживает фильтрацию по дате и поиск подстроки.
    """
    device = await _owned_device(db, device_id, _principal)
    try:
        validate_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date must use YYYY-MM-DD") from exc
    try:
        payload = await read_log_tail_async(_device_log_path(str(device.id)), lines=lines, date=date, search=search)
    except (LogReadBusy, LogReadUnavailable) as exc:
        return _read_failure(exc)
    return JSONResponse({"device_id": device_id, **payload})


# ── Delete (admin only) ───────────────────────────────────────────────────────

@router.delete("/{device_id}", status_code=204, responses={503: {"description": "Device journal storage unavailable or busy"}})
async def delete_device_logs(
    device_id: str,
    _user=require_permission("device:delete"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Удаляет все логи для устройства. Только для администраторов."""
    device = await _owned_device(db, device_id, _user)
    device_dir = _device_log_path(str(device.id))
    try:
        await run_log_storage_write(lambda: delete_device_journal(device_dir))
    except LogUploadBusy as exc:
        raise HTTPException(status_code=503, detail="Log write capacity is busy", headers={"Retry-After": "1"}) from exc
    except LogUploadUnavailable as exc:
        raise HTTPException(status_code=503, detail="Log storage is unavailable") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
