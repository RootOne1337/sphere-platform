"""Real PostgreSQL transactions, RLS login and concurrent import semantics."""
import asyncio
import json
import uuid

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import event, func, select, text

from backend.core.config import settings
from backend.database.tenant import bind_tenant_context
from backend.models.vpn_profile import VPNProfile, VPNProfileRevision
from backend.services.vpn.profile_catalog import VPNProfileCatalog
from tests.vpn.test_profile_catalog import import_payload, import_request
from tests.vpn.test_profile_preflight import KEY


@pytest.fixture
def profile_crypto(monkeypatch):
    monkeypatch.setattr(settings, "VPN_PROFILE_ENCRYPTION_KEYS", SecretStr(Fernet.generate_key().decode()))


async def create(world, data=None):
    response = await world.client.post("/api/v1/vpn/profiles", json=data or import_payload(), headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 200, response.text
    return response.json()


async def test_two_concurrent_creates_with_one_request_id_have_one_profile(world, profile_crypto):
    data = import_payload()
    responses = await asyncio.gather(*(world.client.post("/api/v1/vpn/profiles", json=data, headers=world.auth(world.users["org_admin"])) for _ in range(2)))
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    async with world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(VPNProfile).where(VPNProfile.org_id == world.org_a.id)) == 1
        assert await db.scalar(select(func.count()).select_from(VPNProfileRevision).where(VPNProfileRevision.org_id == world.org_a.id)) == 1


@pytest.mark.parametrize("same_request", [False, True])
async def test_concurrent_revisions_use_row_lock_and_expected_revision(world, profile_crypto, same_request):
    receipt = await create(world)
    path = f'/api/v1/vpn/profiles/{receipt["profile_id"]}/revisions'
    first = import_payload(expected_revision=1, name="Revision two")
    second = first if same_request else import_payload(expected_revision=1, name="Competing revision")
    replies = await asyncio.gather(*(world.client.post(path, json=body, headers=world.auth(world.users["org_admin"])) for body in [first, second]))
    assert sorted(r.status_code for r in replies) == ([200, 200] if same_request else [200, 409]), [r.text for r in replies]
    if same_request:
        assert replies[0].json() == replies[1].json()
    async with world.sessions() as db:
        profile_id = uuid.UUID(receipt["profile_id"])
        assert (await db.get(VPNProfile, profile_id)).current_revision == 2
        assert await db.scalar(select(func.count()).select_from(VPNProfileRevision).where(VPNProfileRevision.profile_id == profile_id)) == 2


async def test_context_bound_ciphertext_and_public_queries_never_read_it(world, profile_crypto):
    receipt = await create(world)
    statements = []

    def record(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(world.engine.sync_engine, "before_cursor_execute", record)
    try:
        paths = ["/api/v1/vpn/profiles", "/api/v1/vpn/profiles?page=100", f'/api/v1/vpn/profiles/{receipt["profile_id"]}',
                 f'/api/v1/vpn/profiles/{receipt["profile_id"]}/revisions', f'/api/v1/vpn/profiles/imports/{receipt["request_id"]}']
        for path in paths:
            response = await world.client.get(path, headers=world.auth(world.users["viewer"]))
            assert response.status_code == 200, response.text
            assert KEY not in response.text and "config_ciphertext" not in response.text
    finally:
        event.remove(world.engine.sync_engine, "before_cursor_execute", record)
    assert all("config_ciphertext" not in sql for sql in statements)
    async with world.sessions() as db:
        row = await db.get(VPNProfileRevision, uuid.UUID(receipt["revision_id"]))
        assert KEY.encode() not in row.config_ciphertext
        assert json.loads(Fernet(settings.VPN_PROFILE_ENCRYPTION_KEYS.get_secret_value().encode()).decrypt(row.config_ciphertext))["identity"]["org_id"] == str(world.org_a.id)


async def test_real_nonowner_rls_and_append_only_policy(world, runtime_db, profile_crypto):
    receipt = await create(world)
    profile_id, revision_id = uuid.UUID(receipt["profile_id"]), uuid.UUID(receipt["revision_id"])
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_b.id))
        assert await db.scalar(select(VPNProfile.id).where(VPNProfile.id == profile_id)) is None
        assert await db.scalar(select(VPNProfileRevision.id).where(VPNProfileRevision.id == revision_id)) is None
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        assert await db.scalar(select(VPNProfile.id).where(VPNProfile.id == profile_id)) == profile_id
        assert (await db.execute(text("UPDATE vpn_profile_revisions SET name='tampered' WHERE id=:id"), {"id": revision_id})).rowcount == 0
        assert (await db.execute(text("DELETE FROM vpn_profile_revisions WHERE id=:id"), {"id": revision_id})).rowcount == 0
        await db.commit()
    async with world.sessions() as db:
        assert (await db.get(VPNProfileRevision, revision_id)).name == "LAN test"
    response = await world.client.get(f'/api/v1/vpn/profiles/{profile_id}', headers=world.auth(world.users["foreign"]))
    assert response.status_code == 404


async def test_extra_permissive_policy_cannot_allow_revision_overwrite(world, runtime_db, profile_crypto):
    receipt = await create(world)
    policy = "audit_vpn_extra_" + world.suffix
    async with world.engine.begin() as db:
        await db.execute(text(f'CREATE POLICY "{policy}" ON vpn_profile_revisions FOR ALL USING (true) WITH CHECK (true)'))
    try:
        async with runtime_db.sessions() as db:
            await bind_tenant_context(db, str(world.org_a.id))
            assert (await db.execute(text("UPDATE vpn_profile_revisions SET name='overwritten' WHERE id=:id"), {"id": uuid.UUID(receipt["revision_id"])})).rowcount == 0
    finally:
        async with world.engine.begin() as db:
            await db.execute(text(f'DROP POLICY "{policy}" ON vpn_profile_revisions'))


async def test_archive_and_append_cannot_both_win_one_revision(world, profile_crypto):
    receipt = await create(world)
    base = f'/api/v1/vpn/profiles/{receipt["profile_id"]}'
    headers = world.auth(world.users["org_admin"])
    responses = await asyncio.gather(
        world.client.post(base + "/archive", json={"expected_revision": 1}, headers=headers),
        world.client.post(base + "/revisions", json=import_payload(expected_revision=1), headers=headers),
    )
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    current = (await world.client.get(base, headers=headers)).json()
    assert (current["current_revision"], current["is_archived"]) in [(1, True), (2, False)]


async def test_wrong_tenant_rejected_before_missing_crypto_key(world, profile_crypto, monkeypatch):
    async with world.sessions() as db:
        receipt = await VPNProfileCatalog(db, world.org_b.id, world.users["foreign"].id).save(import_request())
        await db.commit()
    monkeypatch.setattr(settings, "VPN_PROFILE_ENCRYPTION_KEYS", SecretStr(""))
    response = await world.client.post(f'/api/v1/vpn/profiles/{receipt.profile_id}/revisions',
                                       json=import_payload(expected_revision=1), headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 404


async def test_literal_search_and_out_of_range_total_are_owned(world, profile_crypto):
    await create(world, import_payload(name="Literal % _ test"))
    await create(world, import_payload(name="Other name"))
    headers = world.auth(world.users["viewer"])
    response = await world.client.get("/api/v1/vpn/profiles", params={"search": "% _", "page": 100}, headers=headers)
    assert response.json()["total"] == 1 and response.json()["items"] == []
    response = await world.client.get("/api/v1/vpn/profiles", headers=world.auth(world.users["foreign"]))
    assert response.json()["total"] == 0 and response.json()["items"] == []
