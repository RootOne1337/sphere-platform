from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.models.audit_log import AuditLog
from backend.schemas.vpn.bulk_profiles import VPNProfileBatchRequest, VPNProfileBatchStatusRequest
from backend.services.vpn.profile_batch import batch_status, inspect_batch, save_batch
from backend.services.vpn.profile_catalog import VPNProfileCatalog
from tests.vpn.test_profile_catalog import (  # noqa: F401
    catalog,
    import_payload,
    import_request,
    profile_http,
    profile_key,
)
from tests.vpn.test_profile_preflight import CONFIG, KEY, payload


def batch(*items):
    return VPNProfileBatchRequest.model_validate_json(json.dumps({"items": items}))


@pytest.mark.asyncio
async def test_hundred_profiles_atomic_replay_order_encryption_and_audits(catalog):
    request = batch(*(import_payload(name=f"Exit {i}") for i in range(100)))
    first = await save_batch(catalog, request)
    assert len(first.items) == 100
    assert [r.request_id for r in first.items] == [r.request_id for r in request.items]
    assert not first.apply_allowed and not first.execution_confirmed and first.persisted
    assert await save_batch(catalog, request) == first
    assert (await catalog.list()).total == 100
    assert await catalog.db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "vpn.profile.created")) == 100
    assert KEY not in first.model_dump_json() and "config_text" not in first.model_dump_json()


@pytest.mark.asyncio
async def test_late_conflict_rolls_back_all_new_profiles_and_audits(catalog):
    existing = import_request(request_id=str(uuid.UUID(int=100)))
    await catalog.save(existing)
    request = batch(import_payload(request_id=str(uuid.UUID(int=1))),
                    import_payload(request_id=str(existing.request_id), name="Conflicting intent"))
    with pytest.raises(HTTPException) as failure:
        await save_batch(catalog, request)
    assert failure.value.status_code == 409
    assert (await catalog.list()).total == 1
    assert await catalog.db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "vpn.profile.created")) == 1


@pytest.mark.asyncio
async def test_invalid_late_file_is_reported_without_saving_anything(catalog):
    request = batch(import_payload(), import_payload(profile=payload(CONFIG + "\nPostUp = secret-sentinel")))
    inspected = inspect_batch(request)
    assert not inspected.config_valid and not inspected.persisted
    assert inspected.items[0].config_valid and not inspected.items[1].config_valid
    assert "secret-sentinel" not in inspected.model_dump_json() and KEY not in inspected.model_dump_json()
    with pytest.raises(HTTPException) as failure:
        await save_batch(catalog, request)
    assert failure.value.status_code == 422
    assert (await catalog.list()).total == 0


@pytest.mark.asyncio
async def test_status_is_metadata_only_tenant_scoped_and_missing_is_unknown(catalog):
    first = await catalog.save(import_request())
    request = VPNProfileBatchStatusRequest(request_ids=[uuid.uuid4(), first.request_id])
    report = await batch_status(catalog, request)
    assert report.items[0].receipt is None and report.items[1].receipt == first
    other = VPNProfileCatalog(catalog.db, uuid.uuid4(), catalog.user_id)
    assert all(item.receipt is None for item in (await batch_status(other, request)).items)
    assert KEY not in report.model_dump_json() and "ciphertext" not in report.model_dump_json()


@pytest.mark.parametrize("items", [[], [import_payload()] * 2, [import_payload() for _ in range(101)]])
def test_batch_limits_and_duplicate_item_identity(items):
    with pytest.raises(ValidationError):
        batch(*items)


@pytest.mark.asyncio
async def test_http_batch_preflight_save_status_and_rbac(profile_http):
    client, principal = profile_http
    data = {"items": [import_payload(), import_payload()]}
    inspected = await client.post("/api/v1/vpn/profiles/batch/preflight", json=data)
    assert inspected.status_code == 200 and inspected.json()["config_valid"]
    assert (await client.get("/api/v1/vpn/profiles")).json()["total"] == 0
    result = await client.post("/api/v1/vpn/profiles/batch", json=data)
    assert result.status_code == 200, result.text
    assert (await client.post("/api/v1/vpn/profiles/batch", json=data)).json() == result.json()
    query = {"request_ids": [item["request_id"] for item in data["items"]]}
    principal.role = "viewer"
    status = await client.post("/api/v1/vpn/profiles/batch/status", json=query)
    assert status.status_code == 200
    assert [row["receipt"] for row in status.json()["items"]] == result.json()["items"]
    for path in ("batch", "batch/preflight"):
        assert (await client.post("/api/v1/vpn/profiles/" + path, json=data)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["batch", "batch/preflight", "batch/status"])
async def test_batch_validation_never_echoes_input(profile_http, path):
    client, _ = profile_http
    result = await client.post("/api/v1/vpn/profiles/" + path, json={"items": [{"private_key": "secret-sentinel"}]})
    assert result.status_code == 422
    assert result.json() == {"detail": "invalid_vpn_profile_request"}


@pytest.mark.asyncio
async def test_bulk_body_budget_is_enforced_on_stream_without_content_length(profile_http):
    client, _ = profile_http

    async def chunks():
        for _ in range(65):
            yield b" " * 65536

    result = await client.post("/api/v1/vpn/profiles/batch", content=chunks())
    assert result.status_code == 413
