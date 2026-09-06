"""Opt-in PostgreSQL/Redis fixtures restricted to disposable local services."""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.core.security import create_access_token
from backend.database.engine import get_db
from backend.main import app
from backend.models import Device, Organization, User
from backend.models.script import Script, ScriptVersion


@pytest_asyncio.fixture
async def world():
    if os.environ.get("SPHERE_RUN_INTEGRATION") != "1":
        pytest.skip("Set SPHERE_RUN_INTEGRATION=1 with isolated PostgreSQL/Redis URLs")
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["POSTGRES_URL"])
    if not url.database or "audit" not in url.database:
        pytest.fail(
            "Integration tests require a disposable database containing 'audit' in its name"
        )
    engine = create_async_engine(os.environ["POSTGRES_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    from urllib.parse import urlparse

    if url.host not in {"127.0.0.1", "localhost", "::1"} or urlparse(
        os.environ["REDIS_URL"]
    ).hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Integration tests may connect only to loopback services")
    suffix = uuid.uuid4().hex
    async with sessions() as db:
        org_a = Organization(name="Audit A", slug="audit-a-" + suffix)
        org_b = Organization(name="Audit B", slug="audit-b-" + suffix)
        db.add_all([org_a, org_b])
        await db.flush()
        users = {}
        for role, org in [
            ("org_admin", org_a),
            ("viewer", org_a),
            ("org_owner", org_a),
            ("foreign", org_b),
        ]:
            user = User(
                org_id=org.id,
                email=f"{role}-{suffix}@example.org",
                password_hash="unused-local-fixture",
                role="viewer" if role == "foreign" else role,
            )
            db.add(user)
            users[role] = user
        dev_a = Device(org_id=org_a.id, name="audit-device-a")
        dev_a2 = Device(org_id=org_a.id, name="audit-device-a2")
        dev_b = Device(org_id=org_b.id, name="audit-device-b")
        script = Script(org_id=org_a.id, name="audit-script")
        db.add_all([dev_a, dev_a2, dev_b, script])
        await db.flush()
        version = ScriptVersion(
            org_id=org_a.id, script_id=script.id, dag={"nodes": [], "entry_node": "start"}
        )
        db.add(version)
        await db.flush()
        script.current_version_id = version.id
        await db.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    def auth(user):
        token, _ = create_access_token(
            subject=str(user.id), org_id=str(user.org_id), role=user.role
        )
        return {"Authorization": "Bearer " + token}

    with (
        patch("backend.services.cache_service.get_redis", AsyncMock(return_value=redis)),
        patch("backend.middleware.audit.AsyncSessionLocal", sessions),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
            base_url="http://audit.local",
        ) as client:
            yield SimpleNamespace(**locals())
    app.dependency_overrides.clear()
    # Global VPN uniqueness makes fixture cleanup necessary across test worlds.
    # Delete only peers owned by the two UUID organizations created above.
    from sqlalchemy import delete

    from backend.models.vpn_peer import VPNPeer

    async with sessions() as cleanup:
        await cleanup.execute(delete(VPNPeer).where(VPNPeer.org_id.in_([org_a.id, org_b.id])))
        await cleanup.commit()
    await redis.aclose()
    await engine.dispose()
