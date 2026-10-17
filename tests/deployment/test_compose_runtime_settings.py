"""Generated installation config must survive Compose and real Settings parsing."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("overlay", ["full", "production"])
@pytest.mark.parametrize("skip_auth", [None, "", "false", "true"])
def test_generated_config_loads_backend_settings_after_real_compose_render(tmp_path, overlay, skip_auth):
    docker = shutil.which("docker")
    if not docker:
        if os.environ.get("CI"):
            pytest.fail("Docker Compose is required for deployment acceptance")
        pytest.skip("Docker Compose unavailable")
    config = tmp_path / ".env.generated"
    generated = subprocess.run([sys.executable, str(REPOSITORY / "scripts/generate_secrets.py"),
        "--output", str(config)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert generated.returncode == 0, generated.stderr
    content = config.read_text(encoding="utf-8")
    keys = {line.split("=", 1)[0] for line in content.splitlines() if "=" in line and not line.startswith("#")}
    env = {key: value for key, value in os.environ.items()
        if key not in keys | {"DEV_SKIP_AUTH"} and not key.startswith("COMPOSE_")}
    env["COMPOSE_PROJECT_NAME"] = "isolated-runtime-settings-audit"
    if skip_auth is not None:
        env["DEV_SKIP_AUTH"] = skip_auth
    rendered = subprocess.run([docker, "compose", "--env-file", str(config),
        "-f", str(REPOSITORY / "docker-compose.yml"),
        "-f", str(REPOSITORY / f"docker-compose.{overlay}.yml"), "config", "--format", "json"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert rendered.returncode == 0, rendered.stderr
    backend_env = json.loads(rendered.stdout)["services"]["backend"]["environment"]
    # Parse the actual rendered container environment in a fresh process without
    # the caller's .env files. Do not replace or pre-normalize the boolean value.
    probe_env = {**env, **backend_env, "PYTHONPATH": str(REPOSITORY)}
    parsed = subprocess.run([sys.executable, "-c",
        "from backend.core.config import settings; print('CONFIG_OK:' + str(settings.DEV_SKIP_AUTH))"],
        cwd=tmp_path, env=probe_env, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert parsed.returncode == 0, parsed.stdout + parsed.stderr
    enabled = overlay == "full" and skip_auth == "true"
    assert parsed.stdout.strip() == "CONFIG_OK:" + str(enabled)
