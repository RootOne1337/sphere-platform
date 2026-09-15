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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission, require_roles
from backend.database.engine import get_db

router = APIRouter(prefix="/updates", tags=["updates"])

# Релизы хранятся в JSON-файле (нет нужды в отдельной таблице)
# В production заменяется на путь из env-переменной SPHERE_UPDATES_PATH
_UPDATES_PATH = Path(os.environ.get("SPHERE_UPDATES_PATH", "/tmp/sphere_updates.json"))  # nosec B108
_ARTIFACT_PREFIX = "/api/v1/updates/artifacts/"
_MAX_ARTIFACT_BYTES = 200 * 1024 * 1024


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
    if not _UPDATES_PATH.exists():
        return []
    try:
        return json.loads(_UPDATES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_releases(releases: list[dict]) -> None:
    _UPDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _UPDATES_PATH.write_text(json.dumps(releases, indent=2))


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
    await authenticate_ws_token(x_api_key, db)

    releases = _load_releases()
    # Filter by platform + flavor, sorted by version_code desc
    matching = [
        r for r in releases
        if r.get("platform") == platform and r.get("flavor") == flavor
    ]
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
    await authenticate_ws_token(authorization.removeprefix("Bearer "), db)
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

    releases = _load_releases()
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
    releases.append(new_release)
    _save_releases(releases)
    return JSONResponse(new_release, status_code=status.HTTP_201_CREATED)


# ── Delete release (admin only) ───────────────────────────────────────────────

@router.delete("/{release_id}")
async def delete_release(
    release_id: str,
    _user=require_roles(["super_admin"]),
) -> Response:
    releases = _load_releases()
    filtered = [r for r in releases if r.get("id") != release_id]
    if len(filtered) == len(releases):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    _save_releases(filtered)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
