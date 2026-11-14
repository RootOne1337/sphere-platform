"""Catalog writes are scoped to the authenticated organization."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import Select, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.application_automation_policy import ApplicationAutomationPolicy
from backend.models.application_profile import ApplicationProfile
from backend.schemas.application_profiles import (
    MAX_PROFILES,
    ApplicationProfileList,
    ApplicationProfileResponse,
    ApplicationServer,
    CreateApplicationProfile,
    UpdateApplicationProfile,
)

BUILTIN_ID = uuid.UUID("26a1397d-2696-5c48-8cc6-af6ae2706ff1")
BUILTIN_KEY = "black-russia"
BUILTIN_ALIASES = ("black_russia", "com.br.top")


@lru_cache(maxsize=1)
def _builtin_profile() -> ApplicationProfileResponse:
    path = Path(__file__).resolve().parents[1] / "core" / "servers.json"
    servers = json.loads(path.read_text(encoding="utf-8"))
    return ApplicationProfileResponse(
        id=BUILTIN_ID,
        key=BUILTIN_KEY,
        name="Black Russia",
        android_package="com.br.top",
        source="builtin",
        aliases=list(BUILTIN_ALIASES),
        servers=[
            ApplicationServer(key=f"server-{item['id']}", name=item["name"], domain=item["domain"], port=item["port"])
            for item in servers
        ],
    )


class ApplicationProfileService:
    def __init__(self, db: AsyncSession, org_id: uuid.UUID) -> None:
        self.db = db
        self.org_id = org_id

    def _owned(self) -> Select[tuple[ApplicationProfile]]:
        return select(ApplicationProfile).where(ApplicationProfile.org_id == self.org_id)

    async def list(self) -> ApplicationProfileList:
        profiles = (await self.db.scalars(self._owned().order_by(ApplicationProfile.key).limit(MAX_PROFILES))).all()
        if len(profiles) >= MAX_PROFILES:
            raise HTTPException(503, "Application catalog exceeds its supported size")
        items = [_builtin_profile().model_copy(deep=True)]
        items.extend(ApplicationProfileResponse.model_validate(row) for row in profiles)
        return ApplicationProfileList(items=items, total=len(items))

    async def create(self, request: CreateApplicationProfile) -> ApplicationProfileResponse:
        if request.key in (BUILTIN_KEY, *BUILTIN_ALIASES):
            raise HTTPException(409, "Application profile key is reserved")
        # Serialize the bounded count and key check without changing organization privileges.
        digest = hashlib.sha256(f"application-catalog:{self.org_id}".encode()).digest()
        lock_key = int.from_bytes(digest[:8], "big", signed=True)
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        keys = (await self.db.scalars(
            select(ApplicationProfile.key).where(ApplicationProfile.org_id == self.org_id).limit(MAX_PROFILES)
        )).all()
        if request.key in keys:
            raise HTTPException(409, "Application profile key already exists")
        if len(keys) >= MAX_PROFILES - 1:
            raise HTTPException(409, "Application catalog is full")
        row = ApplicationProfile(org_id=self.org_id, **request.model_dump())
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return ApplicationProfileResponse.model_validate(row)

    async def update(self, profile_id: uuid.UUID, request: UpdateApplicationProfile) -> ApplicationProfileResponse:
        if profile_id == BUILTIN_ID:
            raise HTTPException(409, "Built-in application profile is read-only")
        row = await self.db.scalar(
            self._owned().where(ApplicationProfile.id == profile_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if row is None:
            raise HTTPException(404, "Application profile not found")
        if row.updated_at != request.expected_updated_at:
            raise HTTPException(409, "Application profile changed; reload before saving")

        changes = request.model_dump(exclude_unset=True, exclude={"expected_updated_at"})
        if "servers" in changes:
            names = {server["key"]: server["name"] for server in changes["servers"]}
            if any(names.get(server["key"]) != server["name"] for server in row.servers):
                raise HTTPException(409, "Existing server keys and names must be retained")
        if "android_package" in changes and changes["android_package"] != row.android_package:
            enabled = select(ApplicationAutomationPolicy.application_profile_id).where(
                ApplicationAutomationPolicy.org_id == self.org_id,
                ApplicationAutomationPolicy.application_profile_id == profile_id,
                or_(ApplicationAutomationPolicy.registration_enabled, ApplicationAutomationPolicy.farming_enabled),
            ).exists()
            if await self.db.scalar(select(enabled)):
                raise HTTPException(409, "Disable profile registration and farming before changing the Android package")
        changed = False
        for key, value in changes.items():
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed = True
        if changed:
            row.updated_at = max(datetime.now(timezone.utc), row.updated_at + timedelta(microseconds=1))
            await self.db.flush()
        return ApplicationProfileResponse.model_validate(row)
