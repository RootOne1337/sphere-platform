"""Run the registered dev enrollment hook against disposable PostgreSQL/Redis."""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from structlog.testing import capture_logs

from backend.core.config import settings
from backend.models import APIKey, Device
from backend.services.cache_service import CacheService
from backend.tasks import ensure_enrollment_key as hook
from scripts import seed_enrollment_key


@pytest_asyncio.fixture
async def enrollment(world, monkeypatch, tmp_path):
    raw = "sphr_startup_" + world.suffix
    legacy = "sphr_legacy_" + world.suffix
    config = tmp_path / "environments" / "development.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"enrollment_api_key": raw}), encoding="utf-8")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "AGENT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AGENT_CONFIG_ENV", "development")
    monkeypatch.setenv("SPHERE_BOOTSTRAP_ORG_SLUG", world.org_b.slug)
    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", world.sessions)
    # Isolate the old hook's hard-coded material without changing its behavior.
    # The repaired hook has no such constant; keeping this permits baseline proof.
    monkeypatch.setattr(hook, "DEV_ENROLLMENT_KEY", legacy, raising=False)
    original_limit = CacheService.check_rate_limit

    async def isolated_limit(self, identifier, **kwargs):
        return await original_limit(self, world.suffix + ":" + identifier, **kwargs)

    monkeypatch.setattr(CacheService, "check_rate_limit", isolated_limit)
    yield world, raw, legacy, config
    # The baseline can write into an unrelated organization. Remove only the
    # two synthetic, UUID-specific keys owned by this test, never other keys.
    hashes = [hashlib.sha256(key.encode()).hexdigest() for key in (raw, legacy)]
    async with world.sessions() as db:
        await db.execute(delete(APIKey).where(APIKey.key_hash.in_(hashes)))
        await db.commit()


async def stored(enrollment, raw=None):
    w, configured, _, _ = enrollment
    async with w.sessions() as db:
        return await db.scalar(select(APIKey).where(
            APIKey.key_hash == hashlib.sha256((raw or configured).encode()).hexdigest()))


async def test_startup_uses_configured_key_for_actual_device_registration(enrollment):
    w, raw, legacy, _ = enrollment
    await hook._ensure_enrollment_key()
    response = await w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw},
        json={"fingerprint": "startup-" + w.suffix})
    assert response.status_code == 201, response.text
    key = await stored(enrollment)
    assert key.org_id == w.org_b.id
    assert await stored(enrollment, legacy) is None
    async with w.sessions() as db:
        assert (await db.get(Device, UUID(response.json()["device_id"]))).org_id == w.org_b.id
    path = "/api/v1/devices/" + response.json()["device_id"]
    assert (await w.client.get(path, headers=w.auth(w.users["foreign"]))).status_code == 200
    assert (await w.client.get(path, headers=w.auth(w.users["org_admin"]))).status_code in (403, 404)


async def test_startup_uses_selected_organization_even_with_the_legacy_key(enrollment, monkeypatch):
    w, _, legacy, config = enrollment
    config.write_text(json.dumps({"enrollment_api_key": legacy}), encoding="utf-8")
    await hook._ensure_enrollment_key()
    key = await stored(enrollment, legacy)
    assert key.org_id == w.org_b.id
    assert key.type == "agent"


async def test_cli_then_repeated_workers_keep_one_configured_key(enrollment):
    w, raw, legacy, _ = enrollment
    await seed_enrollment_key.main()
    first = await stored(enrollment)
    outcomes = await asyncio.wait_for(asyncio.gather(
        *(hook._ensure_enrollment_key() for _ in range(4)), return_exceptions=True), 10)
    assert outcomes == [None] * 4, outcomes
    assert (await stored(enrollment)).id == first.id
    assert await stored(enrollment, legacy) is None
    async with w.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(APIKey).where(
            APIKey.key_hash == hashlib.sha256(raw.encode()).hexdigest())) == 1


async def test_simultaneous_first_workers_converge(enrollment, monkeypatch):
    _, raw, _, _ = enrollment
    monkeypatch.setattr(hook, "DEV_ENROLLMENT_KEY", raw)
    outcomes = await asyncio.wait_for(asyncio.gather(
        *(hook._ensure_enrollment_key() for _ in range(4)), return_exceptions=True), 10)
    assert outcomes == [None] * 4, outcomes
    assert (await stored(enrollment)).org_id == enrollment[0].org_b.id


@pytest.mark.parametrize("change", ["revoked", "expired", "permissions", "organization"])
async def test_conflicting_key_is_reported_without_reactivation_or_api_shutdown(enrollment, monkeypatch, change):
    w, raw, _, _ = enrollment
    monkeypatch.setattr(hook, "DEV_ENROLLMENT_KEY", raw)
    await seed_enrollment_key.main()
    key = await stored(enrollment)
    values = {
        "revoked": {"is_active": False},
        "expired": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
        "permissions": {"permissions": []},
        "organization": {"org_id": w.org_a.id},
    }[change]
    async with w.sessions() as db:
        await db.execute(update(APIKey).where(APIKey.id == key.id).values(**values))
        await db.commit()
    with capture_logs() as logs:
        await hook._ensure_enrollment_key()
    assert any(entry["log_level"] == "warning" for entry in logs), logs
    assert raw not in json.dumps(logs)
    assert hashlib.sha256(raw.encode()).hexdigest() not in json.dumps(logs)
    current = await stored(enrollment)
    for name, expected in values.items():
        assert getattr(current, name) == expected


async def test_missing_selected_organization_does_not_bind_to_another(enrollment, monkeypatch):
    w, raw, legacy, _ = enrollment
    monkeypatch.setenv("SPHERE_BOOTSTRAP_ORG_SLUG", "missing-" + w.suffix)
    with capture_logs() as logs:
        await hook._ensure_enrollment_key()
    assert any(entry["log_level"] == "warning" for entry in logs)
    assert await stored(enrollment, raw) is None
    assert await stored(enrollment, legacy) is None


@pytest.mark.parametrize("environment", ["dev", "local"])
async def test_development_aliases_use_the_same_configured_identity(enrollment, monkeypatch, environment):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    await hook._ensure_enrollment_key()
    assert (await stored(enrollment)).org_id == enrollment[0].org_b.id


@pytest.mark.parametrize("config_value", ["{}", "[]", "invalid-json", None])
async def test_invalid_config_keeps_api_available_without_creating_fallback_key(enrollment, config_value):
    _, raw, legacy, config = enrollment
    if config_value is None:
        config.unlink()
    else:
        config.write_text(config_value, encoding="utf-8")
    with capture_logs() as logs:
        await hook._ensure_enrollment_key()
    assert any(entry.get("reason") == "EnrollmentConfigurationError" for entry in logs)
    assert await stored(enrollment, raw) is None
    assert await stored(enrollment, legacy) is None


async def test_database_failure_is_not_mislabeled_as_configuration_warning(enrollment, monkeypatch):
    def unavailable_database():
        raise ConnectionError("synthetic database unavailable")

    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", unavailable_database)
    with pytest.raises(ConnectionError, match="synthetic database unavailable"):
        await hook._ensure_enrollment_key()


@pytest.mark.parametrize("environment", ["production", "staging", "test"])
async def test_non_development_startup_does_not_read_config_or_open_database(monkeypatch, environment):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)

    def unexpected_session():
        pytest.fail("non-development startup must not provision enrollment keys")

    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", unexpected_session)
    monkeypatch.setattr(settings, "AGENT_CONFIG_DIR", "missing-unused-config")
    await hook._ensure_enrollment_key()
