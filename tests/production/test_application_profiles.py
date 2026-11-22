"""Application catalog behavior through the authenticated API and runtime DB role."""

import asyncio

from sqlalchemy import text

from backend.database.engine import get_db
from backend.main import app
from backend.models import ApplicationProfile, User
from backend.schemas.application_profiles import MAX_PROFILES

CATALOG = "/api/v1/application-profiles"
ACCOUNTS = "/api/v1/game-accounts"
SERVER = {"key": "alpha", "name": "Alpha", "domain": "Game.Example.Test.", "port": 9001}
PROFILE = {"key": "arena", "name": "Arena", "android_package": "test.example.arena", "servers": [SERVER]}


async def test_catalog_scope_and_minimal_acl(world, runtime_db):
    async with world.sessions() as db:
        foreign_admin = User(
            org_id=world.org_b.id, email=f"admin-b-{world.suffix}@example.org",
            password_hash="unused-local-fixture", role="org_admin",
        )
        db.add(foreign_admin)
        await db.commit()

    role = runtime_db.role
    async with world.engine.begin() as db:
        await db.execute(text(f'REVOKE ALL ON TABLE public.application_profiles FROM "{role}"'))

    async def override_db():
        async with runtime_db.sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    admin = world.auth(world.users["org_admin"])
    viewer = world.auth(world.users["viewer"])
    foreign = world.auth(foreign_admin)

    assert (await world.client.get(CATALOG, headers=admin)).status_code == 503
    assert (await world.client.get(f"{ACCOUNTS}/servers", headers=admin)).status_code == 200
    async with world.engine.begin() as db:
        await db.execute(text(f'GRANT SELECT, INSERT, UPDATE ON TABLE public.application_profiles TO "{role}"'))

    async with runtime_db.engine.connect() as db:
        flags = (await db.execute(text("""
            SELECT row_security_active('public.application_profiles'),
                   has_table_privilege('public.application_profiles', 'DELETE'),
                   has_table_privilege('public.application_profiles', 'TRUNCATE')
        """))).one()
        assert tuple(flags) == (True, False, False)

    assert (await world.client.get(CATALOG)).status_code == 401
    listing = await world.client.get(CATALOG, headers=viewer)
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    builtin = listing.json()["items"][0]
    assert builtin["source"] == "builtin"
    assert builtin["key"] == "black-russia"
    assert set(builtin["aliases"]) == {"black_russia", "com.br.top"}
    legacy = (await world.client.get(f"{ACCOUNTS}/servers", headers=viewer)).json()
    assert legacy["total"] == len(builtin["servers"]) == 90
    assert [row["name"] for row in legacy["servers"]] == [row["name"] for row in builtin["servers"]]

    assert (await world.client.post(CATALOG, headers=viewer, json=PROFILE)).status_code == 403
    created = await world.client.post(CATALOG, headers=admin, json=PROFILE)
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["source"] == "tenant"
    assert profile["aliases"] == []
    assert profile["servers"] == [{**SERVER, "domain": "game.example.test"}]
    assert (await world.client.get(CATALOG, headers=admin)).json()["total"] == 2
    assert (await world.client.get(CATALOG, headers=foreign)).json()["total"] == 1
    path = f"{CATALOG}/{profile['id']}"
    patch = {"expected_updated_at": profile["updated_at"], "name": "Updated Arena"}
    assert (await world.client.patch(path, headers=viewer, json=patch)).status_code == 403
    assert (await world.client.patch(path, headers=foreign, json=patch)).status_code == 404
    assert (await world.client.patch(f"{CATALOG}/{builtin['id']}", headers=admin, json=patch)).status_code == 409
    saved = await world.client.patch(path, headers=admin, json=patch)
    assert saved.status_code == 200, saved.text
    assert saved.json()["name"] == "Updated Arena"
    same_key = await world.client.post(CATALOG, headers=foreign, json=PROFILE)
    assert same_key.status_code == 201, same_key.text
    assert same_key.json()["id"] != profile["id"]
    async with runtime_db.engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM public.application_profiles")) == 0


async def test_patch_version_and_legacy_account_values(world, account_credential_key):
    admin = world.auth(world.users["org_admin"])
    for game in ("com.br.top", "black_russia", "legacy-custom", PROFILE["key"]):
        saved = await world.client.post(
            ACCOUNTS, headers=admin,
            json={"game": game, "login": f"fixture-{game}", "password": "fixture-only", "server_name": SERVER["name"]},
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["game"] == game

    for key in ("black-russia", "black_russia"):
        reserved = await world.client.post(CATALOG, headers=admin, json={**PROFILE, "key": key})
        assert reserved.status_code == 409, reserved.text
    assert (await world.client.post(CATALOG, headers=admin, json={**PROFILE, "key": "com.br.top"})).status_code == 422

    results = await asyncio.gather(*(world.client.post(CATALOG, headers=admin, json=PROFILE) for _ in range(2)))
    assert sorted(response.status_code for response in results) == [201, 409]
    profile = next(response.json() for response in results if response.status_code == 201)
    path = f"{CATALOG}/{profile['id']}"
    expected = {"expected_updated_at": profile["updated_at"]}

    for patch, status in [
        ({"servers": []}, 409),
        ({"servers": [{**SERVER, "name": "Renamed"}]}, 409),
        ({"servers": [{**SERVER, "key": "renamed"}]}, 409),
        ({"servers": [SERVER, {**SERVER, "key": "another", "name": "ALPHA"}]}, 422),
        ({"servers": [{**SERVER, "domain": "http://game.example.test"}]}, 422),
        ({"servers": [{**SERVER, "port": 65536}]}, 422),
        ({"servers": [{**SERVER, "port": True}]}, 422),
        ({"android_package": "test.invalid-package"}, 422),
        ({"android_package": "test._invalid_package"}, 422),
        ({"key": "replacement"}, 422),
        ({"name": None}, 422),
        ({}, 422),
    ]:
        response = await world.client.patch(path, headers=admin, json={**expected, **patch})
        assert response.status_code == status, response.text

    server_changes = [
        {**SERVER, "domain": "new.example.test", "port": 9010},
        {"key": "beta", "name": "Beta", "domain": "beta.example.test", "port": 9002},
    ]
    saved = await world.client.patch(
        path, headers=admin, json={**expected, "android_package": None, "servers": server_changes},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["android_package"] is None
    assert saved.json()["servers"] == server_changes
    assert saved.json()["updated_at"] != profile["updated_at"]

    stale = await world.client.patch(path, headers=admin, json={**expected, "name": "Stale"})
    assert stale.status_code == 409
    expected = {"expected_updated_at": saved.json()["updated_at"]}
    races = await asyncio.gather(*(world.client.patch(
        path, headers=admin, json={**expected, "name": name},
    ) for name in ("First", "Second")))
    assert sorted(response.status_code for response in races) == [200, 409]

    accounts = await world.client.get(ACCOUNTS, headers=admin)
    assert accounts.status_code == 200, accounts.text
    assert {(row["game"], row["server_name"]) for row in accounts.json()["items"]} == {
        (game, SERVER["name"]) for game in ("com.br.top", "black_russia", "legacy-custom", PROFILE["key"])
    }


async def test_concurrent_creates_cannot_exceed_catalog_limit(world):
    async with world.sessions() as db:
        db.add_all(
            ApplicationProfile(org_id=world.org_a.id, key=f"fixture-{i}", name=f"Fixture {i}")
            for i in range(MAX_PROFILES - 2)
        )
        await db.commit()

    admin = world.auth(world.users["org_admin"])
    responses = await asyncio.gather(*(world.client.post(
        CATALOG, headers=admin, json={**PROFILE, "key": key},
    ) for key in ("first-new", "second-new")))
    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["detail"] == "Application catalog is full"
    listing = await world.client.get(CATALOG, headers=admin)
    assert listing.status_code == 200, listing.text
    assert len(listing.json()["items"]) == listing.json()["total"] == MAX_PROFILES
