"""Account appearance isolation and conditional saves on the restricted runtime role."""

import pytest_asyncio
from sqlalchemy import text

from backend.database.engine import get_db
from backend.main import app

PATH = "/api/v1/user-preferences/me"


@pytest_asyncio.fixture
async def preferences_world(runtime_db):
    async def runtime_session():
        async with runtime_db.sessions() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = runtime_session
    try:
        yield runtime_db
    finally:
        app.dependency_overrides[get_db] = previous


async def test_preferences_round_trip_account_scope_and_preconditions(preferences_world):
    runtime = preferences_world
    world = runtime.world
    editor = world.auth(world.users["org_admin"])

    assert (await world.client.get(PATH)).status_code == 401
    first = await world.client.get(PATH, headers=editor)
    assert first.status_code == 200, first.text
    assert first.headers["etag"] == '"ui-0"'
    assert first.headers["cache-control"] == "private, no-store"
    assert first.json()["appearance"]["palette"] == "neo-dark"
    assert first.json()["org_id"] == str(world.org_a.id)
    assert first.json()["user_id"] == str(world.users["org_admin"].id)

    async with runtime.sessions() as db:
        assert await db.scalar(text("SELECT row_security_active('user_preferences')")) is True
        assert await db.scalar(text("SELECT count(*) FROM user_preferences")) == 0

    assert (await world.client.patch(PATH, headers=editor, json={"palette": "mist"})).status_code == 428
    assert (await world.client.patch(PATH, headers=editor | {"If-Match": "*"}, json={"palette": "mist"})).status_code == 400
    for invalid in ({}, {"palette": None}, {"org_id": str(world.org_b.id)}, {"palette": "unknown"}):
        rejected = await world.client.patch(PATH, headers=editor | {"If-Match": '"ui-0"'}, json=invalid)
        assert rejected.status_code == 422, rejected.text

    saved = await world.client.patch(PATH, headers=editor | {"If-Match": '"ui-0"'}, json={"palette": "mist"})
    assert saved.status_code == 200, saved.text
    assert saved.headers["etag"] == '"ui-1"'
    assert saved.json()["appearance"]["density"] == "cozy"
    assert saved.json()["appearance"]["palette"] == "mist"
    stale = await world.client.patch(PATH, headers=editor | {"If-Match": '"ui-0"'}, json={"palette": "dune"})
    assert stale.status_code == 412, stale.text
    updated = await world.client.patch(PATH, headers=editor | {"If-Match": '"ui-1"'}, json={"density": "compact"})
    assert updated.status_code == 200, updated.text
    assert updated.headers["etag"] == '"ui-2"'
    assert updated.json()["appearance"]["palette"] == "mist"
    assert updated.json()["appearance"]["density"] == "compact"

    for identity in ("viewer", "foreign"):
        isolated = await world.client.get(PATH, headers=world.auth(world.users[identity]))
        assert isolated.status_code == 200, isolated.text
        assert isolated.headers["etag"] == '"ui-0"'
        assert isolated.json()["appearance"]["palette"] == "neo-dark"

    async with runtime.sessions() as db:
        assert await db.scalar(text("SELECT count(*) FROM user_preferences")) == 0
        await db.execute(text("SELECT set_config('app.current_org_id', :org, true)"), {"org": str(world.org_b.id)})
        assert await db.scalar(text("SELECT count(*) FROM user_preferences")) == 0
        await db.execute(text("SELECT set_config('app.current_org_id', :org, true)"), {"org": str(world.org_a.id)})
        assert await db.scalar(text("SELECT count(*) FROM user_preferences")) == 1
