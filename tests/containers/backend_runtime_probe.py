"""Fresh packaged bootstrap and ASGI lifecycle; no source mount or API listener.

The runner supplies disposable PostgreSQL/Redis on an internal Docker network.
This intentionally tests development startup, not production database-role rollout.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EMAIL = "image-runtime-operator@example.org"
PASSWORD = "isolated-image-original-password"
CANDIDATE = "isolated-image-unused-candidate"
KEY = "sphr_isolated_image_runtime_enrollment"


async def application_phase(phase, state_file):
    import httpx

    from backend.database.engine import engine
    from backend.main import app

    # Actual registry, pool, Redis and background-worker initialization/shutdown.
    # No dependency overrides and no HTTP socket: only PostgreSQL/Redis use TCP.
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                    base_url="http://image-probe.local") as client:
                ready = await client.get("/api/v1/health/ready")
                assert ready.status_code == 200, ready.text
                assert ready.json()["checks"] == {"postgres": "ok", "redis": "ok"}
                login = await client.post("/api/v1/auth/login",
                    json={"email": EMAIL, "password": PASSWORD})
                assert login.status_code == 200, f"Login status: {login.status_code}"
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                if phase == "first":
                    registered = await client.post("/api/v1/devices/register",
                        headers={"X-API-Key": KEY}, json={"fingerprint": "isolated-image-runtime-device"})
                    assert registered.status_code == 201, f"Registration status: {registered.status_code}"
                    device_id = registered.json()["device_id"]
                    state_file.write_text(json.dumps({"device_id": device_id}), encoding="utf-8")
                else:
                    device_id = json.loads(state_file.read_text(encoding="utf-8"))["device_id"]
                    unused = await client.post("/api/v1/auth/login",
                        json={"email": EMAIL, "password": CANDIDATE})
                    assert unused.status_code == 401, "Retry candidate replaced the working password"
                visible = await client.get("/api/v1/devices/" + device_id, headers=headers)
                assert visible.status_code == 200, f"Visibility status: {visible.status_code}"
                assert visible.json()["id"] == device_id
                print(f"IMAGE_RUNTIME_PHASE={phase}: ready/login/device-visible", flush=True)
    finally:
        await engine.dispose()


class BackendRuntimeImageTests(unittest.TestCase):
    def command(self, *args, **overrides):
        result = subprocess.run([sys.executable, *args], cwd="/app",
            env=dict(os.environ, **overrides), capture_output=True, text=True, timeout=60)
        # Diagnostics contain only synthetic identities; do not print API bodies/tokens.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if "--phase" in args:
            for line in result.stdout.splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    self.assertNotIn(record.get("level"), ("error", "critical"), line)
            # Preserve lifecycle diagnostics, never the authenticated response bodies.
            print(result.stdout, flush=True)
        return result.stdout

    def test_fresh_image_bootstrap_and_process_restart_preserve_operator_and_device(self):
        self.assertNotEqual(os.geteuid(), 0)
        self.assertIn("audit", os.environ["POSTGRES_URL"])
        self.assertEqual(os.environ["ENVIRONMENT"], "development")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "environments" / "development.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"enrollment_api_key": KEY}), encoding="utf-8")
            env = {"ADMIN_EMAIL": EMAIL, "ADMIN_PASSWORD": PASSWORD,
                "SPHERE_BOOTSTRAP_ORG_SLUG": "isolated-image-runtime",
                "AGENT_CONFIG_DIR": temporary, "AGENT_CONFIG_ENV": "development"}
            self.command("-m", "alembic", "-c", "alembic/alembic.ini", "upgrade", "head", **env)
            output = self.command("scripts/create_admin.py", "--create-only", **env)
            self.assertEqual(output.splitlines().count("SPHERE_ADMIN_BOOTSTRAP=created"), 1)
            self.command("-m", "scripts.seed_enrollment_key", **env)
            state = str(root / "state.json")
            first = self.command(__file__, "--phase", "first", state, **env)
            self.assertIn("IMAGE_RUNTIME_PHASE=first:", first)
            # New subprocesses re-import the real app and reinitialize the registry.
            env["ADMIN_PASSWORD"] = CANDIDATE
            self.command("-m", "alembic", "-c", "alembic/alembic.ini", "upgrade", "head", **env)
            output = self.command("scripts/create_admin.py", "--create-only", **env)
            self.assertEqual(output.splitlines().count("SPHERE_ADMIN_BOOTSTRAP=existing"), 1)
            self.command("-m", "scripts.seed_enrollment_key", **env)
            repeated = self.command(__file__, "--phase", "repeat", state, **env)
            self.assertIn("IMAGE_RUNTIME_PHASE=repeat:", repeated)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--phase":
        asyncio.run(application_phase(sys.argv[2], Path(sys.argv[3])))
    else:
        unittest.main(verbosity=2)
