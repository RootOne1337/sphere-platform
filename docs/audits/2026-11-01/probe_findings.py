"""Read-only findings observations using synthetic values and mocks.

Run from any directory with the project's Python dependencies installed:
    python -B docs/audits/2026-11-01/probe_findings.py

Before importing project code, this process clears inherited environment values,
enters a new empty temporary directory, and provides a synthetic JWT key. This
avoids reading the checkout's .env files or real configuration. It does not start
FastAPI lifespan or connect to a database, Redis, devices, ingress, or GitHub.

RISK means a synthetic reproduction observed the named condition; PASS means
that particular risk was not observed or a control behaved as expected. Exit 0
means all probes ran, including when risks are present. Exit 1 means a probe
could not run; this script is diagnostic, not a CI security acceptance gate.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_SIGNING_KEY = "A" * 48


def report(name: str, risk: bool, detail: str) -> None:
    print(f"{'RISK' if risk else 'PASS'}  {name}: {detail}")


def request(headers: list[tuple[bytes, bytes]] | None = None):
    from starlette.requests import Request

    return Request({
        "type": "http", "method": "POST", "path": "/", "scheme": "https",
        "server": ("fixture.invalid", 443), "headers": headers or [],
    })


async def probe_config() -> None:
    from fastapi import HTTPException

    router = importlib.import_module("backend.api.v1.config.router")
    fixture = {"server_url": "https://fixture.invalid", "enrollment_api_key": "sphr_synthetic_fixture"}
    with patch.object(router, "_get_cached_agent_config", AsyncMock(return_value=fixture)), patch.object(
        router, "_load_agent_config_from_file", side_effect=AssertionError("file read prohibited")
    ):
        try:
            response = await router.get_agent_config(
                x_api_key=None, x_agent_fingerprint=None, db=None, redis=None,
            )
        except HTTPException:
            leaked = False
        else:
            leaked = response.enrollment_api_key == fixture["enrollment_api_key"]
    report("anonymous config", leaked, "synthetic enrollment key returned" if leaked else "fixture key not returned")


async def probe_dev_bypass() -> None:
    from fastapi import HTTPException
    from pydantic import ValidationError

    from backend.core import config, dependencies

    # A future fail-closed Settings validator is a valid remediation; don't
    # bypass it by merely monkeypatching an already-created Settings instance.
    try:
        config.Settings(_env_file=None, JWT_SECRET_KEY=SYNTHETIC_SIGNING_KEY,
                        ENVIRONMENT="production", DEV_SKIP_AUTH=True)
    except ValidationError:
        report("production dev bypass", False, "production configuration rejects bypass")
        return
    user = SimpleNamespace(id="synthetic-user", org_id="synthetic-org", is_active=True)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user)))
    with patch.object(config.settings, "ENVIRONMENT", "production"), patch.object(
        config.settings, "DEV_SKIP_AUTH", True
    ):
        try:
            response = await dependencies.get_current_user(request(), credentials=None, db=db)
        except HTTPException:
            bypass = False
        else:
            bypass = response is user
    report("production dev bypass", bypass, "mock user accepted without Bearer" if bypass else "mock user not accepted")


async def probe_logout() -> None:
    import jwt
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    from starlette.responses import Response

    router = importlib.import_module("backend.api.v1.auth.router")
    token = jwt.encode({
        "sub": "fixture-device", "org_id": "fixture-org", "jti": "fixture-jti",
        "type": "device", "exp": 1,
    }, SYNTHETIC_SIGNING_KEY, algorithm="HS256")
    service = SimpleNamespace(logout=AsyncMock())
    try:
        await router.logout(
            request([(b"x-refresh-token", b"synthetic-other-refresh")]), Response(),
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), None, service,
        )
    except HTTPException:
        forwarded = False
    else:
        forwarded = service.logout.await_count == 1 and (
            service.logout.await_args.kwargs.get("refresh_token_raw") == "synthetic-other-refresh"
        )
    report("logout JWT type", forwarded, "signed expired non-access JWT and fixture refresh forwarded" if forwarded else "fixture combination not forwarded")

    # This independently tests the service with a fake row. No lookup or SQL is performed.
    module = importlib.import_module("backend.services.auth_service")
    row = SimpleNamespace(revoked=False, revoked_at=None, org_id="other-org", user_id="other-user")
    db = SimpleNamespace(commit=AsyncMock())
    cache = SimpleNamespace(blacklist_token=AsyncMock())
    actual = module.AuthService(db, cache)
    actual._get_refresh_token_by_hash = AsyncMock(return_value=row)
    await actual.logout(jti="fixture-jti", token_exp=1, refresh_token_raw="synthetic-other-refresh")
    revoked = row.revoked and db.commit.await_count == 1
    report("logout mock row", revoked, "selected mock refresh revoked without principal comparison" if revoked else "mock refresh not revoked")


async def probe_health() -> None:
    from fastapi import HTTPException

    from backend.services.health_service import ComponentHealth, HealthService

    redis = AsyncMock()
    redis.ping.return_value = False
    redis.info.return_value = {}
    service = HealthService(None, redis)
    service._check_postgres = AsyncMock(return_value=ComponentHealth(name="postgresql", status="ok", latency_ms=0))
    false_ping_ready = await service.check_readiness()
    report("readyz false ping", false_ping_ready, "mock false PING treated as ready" if false_ping_ready else "mock false PING not ready")
    service.redis = None
    missing_ready = await service.check_readiness()
    report("readyz missing Redis", missing_ready, "missing mock Redis treated as ready" if missing_ready else "missing mock Redis not ready")

    # Import app without starting its lifespan; fake connection never opens a socket.
    engine_module = importlib.import_module("backend.database.engine")
    redis_module = importlib.import_module("backend.database.redis_client")
    main_module = importlib.import_module("backend.main")

    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, *_args):
            return None

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    with patch.object(engine_module, "engine", FakeEngine()), patch.object(redis_module, "redis", None):
        try:
            result = await main_module.readiness_check()
        except HTTPException:
            false_ready = False
        else:
            false_ready = result.get("status") == "ready" and result.get("checks", {}).get("redis") == "ok"
    report("legacy readiness", false_ready, "missing mock Redis reported ok" if false_ready else "missing mock Redis not reported ok")


async def probe_role_guard() -> None:
    from backend.core import config, startup_checks

    with patch.object(config.settings, "ENVIRONMENT", "Production"), patch.object(startup_checks.logger, "warning"):
        try:
            startup_checks._reject_unsafe("synthetic unsafe role")
        except RuntimeError:
            warned_only = False
        else:
            warned_only = True
    report("environment case", warned_only, "capitalized Production only warns on unsafe role" if warned_only else "capitalized Production rejects unsafe role")


async def probe_discovery() -> None:
    import uuid

    from backend.schemas.discovery import DiscoverRequest
    from backend.services.discovery_service import DiscoveryService
    from backend.websocket.pubsub_router import PubSubRouter

    # Never call a newly implemented transport from this synthetic probe.
    if hasattr(PubSubRouter, "send_command_wait_result"):
        report("discovery transport", False, "router now exposes the method; delivery was not tested")
        return
    fixture = DiscoverRequest(
        subnet="192.0.2.0/30",
        workstation_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        auto_register=False,
    )
    router = PubSubRouter(redis=None, connection_manager=None)
    service = DiscoveryService(db=None, device_svc=None)
    with patch("backend.services.discovery_service.get_pubsub_router", return_value=router):
        result = await service._discover_devices_via_agent(fixture)
    risk = result == []
    report("discovery transport", risk, "missing router method converted to empty result" if risk else "fixture did not produce an empty result")


async def run_probes() -> bool:
    failures = 0
    for name, probe in (
        ("config", probe_config), ("dev bypass", probe_dev_bypass),
        ("logout", probe_logout), ("health", probe_health), ("role guard", probe_role_guard),
        ("discovery", probe_discovery),
    ):
        try:
            await probe()
        except Exception as exc:
            failures += 1
            # Avoid rendering arbitrary dependency/driver exception text.
            print(f"FAIL  {name}: probe could not run ({type(exc).__name__})")
    return failures == 0


def main() -> int:
    original_cwd = Path.cwd()
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    # This changes only the child process, never the caller's environment.
    os.environ.clear()
    os.environ.update({"JWT_SECRET_KEY": SYNTHETIC_SIGNING_KEY, "PATH": os.defpath})
    if os.name == "nt":
        os.environ["SYSTEMROOT"] = system_root
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    print("Synthetic fixtures and mocks only; no deployment or live-service conclusions.")
    with tempfile.TemporaryDirectory(prefix="sphere-auth-probe-") as directory:
        try:
            os.chdir(directory)
            success = asyncio.run(run_probes())
        finally:
            # Windows cannot remove a directory while it is the current directory.
            os.chdir(original_cwd)
    print("PASS  diagnostic completed" if success else "FAIL  diagnostic incomplete")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
