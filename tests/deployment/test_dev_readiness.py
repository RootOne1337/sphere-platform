"""Execute the effective Compose health commands with controlled HTTP responses."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", params=["full", "production"])
def dev_services(request, tmp_path_factory):
    if not shutil.which("docker"):
        if os.environ.get("CI"):
            pytest.fail("Docker Compose is required for readiness configuration checks")
        pytest.skip("Docker Compose unavailable")
    files = ["docker-compose.yml", f"docker-compose.{request.param}.yml"]
    variables = set()
    for name in files:
        variables.update(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", (REPOSITORY / name).read_text(encoding="utf-8")))
    environment = os.environ.copy()
    environment.update({name: "audit-fixture" for name in variables})
    environment.update(BACKEND_PORT="58080", WEB_CONCURRENCY="4", ENVIRONMENT="development")
    empty = tmp_path_factory.mktemp("compose-readiness") / "empty.env"
    empty.write_text("", encoding="utf-8")
    command = ["docker", "compose", "--env-file", str(empty)]
    for name in files:
        command.extend(["-f", name])
    result = subprocess.run(command + ["config", "--format", "json"], cwd=REPOSITORY,
        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]


def test_backend_receives_the_selected_bootstrap_organization(dev_services):
    assert dev_services["backend"]["environment"].get("SPHERE_BOOTSTRAP_ORG_SLUG") == "audit-fixture"


@pytest.mark.parametrize("scenario,code", [("ready", 0), ("unready", 1), ("error", 1)])
def test_backend_healthcheck_requires_readiness_response(dev_services, scenario, code):
    check = dev_services["backend"].get("healthcheck", {})
    assert check.get("test"), "Backend has no readiness gate in the effective Compose configuration"
    command = check["test"]
    assert command[:3] == ["CMD", "python", "-c"]
    # Run the shipped Python expression, replacing only its HTTP boundary.
    prelude = '''import io, urllib.request
def fake(url, timeout):
    assert url == "http://127.0.0.1:8000/api/v1/health/readyz"
    assert 0 < timeout <= 5
    if SCENARIO == "error":
        raise OSError("synthetic connection failure")
    response = io.BytesIO(b'{"status":"ready"}' if SCENARIO == "ready" else b'{"status":"not_ready"}')
    response.status = 200  # A reachable but unready server must still fail.
    return response
urllib.request.urlopen = fake
'''.replace("SCENARIO", repr(scenario))
    result = subprocess.run([sys.executable, "-c", prelude + command[3]],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == code, result.stderr


@pytest.mark.parametrize("status", [200, 302, 503, "error"])
def test_frontend_healthcheck_rejects_redirects_errors_and_network_failure(dev_services, status):
    check = dev_services["frontend"].get("healthcheck", {})
    assert check.get("test"), "Frontend has no HTTP readiness gate in the effective Compose configuration"
    command = check["test"]
    assert command[:3] == ["CMD", "node", "-e"]
    node = shutil.which("node")
    if not node:
        if os.environ.get("CI"):
            pytest.fail("Node is required for the frontend readiness command")
        pytest.skip("Node unavailable; health command was not exercised")
    prelude = '''globalThis.fetch = async (url, options) => {
      if (url !== 'http://127.0.0.1:3000/login' || options.redirect !== 'manual' || !options.signal)
        process.exit(99);
      if (STATUS === 'error') throw new Error('synthetic connection failure');
      return {status: STATUS};
    };
    '''.replace("STATUS", json.dumps(status))
    result = subprocess.run([node, "-e", prelude + command[3]],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == (0 if status == 200 else 1), result.stderr
