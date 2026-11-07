from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, func, select

from backend.core.config import settings
from backend.models.audit_log import AuditLog
from backend.models.vpn_profile import VPNProfile, VPNProfileRevision
from backend.schemas.vpn.catalog import VPNProfileAppendRequest, VPNProfileImportRequest
from backend.services.vpn.profile_catalog import VPNProfileCatalog
from backend.services.vpn.profile_secrets import decrypt_revision
from tests.vpn.test_profile_preflight import CONFIG, KEY, payload


def import_payload(**extra):
    return {"request_id": str(uuid.uuid4()), "name": "LAN test", "description": "Only selected applications", "profile": payload(), **extra}


def import_request(**extra):
    return VPNProfileImportRequest.model_validate_json(json.dumps(import_payload(**extra)))


@pytest.fixture
def profile_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "VPN_PROFILE_ENCRYPTION_KEYS", SecretStr(key))
    return key


@pytest.fixture
def catalog(db_session, test_org, test_user, profile_key):
    return VPNProfileCatalog(db_session, test_org.id, test_user.id)


@pytest_asyncio.fixture
async def profile_http(db_session, test_org, test_user, profile_key):
    from backend.core.dependencies import get_current_user
    from backend.database.engine import get_db
    from backend.main import app
    from backend.services.vpn.catalog_database import get_vpn_catalog_db

    principal = SimpleNamespace(id=test_user.id, org_id=test_org.id, role="org_admin", email="test@example.org")
    previous = dict(app.dependency_overrides)

    async def session():
        yield db_session

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_vpn_catalog_db] = session
    app.dependency_overrides[get_current_user] = lambda: principal
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            yield client, principal
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.asyncio
async def test_encrypted_append_only_versions_and_old_request_replay(catalog):
    first_request = import_request()
    first = await catalog.save(first_request)
    stored = await catalog.db.get(VPNProfileRevision, first.revision_id)
    assert KEY.encode() not in stored.config_ciphertext
    assert CONFIG == decrypt_revision(stored)[0]
    second = await catalog.save(VPNProfileAppendRequest.model_validate_json(json.dumps(import_payload(
        name="Updated profile", expected_revision=1,
        profile=payload(CONFIG.replace("vpn.example:51820", "other.example:443")),
    ))), first.profile_id)
    assert second.revision == 2
    assert await catalog.save(first_request) == first
    assert (await catalog.get(first.profile_id)).current_revision == 2
    assert (await catalog.get(first.profile_id)).name == "Updated profile"
    history = await catalog.revisions(first.profile_id)
    assert [r.revision for r in history.items] == [2, 1]
    assert history.items[1].name == "LAN test"
    assert "config_ciphertext" not in history.model_dump_json() and KEY not in history.model_dump_json()
    assert decrypt_revision(stored)[0] == CONFIG
    assert not first.apply_allowed and first.persisted and not first.execution_confirmed


@pytest.mark.asyncio
async def test_retry_id_must_bind_the_exact_request(catalog):
    request = import_request()
    receipt = await catalog.save(request)
    assert await catalog.save(request) == receipt
    modified = import_request(request_id=str(request.request_id), name="Different intent")
    with pytest.raises(HTTPException) as failure:
        await catalog.save(modified)
    assert failure.value.status_code == 409
    assert await catalog.db.scalar(select(func.count()).select_from(VPNProfile)) == 1
    assert await catalog.db.scalar(select(func.count()).select_from(VPNProfileRevision)) == 1


@pytest.mark.asyncio
async def test_v2_scope_survives_encryption_catalog_and_replay_without_a_package_snapshot(catalog):
    policy = {"mode": "all_apps_except_control", "control_plane": "bypass", "kill_switch": "all_apps_except_control", "ipv6": "block"}
    request = import_request(profile=payload(schema_version=2, traffic_policy=policy))
    receipt = await catalog.save(request)
    stored = await catalog.db.get(VPNProfileRevision, receipt.revision_id)
    assert stored.schema_version == 2 and stored.traffic_policy == policy
    assert decrypt_revision(stored)[0] == CONFIG and KEY.encode() not in stored.config_ciphertext
    assert (await catalog.get(receipt.profile_id)).traffic_policy.model_dump() == policy
    assert await catalog.save(request) == receipt
    assert not receipt.apply_allowed and not receipt.execution_confirmed


@pytest.mark.asyncio
async def test_stale_revision_and_archive_do_not_overwrite(catalog):
    first = await catalog.save(import_request())
    request = VPNProfileAppendRequest.model_validate_json(json.dumps(import_payload(expected_revision=1)))
    await catalog.save(request, first.profile_id)
    with pytest.raises(HTTPException, match="vpn_profile_revision_conflict"):
        await catalog.save(VPNProfileAppendRequest.model_validate_json(json.dumps(import_payload(expected_revision=1))), first.profile_id)
    with pytest.raises(HTTPException, match="vpn_profile_revision_conflict"):
        await catalog.archive(first.profile_id, 1)
    archived = await catalog.archive(first.profile_id, 2)
    assert archived.is_archived
    assert (await catalog.archive(first.profile_id, 2)).is_archived
    assert (await catalog.list()).total == 0
    assert (await catalog.list(include_archived=True)).total == 1
    assert (await catalog.revisions(first.profile_id)).total == 2
    with pytest.raises(HTTPException, match="vpn_profile_archived"):
        await catalog.save(VPNProfileAppendRequest.model_validate_json(json.dumps(import_payload(expected_revision=2))), first.profile_id)


@pytest.mark.asyncio
async def test_missing_keys_fail_before_catalog_changes_but_metadata_remains_readable(catalog, monkeypatch):
    first = await catalog.save(import_request())
    monkeypatch.setattr(settings, "VPN_PROFILE_ENCRYPTION_KEYS", SecretStr(""))
    assert (await catalog.list()).total == 1
    assert (await catalog.get(first.profile_id)).current_revision == 1
    assert (await catalog.revisions(first.profile_id)).total == 1
    with pytest.raises(HTTPException) as failure:
        await catalog.save(import_request())
    assert failure.value.status_code == 503
    assert (await catalog.list()).total == 1


@pytest.mark.asyncio
async def test_key_ring_rotation_and_ciphertext_context_binding(catalog, profile_key, monkeypatch):
    first = await catalog.save(import_request())
    row = await catalog.db.get(VPNProfileRevision, first.revision_id)
    second_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "VPN_PROFILE_ENCRYPTION_KEYS", SecretStr(second_key + "," + profile_key))
    assert decrypt_revision(row)[0] == CONFIG
    old_id = row.profile_id
    row.profile_id = uuid.uuid4()
    with pytest.raises(HTTPException) as failure:
        decrypt_revision(row)
    assert failure.value.status_code == 503
    row.profile_id = old_id
    monkeypatch.setattr(settings, "VPN_PROFILE_ENCRYPTION_KEYS", SecretStr(second_key))
    with pytest.raises(HTTPException):
        decrypt_revision(row)


@pytest.mark.asyncio
async def test_other_tenant_cannot_read_update_archive_or_probe_import(catalog):
    first = await catalog.save(import_request())
    other = VPNProfileCatalog(catalog.db, uuid.uuid4(), catalog.user_id)
    assert (await other.list()).total == 0
    for action in [other.get(first.profile_id), other.revisions(first.profile_id), other.archive(first.profile_id, 1),
                   other.import_status(first.request_id), other.save(VPNProfileAppendRequest.model_validate_json(json.dumps(import_payload(expected_revision=1))), first.profile_id)]:
        with pytest.raises(HTTPException) as failure:
            await action
        assert failure.value.status_code == 404


@pytest.mark.asyncio
async def test_metadata_queries_never_select_the_encrypted_config(catalog):
    first = await catalog.save(import_request())
    statements = []

    def record(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    engine = catalog.db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert (await catalog.list()).total == 1
        assert (await catalog.list(page=100)).items == []
        assert (await catalog.list(page=100)).total == 1
        assert (await catalog.get(first.profile_id)).id == first.profile_id
        assert (await catalog.revisions(first.profile_id)).total == 1
        assert await catalog.import_status(first.request_id) == first
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert all("config_ciphertext" not in sql for sql in statements)


@pytest.mark.asyncio
async def test_audit_records_only_identifiers(catalog):
    await catalog.save(import_request())
    rows = (await catalog.db.scalars(select(AuditLog).where(AuditLog.action == "vpn.profile.created"))).all()
    assert len(rows) == 1 and set(rows[0].meta) == {"revision", "revision_id", "request_id"}
    assert KEY not in json.dumps(rows[0].meta)


@pytest.mark.asyncio
async def test_invalid_configuration_never_persists(catalog):
    with pytest.raises(HTTPException) as failure:
        await catalog.save(import_request(profile=payload(CONFIG.replace("[Peer]", "PostUp = secret-sentinel\n[Peer]"))))
    assert failure.value.status_code == 422
    assert "secret-sentinel" not in json.dumps(failure.value.detail)
    assert (await catalog.list()).total == 0


@pytest.mark.asyncio
async def test_api_import_history_status_conflicts_and_permissions(profile_http):
    client, principal = profile_http
    data = import_payload()
    first = await client.post("/api/v1/vpn/profiles", json=data)
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert receipt["persisted"] and not receipt["apply_allowed"]
    assert (await client.post("/api/v1/vpn/profiles", json=data)).json() == receipt
    assert (await client.get(f'/api/v1/vpn/profiles/imports/{data["request_id"]}')).json() == receipt
    profile_id = receipt["profile_id"]
    listed = await client.get("/api/v1/vpn/profiles")
    assert listed.status_code == 200 and listed.json()["items"][0]["id"] == profile_id
    revised = await client.post(f"/api/v1/vpn/profiles/{profile_id}/revisions", json=import_payload(expected_revision=1))
    assert revised.status_code == 200 and revised.json()["revision"] == 2
    assert (await client.post(f"/api/v1/vpn/profiles/{profile_id}/archive", json={"expected_revision": 1})).status_code == 409
    history = await client.get(f"/api/v1/vpn/profiles/{profile_id}/revisions")
    assert [v["revision"] for v in history.json()["items"]] == [2, 1]
    assert KEY not in history.text and "ciphertext" not in history.text
    principal.role = "viewer"
    assert (await client.get("/api/v1/vpn/profiles")).status_code == 200
    assert (await client.post("/api/v1/vpn/profiles", json=import_payload())).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"config_text": "secret-sentinel"}, import_payload(request_id="secret-sentinel"),
    import_payload(profile={**payload(), "extra": "secret-sentinel"}), import_payload(name=" " * 5)])
async def test_secret_bearing_api_validation_is_sanitized(profile_http, bad):
    client, _ = profile_http
    response = await client.post("/api/v1/vpn/profiles", json=bad)
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_vpn_profile_request"}
    assert "secret-sentinel" not in response.text and KEY not in response.text
