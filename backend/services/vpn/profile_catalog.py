"""Persistent profile management, deliberately independent of VPN execution."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit_log import AuditLog
from backend.models.vpn_profile import VPNProfile, VPNProfileRevision
from backend.schemas.vpn.catalog import (
    VPNProfileAppendRequest,
    VPNProfileImportRequest,
    VPNProfilePage,
    VPNProfileResponse,
    VPNProfileRevisionPage,
    VPNProfileRevisionResponse,
    VPNProfileSaveResponse,
)
from backend.services.vpn.profile_preflight import preflight_profile
from backend.services.vpn.profile_secrets import decrypt_revision, encrypt_revision

_META = ("name", "description", "provider_id", "protocol", "protocol_version", "schema_version", "traffic_policy", "endpoint", "features")


def _fingerprint(request: VPNProfileImportRequest, profile_id: uuid.UUID | None) -> str:
    # Stored ONLY inside the authenticated ciphertext, never in metadata/logs.
    data = request.model_dump(mode="json", exclude={"profile": {"config_text"}})
    data["profile"]["config_text"] = request.profile.config_text.get_secret_value()
    data["target_profile_id"] = str(profile_id) if profile_id else None
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _receipt(row: VPNProfileRevision) -> VPNProfileSaveResponse:
    return VPNProfileSaveResponse(profile_id=row.profile_id, revision_id=row.id, revision=row.revision, request_id=row.request_id)


class VPNProfileCatalog:
    def __init__(self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID):
        self.db, self.org_id, self.user_id = db, org_id, user_id

    async def _owned(self, profile_id: uuid.UUID, *, lock=False) -> VPNProfile:
        statement = select(VPNProfile).where(VPNProfile.id == profile_id, VPNProfile.org_id == self.org_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        row = await self.db.scalar(statement)
        if row is None:
            raise HTTPException(404, "vpn_profile_not_found")
        return row

    async def _replay(self, request_id: uuid.UUID, fingerprint: str) -> VPNProfileSaveResponse | None:
        row = await self.db.scalar(select(VPNProfileRevision).where(
            VPNProfileRevision.org_id == self.org_id, VPNProfileRevision.request_id == request_id,
        ))
        if row is None:
            return None
        _, stored = decrypt_revision(row)
        if not hmac.compare_digest(stored, fingerprint):
            raise HTTPException(409, "vpn_profile_request_id_conflict")
        return _receipt(row)

    async def import_status(self, request_id: uuid.UUID) -> VPNProfileSaveResponse:
        # A 404 means not observed in this SQL snapshot, not that an in-flight
        # request is cancelled or cannot still commit. Never auto-retry with a new ID.
        row = (await self.db.execute(select(
            VPNProfileRevision.profile_id, VPNProfileRevision.id.label("revision_id"),
            VPNProfileRevision.revision, VPNProfileRevision.request_id,
        ).where(VPNProfileRevision.org_id == self.org_id, VPNProfileRevision.request_id == request_id))).mappings().one_or_none()
        if row is None:
            raise HTTPException(404, "vpn_profile_import_not_observed")
        return VPNProfileSaveResponse(**row)

    async def save(self, request: VPNProfileImportRequest, profile_id: uuid.UUID | None = None) -> VPNProfileSaveResponse:
        # Ownership precedes validation/crypto for an existing profile, so a
        # missing key cannot reveal anything about another tenant's record.
        if profile_id is not None:
            await self._owned(profile_id)
            if not isinstance(request, VPNProfileAppendRequest):
                raise HTTPException(422, "vpn_profile_expected_revision_required")
        inspected = preflight_profile(request.profile)
        if not inspected.config_valid:
            raise HTTPException(422, {"code": "invalid_vpn_profile_config", "issues": [i.model_dump() for i in inspected.issues]})
        fingerprint = _fingerprint(request, profile_id)
        replay = await self._replay(request.request_id, fingerprint)
        if replay:
            return replay
        try:
            async with self.db.begin_nested():
                if profile_id is None:
                    profile = VPNProfile(id=uuid.uuid4(), org_id=self.org_id, name=request.name,
                                         description=request.description, current_revision=1, is_archived=False)
                    number = 1
                else:
                    if not isinstance(request, VPNProfileAppendRequest):
                        raise HTTPException(422, "vpn_profile_expected_revision_required")
                    profile = await self._owned(profile_id, lock=True)
                    # A concurrent identical request may have committed while
                    # we waited for the profile lock.
                    replay = await self._replay(request.request_id, fingerprint)
                    if replay:
                        return replay
                    if profile.is_archived:
                        raise HTTPException(409, "vpn_profile_archived")
                    if profile.current_revision != request.expected_revision:
                        raise HTTPException(409, "vpn_profile_revision_conflict")
                    number = request.expected_revision + 1

                row = VPNProfileRevision(
                    id=uuid.uuid4(), org_id=self.org_id, profile_id=profile.id, revision=number,
                    request_id=request.request_id, name=request.name, description=request.description,
                    provider_id=request.profile.provider_id, protocol=request.profile.protocol,
                    protocol_version=request.profile.protocol_version, schema_version=request.profile.schema_version,
                    traffic_policy=request.profile.traffic_policy.model_dump(), endpoint=inspected.endpoint,
                    features=inspected.features, created_by_id=self.user_id,
                )
                # Crypto must succeed before either row can be flushed. No
                # fallback to plaintext or to an ephemeral/random server key.
                row.config_ciphertext = encrypt_revision(row, request.profile.config_text.get_secret_value(), fingerprint)
                if profile_id is None:
                    self.db.add(profile)
                    await self.db.flush()
                else:
                    assert isinstance(request, VPNProfileAppendRequest)  # Validated before acquiring the profile lock.
                    changed = await self.db.execute(update(VPNProfile).where(
                        VPNProfile.id == profile.id, VPNProfile.org_id == self.org_id,
                        VPNProfile.current_revision == request.expected_revision, VPNProfile.is_archived.is_(False),
                    ).values(current_revision=number, name=request.name, description=request.description, updated_at=func.now()))
                    if changed.rowcount != 1:
                        raise HTTPException(409, "vpn_profile_revision_conflict")
                self.db.add(row)
                self.db.add(AuditLog(
                    org_id=self.org_id, user_id=self.user_id, action="vpn.profile.created" if number == 1 else "vpn.profile.revision_created",
                    resource_type="vpn_profile", resource_id=str(profile.id),
                    meta={"revision": number, "revision_id": str(row.id), "request_id": str(request.request_id)},
                ))
                await self.db.flush()
                return _receipt(row)
        except IntegrityError:
            # The savepoint restores a speculative profile/head update. Read
            # the winning request in a fresh READ COMMITTED statement.
            replay = await self._replay(request.request_id, fingerprint)
            if replay:
                return replay
            raise HTTPException(409, "vpn_profile_write_conflict") from None

    def _heads(self):
        return select(
            VPNProfile.id, VPNProfile.current_revision, VPNProfile.is_archived,
            VPNProfile.created_at, VPNProfile.updated_at,
            VPNProfileRevision.id.label("revision_id"),
            *(getattr(VPNProfileRevision, name) for name in _META),
        ).join(VPNProfileRevision, (VPNProfileRevision.profile_id == VPNProfile.id)
               & (VPNProfileRevision.org_id == VPNProfile.org_id)
               & (VPNProfileRevision.revision == VPNProfile.current_revision)).where(VPNProfile.org_id == self.org_id)

    async def get(self, profile_id: uuid.UUID) -> VPNProfileResponse:
        row = (await self.db.execute(self._heads().where(VPNProfile.id == profile_id))).mappings().one_or_none()
        if row is None:
            raise HTTPException(404, "vpn_profile_not_found")
        return VPNProfileResponse(**row)

    async def _page(self, statement, page: int, page_size: int, order: tuple) -> tuple[list[dict], int]:
        # Single SQL snapshot, including empty/out-of-range pages. The sentinel
        # LEFT JOIN avoids a separate count/source query or a ciphertext read.
        filtered = statement.cte("vpn_catalog_filtered")
        ordered = select(filtered).order_by(*(filtered.c[name].desc() for name in order)).offset((page - 1) * page_size).limit(page_size).subquery()
        total = select(func.count().label("_total")).select_from(filtered).subquery()
        result = (await self.db.execute(select(ordered, total.c._total).select_from(total.outerjoin(ordered, true())))).mappings().all()
        return [dict(row) for row in result if row["id"] is not None], int(result[0]["_total"])

    async def list(self, *, page=1, page_size=25, include_archived=False, search="") -> VPNProfilePage:
        statement = self._heads()
        if not include_archived:
            statement = statement.where(VPNProfile.is_archived.is_(False))
        if search.strip():
            statement = statement.where(VPNProfile.name.icontains(search.strip(), autoescape=True))
        rows, total = await self._page(statement, page, page_size, ("created_at", "id"))
        return VPNProfilePage(items=[VPNProfileResponse(**{k: v for k, v in row.items() if k != "_total"}) for row in rows], total=total, page=page, page_size=page_size)

    async def revisions(self, profile_id: uuid.UUID, *, page=1, page_size=25) -> VPNProfileRevisionPage:
        await self._owned(profile_id)
        statement = select(
            VPNProfileRevision.id, VPNProfileRevision.profile_id, VPNProfileRevision.revision,
            VPNProfileRevision.request_id, VPNProfileRevision.created_at,
            *(getattr(VPNProfileRevision, name) for name in _META),
        ).where(VPNProfileRevision.org_id == self.org_id, VPNProfileRevision.profile_id == profile_id)
        rows, total = await self._page(statement, page, page_size, ("revision",))
        return VPNProfileRevisionPage(items=[VPNProfileRevisionResponse(**{k: v for k, v in row.items() if k != "_total"}) for row in rows], total=total, page=page, page_size=page_size)

    async def archive(self, profile_id: uuid.UUID, expected_revision: int) -> VPNProfileResponse:
        profile = await self._owned(profile_id, lock=True)
        if profile.current_revision != expected_revision:
            raise HTTPException(409, "vpn_profile_revision_conflict")
        if not profile.is_archived:
            profile.is_archived = True
            self.db.add(AuditLog(org_id=self.org_id, user_id=self.user_id, action="vpn.profile.archived",
                                 resource_type="vpn_profile", resource_id=str(profile_id), meta={"revision": expected_revision}))
            await self.db.flush()
        return await self.get(profile_id)
