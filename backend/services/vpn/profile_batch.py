"""Atomic catalog import and read-only recovery, never device dispatch or network probes."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from backend.models.vpn_profile import VPNProfileRevision
from backend.schemas.vpn.bulk_profiles import (
    VPNProfileBatchInspection,
    VPNProfileBatchInspectionItem,
    VPNProfileBatchRequest,
    VPNProfileBatchSaveResponse,
    VPNProfileBatchStatusItem,
    VPNProfileBatchStatusRequest,
    VPNProfileBatchStatusResponse,
)
from backend.schemas.vpn.catalog import VPNProfileSaveResponse
from backend.services.vpn.profile_catalog import VPNProfileCatalog
from backend.services.vpn.profile_preflight import preflight_profile


def inspect_batch(request: VPNProfileBatchRequest) -> VPNProfileBatchInspection:
    items = []
    for item in request.items:
        result = preflight_profile(item.profile)
        items.append(VPNProfileBatchInspectionItem(request_id=item.request_id, config_valid=result.config_valid, issues=result.issues))
    return VPNProfileBatchInspection(items=items, config_valid=all(item.config_valid for item in items))


async def save_batch(catalog: VPNProfileCatalog, request: VPNProfileBatchRequest) -> VPNProfileBatchSaveResponse:
    inspection = inspect_batch(request)
    if not inspection.config_valid:
        raise HTTPException(422, {"code": "invalid_vpn_profile_batch", "items": inspection.model_dump(mode="json")["items"]})
    receipts = {}
    # Stable lock/unique-index acquisition order for overlapping concurrent batches.
    # One outer savepoint also rolls back earlier rows/audits after a late conflict.
    async with catalog.db.begin_nested():
        for item in sorted(request.items, key=lambda item: item.request_id.int):
            receipts[item.request_id] = await catalog.save(item)
    return VPNProfileBatchSaveResponse(items=[receipts[item.request_id] for item in request.items])


async def batch_status(catalog: VPNProfileCatalog, request: VPNProfileBatchStatusRequest) -> VPNProfileBatchStatusResponse:
    rows = (await catalog.db.execute(select(
        VPNProfileRevision.profile_id, VPNProfileRevision.id.label("revision_id"),
        VPNProfileRevision.revision, VPNProfileRevision.request_id,
    ).where(VPNProfileRevision.org_id == catalog.org_id, VPNProfileRevision.request_id.in_(request.request_ids)))).mappings().all()
    observed = {row["request_id"]: VPNProfileSaveResponse(**row) for row in rows}
    # Null means unobserved in this snapshot, never cancelled/failed. No auto-resubmit.
    return VPNProfileBatchStatusResponse(items=[VPNProfileBatchStatusItem(request_id=item, receipt=observed.get(item)) for item in request.request_ids])
