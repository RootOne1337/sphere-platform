# backend/api/v1/logs/router.py
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# Device log management:
#  POST /logs/upload       — агент загружает накопленные логи   (X-API-Key auth)
#  GET  /logs/{device_id}  — просмотр логов устройства         (JWT или API-Key)
#  DELETE /logs/{device_id} — очистка логов устройства         (только admin)
from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.device import Device


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
_LOGS_DIR = Path(os.environ.get("SPHERE_LOGS_DIR", "/tmp/sphere_device_logs"))  # nosec B108
_MAX_LOG_SIZE_BYTES = 50 * 1024 * 1024   # 50 MB per device
_MAX_ENTRY_BYTES = 512 * 1024             # 512 KB per upload
_LOG_TTL_DAYS = 30                        # rotate logs older than N days


def _device_log_path(device_id: str) -> Path:
    # Sanitize device_id to prevent path traversal
    safe_id = hashlib.sha256(device_id.encode()).hexdigest()[:32]
    return _LOGS_DIR / safe_id


def _get_log_file(device_id: str) -> Path:
    device_dir = _device_log_path(device_id)
    device_dir.mkdir(parents=True, exist_ok=True)
    # One log file per day
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return device_dir / f"agent_{date_str}.log"


def _clean_old_logs(device_id: str) -> None:
    """Remove log files older than _LOG_TTL_DAYS days."""
    device_dir = _device_log_path(device_id)
    if not device_dir.exists():
        return
    cutoff = time.time() - _LOG_TTL_DAYS * 86400
    for f in device_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def _get_device_id_from_header(
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
) -> Optional[str]:
    return x_device_id


# ── Upload (called by LogUploadWorker on the Android agent) ──────────────────

@router.post("/upload")
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
    device_id = str((await _owned_device(db, device_id, principal)).id)

    # Read body with size limit
    body = await request.body()
    if len(body) > _MAX_ENTRY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Log body exceeds {_MAX_ENTRY_BYTES // 1024} KB limit",
        )

    upload_ts = datetime.now(timezone.utc).isoformat()
    separator = f"\n--- Uploaded at {upload_ts} ---\n"

    log_file = _get_log_file(device_id)
    # Rotate if file exceeds max size
    if log_file.exists() and log_file.stat().st_size > _MAX_LOG_SIZE_BYTES:
        log_file.unlink(missing_ok=True)

    # Append once: concurrent uploads must not replace each other's data, and
    # uploading 512 KiB must not read/rewrite the whole 50 MiB file.
    from starlette.concurrency import run_in_threadpool
    def append_entry():
        with log_file.open("ab") as stream:
            stream.write(separator.encode() + body)
    await run_in_threadpool(append_entry)
    _clean_old_logs(device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Get logs for a device ─────────────────────────────────────────────────────

@router.get("/{device_id}")
async def get_device_logs(
    device_id: str,
    lines: int = Query(default=500, ge=1, le=10000, description="Max lines to return"),
    date: Optional[str] = Query(default=None, description="Date filter YYYY-MM-DD (default: today)"),
    search: Optional[str] = Query(default=None, description="Filter lines containing this text"),
    _principal=require_permission("device:read"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Возвращает последние N строк логов для устройства.
    Поддерживает фильтрацию по дате и поиск подстроки.
    """
    await _owned_device(db, device_id, _principal)
    device_dir = _device_log_path(device_id)
    if not device_dir.exists():
        return JSONResponse({"device_id": device_id, "lines": [], "total": 0})

    # Выбираем файлы
    if date:
        target_files = sorted(device_dir.glob(f"agent_{date}*.log"))
    else:
        target_files = sorted(device_dir.glob("agent_*.log"), reverse=True)[:3]

    all_lines: list[str] = []
    for f in reversed(target_files):
        try:
            text = f.read_text(errors="replace")
            all_lines.extend(text.splitlines())
        except OSError:
            pass

    # Apply search filter
    if search:
        all_lines = [ln for ln in all_lines if search.lower() in ln.lower()]

    # Return last N lines
    result_lines = all_lines[-lines:]
    return JSONResponse({
        "device_id": device_id,
        "lines": result_lines,
        "total": len(result_lines),
    })


# ── Delete (admin only) ───────────────────────────────────────────────────────

@router.delete("/{device_id}")
async def delete_device_logs(
    device_id: str,
    _user=require_permission("device:delete"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Удаляет все логи для устройства. Только для администраторов."""
    import shutil
    await _owned_device(db, device_id, _user)
    device_dir = _device_log_path(device_id)
    if device_dir.exists():
        shutil.rmtree(device_dir, ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
