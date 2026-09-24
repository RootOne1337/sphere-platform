# backend/api/v1/updates/router.py
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# OTA Update management:
#  GET  /updates/latest   — агент запрашивает последнюю версию    (X-API-Key)
#  GET  /updates/         — список всех релизов                   (JWT admin)
#  POST /updates/         — создание нового релиза                (JWT admin)
#  DELETE /updates/{id}  — удаление релиза                       (JWT admin)
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission, require_roles
from backend.database.engine import get_db
from backend.models.device import Device
from backend.services.device_ota_recovery import OtaRecoveryGrant, get_ota_recovery

router = APIRouter(prefix="/updates", tags=["updates"])

# Pilot/local file store. Container overlays mount this directory persistently;
# production deployments should use a durable object/catalog service before scaling
# backend replicas. Never silently put release state in the container's /tmp.
def _resolve_updates_path(configured: str | None = None) -> Path:
    override = configured or os.environ.get("SPHERE_UPDATES_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "updates" / "releases.json"


_UPDATES_PATH = _resolve_updates_path()
_ARTIFACT_PREFIX = "/api/v1/updates/artifacts/"
_MAX_ARTIFACT_BYTES = 200 * 1024 * 1024
_CATALOG_LOCK_TIMEOUT_SECONDS = 5


def _artifact_path(digest: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise HTTPException(status_code=404, detail="Artifact not found")
    directory = (_UPDATES_PATH.parent / "artifacts").resolve()
    path = directory / f"{digest}.apk"
    # Deployment supplies immutable files; never follow a link outside the store.
    if path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return path


# ── In-memory store backed by JSON file ──────────────────────────────────────

def _load_releases() -> list[dict]:
    try:
        releases = json.loads(_UPDATES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise HTTPException(status_code=503, detail="OTA release catalog is invalid") from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="OTA release catalog is unavailable") from exc
    if not isinstance(releases, list) or any(not isinstance(release, dict) for release in releases):
        raise HTTPException(status_code=503, detail="OTA release catalog is invalid")
    return releases


def _save_releases(releases: list[dict]) -> None:
    _UPDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{_UPDATES_PATH.name}.",
        suffix=".tmp",
        dir=_UPDATES_PATH.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(releases, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, _UPDATES_PATH)
        if os.name == "posix":
            directory_descriptor = os.open(
                _UPDATES_PATH.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        temporary_path.unlink(missing_ok=True)


def _append_release(release: dict) -> None:
    try:
        with FileLock(f"{_UPDATES_PATH}.lock", timeout=_CATALOG_LOCK_TIMEOUT_SECONDS):
            releases = _load_releases()
            releases.append(release)
            _save_releases(releases)
    except Timeout as exc:
        raise HTTPException(
            status_code=503,
            detail="OTA release catalog is busy; retry shortly",
            headers={"Retry-After": "1"},
        ) from exc


def _remove_release(release_id: str) -> bool:
    try:
        with FileLock(f"{_UPDATES_PATH}.lock", timeout=_CATALOG_LOCK_TIMEOUT_SECONDS):
            releases = _load_releases()
            filtered = [release for release in releases if release.get("id") != release_id]
            if len(filtered) == len(releases):
                return False
            _save_releases(filtered)
            return True
    except Timeout as exc:
        raise HTTPException(
            status_code=503,
            detail="OTA release catalog is busy; retry shortly",
            headers={"Retry-After": "1"},
        ) from exc


# ── Schemas ───────────────────────────────────────────────────────────────────

class CreateReleaseRequest(BaseModel):
    platform: str = "android"
    flavor: str = "enterprise"           # enterprise | dev
    version_code: int
    version_name: str
    download_url: str                    # must be https://
    sha256: str                          # SHA-256 of APK
    mandatory: bool = False
    changelog: Optional[str] = None


class CreateRecoveryRequest(BaseModel):
    """Явное разрешение восстановления ровно одним опубликованным APK."""

    device_id: uuid.UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_seconds: int = Field(default=1800, ge=60, le=3600)


@router.post("/recovery", status_code=201)
async def create_recovery(
    payload: CreateRecoveryRequest, user=require_roles(["super_admin"]), db: AsyncSession = Depends(get_db),
) -> dict:
    """Включить OTA-only recovery для старых копий; обычные права JWT не меняются."""
    device = await db.scalar(select(Device).where(Device.id == payload.device_id,
                                                 Device.org_id == user.org_id,
                                                 Device.is_active.is_(True)).with_for_update())
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    release = next((r for r in _load_releases() if r.get("sha256") == payload.sha256 and
                    r.get("download_url") == _ARTIFACT_PREFIX + payload.sha256), None)
    if release is None:
        raise HTTPException(status_code=422, detail="Published managed artifact required")
    _artifact_path(payload.sha256)
    now = int(datetime.now(timezone.utc).timestamp())
    active = (device.meta or {}).get("ota_recovery", {})
    if isinstance(active, dict) and active.get("expires_at", 0) > now:
        raise HTTPException(status_code=409, detail="Recovery grant already active; inspect before another request")
    grant = OtaRecoveryGrant(command_id=uuid.uuid4(), sha256=payload.sha256,
                             version_name=release["version_name"], created_at=now,
                             expires_at=now + payload.duration_seconds, issued_before=now - 1).signed(device)
    device.meta = {**(device.meta or {}), "ota_recovery": grant.model_dump(mode="json")}
    await db.commit()
    return {"device_id": str(device.id), **grant.model_dump(mode="json")}


@router.delete("/recovery/{device_id}", status_code=204)
async def revoke_recovery(
    device_id: uuid.UUID, user=require_roles(["super_admin"]), db: AsyncSession = Depends(get_db),
) -> Response:
    """Отключить аварийную доставку после сверки установленных копий."""
    device = await db.scalar(select(Device).where(Device.id == device_id,
                                                 Device.org_id == user.org_id).with_for_update())
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    device.meta = {k: v for k, v in (device.meta or {}).items() if k != "ota_recovery"}
    await db.commit()
    return Response(status_code=204)


# ── Latest version check (called by UpdateCheckWorker) ──────────────────────

@router.get("/latest")
async def get_latest(
    request: Request,
    platform: str = Query(default="android"),
    flavor: str = Query(default="enterprise"),
    version_code: int = Query(default=0),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Возвращает информацию о последнем релизе для данной платформы/флейвора.
    Если версия на устройстве >= последней → update_available=false.
    Аутентификация — X-API-Key (агент) или JWT.
    """
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-API-Key required")

    # Verify API key
    from backend.api.ws.android.router import authenticate_ws_token
    recovery = await get_ota_recovery(x_api_key, db)
    if recovery is None:
        await authenticate_ws_token(x_api_key, db)

    releases = _load_releases()
    # Filter by platform + flavor, sorted by version_code desc
    matching = [
        r for r in releases
        if r.get("platform") == platform and r.get("flavor") == flavor
    ]
    if recovery is not None:
        matching = [r for r in matching if r.get("sha256") == recovery[1].sha256]
    if not matching:
        return JSONResponse({"update_available": False})

    latest = max(matching, key=lambda r: r.get("version_code", 0))
    latest_code = latest.get("version_code", 0)

    if latest_code <= version_code:
        return JSONResponse({"update_available": False, "current_version_code": version_code})

    download_url = latest.get("download_url")
    if isinstance(download_url, str) and download_url.startswith(_ARTIFACT_PREFIX):
        # Keep managed metadata independent of an ingress hostname. The same
        # HTTPS host used by the agent receives its authenticated download.
        download_url = str(request.base_url.replace(scheme="https")).rstrip("/") + download_url

    return JSONResponse({
        "update_available": True,
        "version_code": latest_code,
        "version_name": latest.get("version_name"),
        "download_url": download_url,
        "sha256": latest.get("sha256", ""),
        "mandatory": latest.get("mandatory", False),
        "changelog": latest.get("changelog"),
    })


@router.get("/artifacts/{sha256}")
async def download_artifact(
    sha256: str,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download a published, operator-staged APK using the agent's own JWT."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    from backend.api.ws.android.router import authenticate_ws_token
    token = authorization.removeprefix("Bearer ")
    if await get_ota_recovery(token, db, sha256=sha256) is None:
        await authenticate_ws_token(token, db)
    if not any(r.get("sha256") == sha256 and r.get("download_url") == _ARTIFACT_PREFIX + sha256
               for r in _load_releases()):
        raise HTTPException(status_code=404, detail="Published artifact not found")
    path = _artifact_path(sha256)
    return FileResponse(path, media_type="application/vnd.android.package-archive",
                        headers={"Cache-Control": "private, no-store"})


# ── List all releases (admin) ─────────────────────────────────────────────────

@router.get("/")
async def list_releases(
    platform: Optional[str] = Query(default=None),
    flavor: Optional[str] = Query(default=None),
    _user=require_permission("device:read"),
) -> JSONResponse:
    releases = _load_releases()
    if platform:
        releases = [r for r in releases if r.get("platform") == platform]
    if flavor:
        releases = [r for r in releases if r.get("flavor") == flavor]
    releases_sorted = sorted(releases, key=lambda r: r.get("version_code", 0), reverse=True)
    return JSONResponse({"releases": releases_sorted, "total": len(releases_sorted)})


# ── Create release (admin only) ───────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_release(
    payload: CreateReleaseRequest,
    _user=require_roles(["super_admin"]),
) -> JSONResponse:
    """
    Регистрирует новый APK-релиз в системе обновлений.
    После создания агенты автоматически обнаружат его при следующей проверке (до 6 ч).
    """
    if payload.download_url == _ARTIFACT_PREFIX + payload.sha256:
        try:
            artifact = _artifact_path(payload.sha256)
        except HTTPException as exc:
            raise HTTPException(status_code=422, detail="Managed artifact is missing or invalid") from exc
        if not 0 < artifact.stat().st_size <= _MAX_ARTIFACT_BYTES:
            raise HTTPException(status_code=422, detail="Managed artifact size is invalid")
        with artifact.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != payload.sha256:
            raise HTTPException(status_code=422, detail="Managed artifact checksum mismatch")
    elif not payload.download_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="download_url must use HTTPS",
        )

    new_release = {
        "id": str(uuid.uuid4()),
        "platform": payload.platform,
        "flavor": payload.flavor,
        "version_code": payload.version_code,
        "version_name": payload.version_name,
        "download_url": payload.download_url,
        "sha256": payload.sha256,
        "mandatory": payload.mandatory,
        "changelog": payload.changelog,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _append_release(new_release)
    return JSONResponse(new_release, status_code=status.HTTP_201_CREATED)


# ── Delete release (admin only) ───────────────────────────────────────────────

@router.delete("/{release_id}")
async def delete_release(
    release_id: str,
    _user=require_roles(["super_admin"]),
) -> Response:
    if not _remove_release(release_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
