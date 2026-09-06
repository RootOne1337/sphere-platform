"""Validate the actual Compose merge; never start containers or use real secrets."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture(params=[False, True], ids=["base-production", "base-full-production"])
def production_config(request, tmp_path):
    if shutil.which("docker") is None:
        if os.environ.get("CI"):
            pytest.fail("Docker Compose is required for deployment configuration checks")
        pytest.skip("Docker Compose unavailable; no configuration validation performed")
    files = ["docker-compose.yml"]
    if request.param:
        files.append("docker-compose.full.yml")
    files.append("docker-compose.production.yml")
    # Override every interpolation variable with synthetic data and disable .env
    # autoloading. Only selected configuration properties appear in assertions.
    variables = set()
    for name in files:
        variables.update(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", (REPOSITORY / name).read_text(encoding="utf-8")))
    environment = os.environ.copy()
    environment.update({name: "audit-fixture" for name in variables})
    environment.update(BACKEND_PORT="58080", WEB_CONCURRENCY="4", ENVIRONMENT="production")
    env_file = tmp_path / "empty.env"
    env_file.write_text("", encoding="utf-8")
    command = ["docker", "compose", "--env-file", str(env_file)]
    for name in files:
        command.extend(["-f", name])
    result = subprocess.run(command + ["config", "--format", "json"], cwd=REPOSITORY,
        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]


def test_production_databases_have_no_published_host_ports(production_config):
    for service in ["postgres", "redis"]:
        assert not production_config[service].get("ports"), production_config[service].get("ports")


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_production_application_uses_image_defaults_without_source_mounts(production_config, service):
    configuration = production_config[service]
    assert not configuration.get("command"), {service: configuration.get("command")}
    assert not configuration.get("volumes"), {service: configuration.get("volumes")}
    assert configuration.get("user") not in {"0", "root"}
    assert not configuration.get("ports"), {service: configuration.get("ports")}
