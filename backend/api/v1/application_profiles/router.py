"""Operator application catalog and per-profile automation settings."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from prometheus_client import Counter
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_tenant_db, require_permission
from backend.models.user import User
from backend.schemas.application_automation import (
    ApplicationAutomationPolicyResponse,
    ApplicationAutomationPolicyUpdate,
)
from backend.schemas.application_profiles import (
    ApplicationProfileList,
    ApplicationProfileResponse,
    CreateApplicationProfile,
    UpdateApplicationProfile,
)
from backend.services.application_automation_service import ApplicationAutomationService
from backend.services.application_profile_service import ApplicationProfileService

router = APIRouter(prefix="/application-profiles", tags=["application-profiles"])
logger = structlog.get_logger()
catalog_storage_errors = Counter(
    "sphere_application_catalog_storage_errors_total",
    "Application catalog requests rejected because storage is not provisioned",
    ("sqlstate",),
)
_next_catalog_warning: dict[str, float] = {}


@contextmanager
def _catalog_storage() -> Iterator[None]:
    try:
        yield
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate not in {"42501", "42P01"}:
            raise
        catalog_storage_errors.labels(sqlstate=sqlstate).inc()
        now = monotonic()
        if now >= _next_catalog_warning.get(sqlstate, 0):
            _next_catalog_warning[sqlstate] = now + 60
            logger.warning("application_catalog_storage_unavailable", sqlstate=sqlstate)
        raise HTTPException(503, "Application catalog is unavailable") from exc


@router.get("", response_model=ApplicationProfileList, summary="List tenant and built-in application profiles")
async def list_profiles(
    user: User = require_permission("account:read"), db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationProfileList:
    with _catalog_storage():
        return await ApplicationProfileService(db, user.org_id).list()


@router.post("", response_model=ApplicationProfileResponse, status_code=201, summary="Create a tenant application profile")
async def create_profile(
    body: CreateApplicationProfile,
    user: User = require_permission("account:write"), db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationProfileResponse:
    with _catalog_storage():
        profile = await ApplicationProfileService(db, user.org_id).create(body)
        await db.commit()
    return profile


@router.patch("/{profile_id}", response_model=ApplicationProfileResponse, summary="Update an inspected application profile")
async def update_profile(
    profile_id: uuid.UUID, body: UpdateApplicationProfile,
    user: User = require_permission("account:write"), db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationProfileResponse:
    with _catalog_storage():
        profile = await ApplicationProfileService(db, user.org_id).update(profile_id, body)
        await db.commit()
    return profile


@router.get("/{profile_id}/automation-policy", response_model=ApplicationAutomationPolicyResponse)
async def get_automation_policy(
    profile_id: uuid.UUID, response: Response, user: User = require_permission("pipeline:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationAutomationPolicyResponse:
    with _catalog_storage():
        response.headers["Cache-Control"] = "no-store"
        return await ApplicationAutomationService(db, user.org_id).get_policy(profile_id)


@router.put(
    "/{profile_id}/automation-policy", response_model=ApplicationAutomationPolicyResponse,
    responses={409: {"description": "Policy revision changed or built-in profile"}},
)
async def update_automation_policy(
    profile_id: uuid.UUID, body: ApplicationAutomationPolicyUpdate, response: Response,
    user: User = require_permission("pipeline:write"), db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationAutomationPolicyResponse:
    with _catalog_storage():
        policy = await ApplicationAutomationService(db, user.org_id).update_policy(profile_id, body)
        await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return policy
