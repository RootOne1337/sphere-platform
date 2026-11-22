"""Exercise the shipped enrollment CLI with real isolated PostgreSQL/HTTP."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from backend.core.config import settings
from backend.models import APIKey, Device, Organization, User
from backend.services.cache_service import CacheService
from scripts import seed_enrollment_key


@pytest_asyncio.fixture
async def pilot(world, monkeypatch, tmp_path):
    original_rate_limit = CacheService.check_rate_limit

    async def isolated_rate_limit(self, identifier, **kwargs):
        return await original_rate_limit(self, world.suffix + ":" + identifier, **kwargs)

    # Preserve real Redis/limit behavior, isolate synthetic clients between cases/runs.
    monkeypatch.setattr(CacheService, "check_rate_limit", isolated_rate_limit)
    raw = "sphr_pilot_" + world.suffix
    config = tmp_path / "environments" / "development.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"enrollment_api_key": raw}), encoding="utf-8")
    monkeypatch.setattr(settings, "AGENT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AGENT_CONFIG_ENV", "development")
    monkeypatch.setenv("SPHERE_BOOTSTRAP_ORG_SLUG", world.org_a.slug)
    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", world.sessions)
    return world, raw, config


async def stored(pilot):
    w, raw, _ = pilot
    async with w.sessions() as db:
        return await db.scalar(select(APIKey).where(APIKey.key_hash == hashlib.sha256(raw.encode()).hexdigest()))


async def test_shipped_seed_runs_and_device_is_visible_to_the_intended_operator(pilot):
    w, raw, _ = pilot
    await seed_enrollment_key.main()
    key = await stored(pilot)
    assert key.org_id == w.org_a.id
    assert key.type == "agent"
    response = await w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw},
        json={"fingerprint": "pilot-" + w.suffix})
    assert response.status_code == 201, response.text
    device_id = response.json()["device_id"]
    listed = await w.client.get("/api/v1/devices/" + device_id, headers=w.auth(w.users["org_admin"]))
    assert listed.status_code == 200, listed.text
    denied = await w.client.get("/api/v1/devices/" + device_id, headers=w.auth(w.users["foreign"]))
    assert denied.status_code in (403, 404)
    async with w.sessions() as db:
        assert await db.scalar(select(Device.org_id).where(Device.meta["fingerprint"].as_string() == "pilot-" + w.suffix)) == w.org_a.id


async def test_repeated_seed_reuses_one_key_without_printing_key_material(pilot, capsys):
    _, raw, _ = pilot
    await seed_enrollment_key.main()
    first = await stored(pilot)
    await seed_enrollment_key.main()
    assert (await stored(pilot)).id == first.id
    output = capsys.readouterr().out
    assert raw not in output
    assert raw[:20] not in output
    assert hashlib.sha256(raw.encode()).hexdigest()[:16] not in output


@pytest.mark.parametrize("change", ["revoked", "expired", "permissions", "organization"])
async def test_retry_does_not_silently_reactivate_or_rebind_an_existing_key(pilot, change):
    w, _, _ = pilot
    await seed_enrollment_key.main()
    key = await stored(pilot)
    values = {
        "revoked": {"is_active": False},
        "expired": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
        "permissions": {"permissions": []},
        "organization": {"org_id": w.org_b.id},
    }[change]
    async with w.sessions() as db:
        await db.execute(update(APIKey).where(APIKey.id == key.id).values(**values))
        await db.commit()
    with pytest.raises(RuntimeError):
        await seed_enrollment_key.main()
    current = await stored(pilot)
    for name, expected in values.items():
        assert getattr(current, name) == expected


async def test_missing_key_is_a_bootstrap_failure_not_reported_success(pilot):
    _, _, config = pilot
    config.write_text("{}", encoding="utf-8")
    with pytest.raises((RuntimeError, ValueError)):
        await seed_enrollment_key.main()
    assert await stored(pilot) is None


async def test_missing_operator_organization_does_not_create_an_unrelated_tenant(pilot, monkeypatch):
    w, _, _ = pilot
    monkeypatch.setenv("SPHERE_BOOTSTRAP_ORG_SLUG", "absent-" + w.suffix)
    async with w.sessions() as db:
        before = await db.scalar(select(func.count()).select_from(Organization))
    with pytest.raises(RuntimeError):
        await seed_enrollment_key.main()
    async with w.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Organization)) == before
    assert await stored(pilot) is None


async def test_two_seed_process_flows_converge_on_one_key(pilot):
    w, raw, _ = pilot
    await asyncio.wait_for(asyncio.gather(seed_enrollment_key.main(), seed_enrollment_key.main()), 5)
    async with w.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(APIKey).where(APIKey.key_hash == hashlib.sha256(raw.encode()).hexdigest())) == 1


async def admin_cli(pilot, email, slug, password="isolated-pilot-password"):
    w, _, _ = pilot
    environment = os.environ.copy()
    environment.update(POSTGRES_URL=w.engine.url.render_as_string(hide_password=False),
        ADMIN_EMAIL=email, ADMIN_PASSWORD=password, SPHERE_BOOTSTRAP_ORG_SLUG=slug)
    return await asyncio.to_thread(subprocess.run,
        [sys.executable, "scripts/create_admin.py"], cwd=Path(__file__).resolve().parents[2],
        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)


@pytest.mark.parametrize("mode", ["new_user", "existing_user", "new_organization"])
async def test_actual_admin_cli_login_and_enrollment_share_one_organization(pilot, mode, monkeypatch):
    w, raw, _ = pilot
    email = w.users["org_admin"].email if mode == "existing_user" else "pilot-" + w.suffix + "@example.org"
    slug = "pilot-new-" + w.suffix if mode == "new_organization" else w.org_a.slug
    monkeypatch.setenv("SPHERE_BOOTSTRAP_ORG_SLUG", slug)
    result = await admin_cli(pilot, email, slug)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "isolated-pilot-password" not in result.stdout
    login = await w.client.post("/api/v1/auth/login", json={"email": email, "password": "isolated-pilot-password"})
    assert login.status_code == 200, login.text
    await seed_enrollment_key.main()
    response = await w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw},
        json={"fingerprint": "login-pilot-" + w.suffix})
    assert response.status_code == 201, response.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    visible = await w.client.get("/api/v1/devices/" + response.json()["device_id"], headers=headers)
    assert visible.status_code == 200, visible.text


async def test_admin_cli_rejects_existing_email_in_another_organization(pilot):
    w, _, _ = pilot
    before = w.users["foreign"]
    result = await admin_cli(pilot, before.email, w.org_a.slug)
    assert result.returncode != 0
    assert "another organization" in result.stderr
    assert "Done." not in result.stdout
    async with w.sessions() as db:
        after = await db.get(User, before.id)
        assert (after.org_id, after.password_hash, after.role) == (before.org_id, before.password_hash, before.role)


@pytest.mark.parametrize("invalid", ["email", "password"])
async def test_admin_cli_rejects_credentials_that_login_cannot_accept_before_writing(pilot, invalid):
    w, _, _ = pilot
    email = "invalid-pilot-" + w.suffix + ("@sphere.local" if invalid == "email" else "@example.org")
    password = "short" if invalid == "password" else "isolated-pilot-password"
    result = await admin_cli(pilot, email, w.org_a.slug, password)
    assert result.returncode != 0
    assert password not in result.stdout + result.stderr
    async with w.sessions() as db:
        assert await db.scalar(select(User.id).where(User.email == email)) is None
