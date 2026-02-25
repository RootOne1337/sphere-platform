# backend/api/v1/updates/router.py
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# OTA Update management:
#  GET  /updates/latest   — агент запрашивает последнюю версию    (X-API-Key)
#  GET  /updates/         — список всех релизов                   (JWT admin)
#  POST /updates/         — создание нового релиза                (JWT admin)
#  DELETE /updates/{id}  — удаление релиза                       (JWT admin)
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db

router = APIRouter(prefix="/updates", tags=["updates"])

# Релизы хранятся в JSON-файле (нет нужды в отдельной таблице)
# В production заменяется на путь из env-переменной SPHERE_UPDATES_PATH
_UPDATES_PATH = Path(os.environ.get("SPHERE_UPDATES_PATH", "/tmp/sphere_updates.json"))  # nosec B108


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
    from backend.services.api_key_service import APIKeyService
    api_key_svc = APIKeyService(db)
    key_obj = await api_key_svc.authenticate(x_api_key)
    if not key_obj:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

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

    return JSONResponse({
        "update_available": True,
        "version_code": latest_code,
        "version_name": latest.get("version_name"),
        "download_url": latest.get("download_url"),
        "sha256": latest.get("sha256", ""),
        "mandatory": latest.get("mandatory", False),
        "changelog": latest.get("changelog"),
    })


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
    _user=require_permission("device:write"),
) -> JSONResponse:
    """
    Регистрирует новый APK-релиз в системе обновлений.
    После создания агенты автоматически обнаружат его при следующей проверке (до 6 ч).
    """
    # Security: allow only https:// download URLs to prevent SSRF
    if not payload.download_url.startswith("https://"):
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
    _user=require_permission("device:delete"),
) -> Response:
    releases = _load_releases()
    filtered = [r for r in releases if r.get("id") != release_id]
    if len(filtered) == len(releases):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    _save_releases(filtered)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
