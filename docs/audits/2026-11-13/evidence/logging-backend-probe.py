"""Compare device-journal retention against temporary files only."""

import asyncio
import importlib
import json
import os
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from starlette.requests import Request


def synthetic_request(body):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "headers": [(b"content-length", str(len(body)).encode())]}, receive)


async def observe():
    os.environ["JWT_SECRET_KEY"] = "audit-logging-fixture-only-20261113-material"
    os.environ["POSTGRES_URL"] = "postgresql+asyncpg://127.0.0.1:1/sphere_audit_20261113"
    os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
    router = importlib.import_module("backend.api.v1.logs.router")
    now = time.time()
    org_id, online, offline = uuid4(), uuid4(), uuid4()
    device = SimpleNamespace(id=online, org_id=org_id, is_active=True)
    database = SimpleNamespace(get=AsyncMock(return_value=device))
    principal = SimpleNamespace(device_id=online, org_id=org_id)

    version = "before" if hasattr(router, "_MAX_LOG_SIZE_BYTES") else "after"
    with TemporaryDirectory(prefix="sphere-log-audit-") as directory, ExitStack() as stack:
        stack.enter_context(patch.object(router, "_LOGS_DIR", Path(directory)))
        stack.enter_context(patch("backend.api.ws.android.router.authenticate_ws_token", AsyncMock(return_value=principal)))
        if version == "before":
            stack.enter_context(patch.object(router, "_MAX_LOG_SIZE_BYTES", 200))
        else:
            stack.enter_context(patch.object(router.settings, "DEVICE_LOG_DAILY_MAX_BYTES", 200))
        same_device_old = router._get_log_file(str(online)).parent / "agent_2000-01-01.log"
        offline_old = router._get_log_file(str(offline)).parent / "agent_2000-01-01.log"
        old = now - 31 * 86400
        for file in (same_device_old, offline_old):
            file.write_bytes(b"aged fixture")
            os.utime(file, (old, old))

        bodies = [b"first" + b"A" * 115, b"second" + b"B" * 114, b"third" + b"C" * 115]
        sizes = []
        statuses = []
        for body in bodies:
            try:
                response = await router.upload_logs(
                    synthetic_request(body), device_id=None, x_device_id=str(online),
                    x_api_key="synthetic-local", db=database,
                )
            except HTTPException as exc:
                statuses.append(exc.status_code)
            else:
                statuses.append(response.status_code)
            sizes.append(router._get_log_file(str(online)).stat().st_size)
        retained = router._get_log_file(str(online)).read_bytes()
        return version, {
            "isolated_storage": True, "scaled_daily_file_threshold_bytes": 200,
            "upload_statuses": statuses, "successive_daily_file_bytes": sizes,
            "daily_file_exceeds_threshold_before_next_upload": sizes[1] > 200,
            "first_two_successful_uploads_erased_by_rollover": bodies[0] not in retained and bodies[1] not in retained,
            "first_upload_remains": bodies[0] in retained,
            "third_upload_remains": bodies[2] in retained,
            "expired_active_device_file_remains": same_device_old.exists(),
            "expired_inactive_device_file_remains": offline_old.exists(),
        }


if __name__ == "__main__":
    version, result = asyncio.run(observe())
    payload = json.dumps(result, indent=2) + "\n"
    Path(__file__).with_name(f"logging-backend-{version}.json").write_text(payload, encoding="utf-8")
    print(payload)
