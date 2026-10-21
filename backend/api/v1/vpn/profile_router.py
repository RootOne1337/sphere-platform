from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.v1.vpn.profile_input import profile_request_schema, read_profile_request
from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.schemas.vpn.catalog import (
    VPNProfileAppendRequest,
    VPNProfileArchiveRequest,
    VPNProfileImportRequest,
    VPNProfilePage,
    VPNProfileResponse,
    VPNProfileRevisionPage,
    VPNProfileSaveResponse,
)
from backend.services.vpn.profile_catalog import VPNProfileCatalog

router = APIRouter(prefix="/profiles")
_ERRORS = {401: {"description": "Authentication required"}, 403: {"description": "VPN permission required"},
           404: {"description": "Owned profile/import not found"}, 409: {"description": "Revision, archive or request ID conflict"},
           413: {"description": "Request exceeds 96 KiB"}, 422: {"description": "Invalid request/config, without secret echo"},
           503: {"description": "Profile encryption unavailable"}}


@router.get("", response_model=VPNProfilePage)
async def list_profiles(
    page: int = Query(1, ge=1, le=10000), page_size: int = Query(25, ge=1, le=100),
    include_archived: bool = False, search: str = Query("", max_length=120),
    user=require_permission("vpn:read"), db: AsyncSession = Depends(get_db),
):
    return await VPNProfileCatalog(db, user.org_id, user.id).list(
        page=page, page_size=page_size, include_archived=include_archived, search=search,
    )


@router.post("", response_model=VPNProfileSaveResponse, responses=_ERRORS,
             summary="Save an encrypted VPN profile without applying it",
             openapi_extra={"requestBody": profile_request_schema(VPNProfileImportRequest)})
async def import_profile(request: Request, user=require_permission("vpn:write"), db: AsyncSession = Depends(get_db)):
    body = await read_profile_request(request, VPNProfileImportRequest)
    receipt = await VPNProfileCatalog(db, user.org_id, user.id).save(body)
    await db.commit()
    return receipt


@router.get("/imports/{request_id}", response_model=VPNProfileSaveResponse, responses={404: _ERRORS[404]})
async def import_status(request_id: uuid.UUID, user=require_permission("vpn:read"), db: AsyncSession = Depends(get_db)):
    return await VPNProfileCatalog(db, user.org_id, user.id).import_status(request_id)


@router.get("/{profile_id}", response_model=VPNProfileResponse, responses={404: _ERRORS[404]})
async def get_profile(profile_id: uuid.UUID, user=require_permission("vpn:read"), db: AsyncSession = Depends(get_db)):
    return await VPNProfileCatalog(db, user.org_id, user.id).get(profile_id)


@router.get("/{profile_id}/revisions", response_model=VPNProfileRevisionPage, responses={404: _ERRORS[404]})
async def profile_revisions(
    profile_id: uuid.UUID, page: int = Query(1, ge=1, le=10000), page_size: int = Query(25, ge=1, le=100),
    user=require_permission("vpn:read"), db: AsyncSession = Depends(get_db),
):
    return await VPNProfileCatalog(db, user.org_id, user.id).revisions(profile_id, page=page, page_size=page_size)


@router.post("/{profile_id}/revisions", response_model=VPNProfileSaveResponse, responses=_ERRORS,
             openapi_extra={"requestBody": profile_request_schema(VPNProfileAppendRequest)})
async def append_revision(profile_id: uuid.UUID, request: Request, user=require_permission("vpn:write"), db: AsyncSession = Depends(get_db)):
    body = await read_profile_request(request, VPNProfileAppendRequest)
    receipt = await VPNProfileCatalog(db, user.org_id, user.id).save(body, profile_id)
    await db.commit()
    return receipt


@router.post("/{profile_id}/archive", response_model=VPNProfileResponse, responses=_ERRORS,
             openapi_extra={"requestBody": profile_request_schema(VPNProfileArchiveRequest)})
async def archive_profile(profile_id: uuid.UUID, request: Request, user=require_permission("vpn:write"), db: AsyncSession = Depends(get_db)):
    body = await read_profile_request(request, VPNProfileArchiveRequest)
    result = await VPNProfileCatalog(db, user.org_id, user.id).archive(profile_id, body.expected_revision)
    await db.commit()
    return result
