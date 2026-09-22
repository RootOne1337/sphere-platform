"""Render shipped Compose combinations with synthetic secrets; never start the stack."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
MATRIX = {
    "base": ["docker-compose.yml"],
    "development": ["docker-compose.yml", "docker-compose.override.yml"],
    "full": ["docker-compose.yml", "docker-compose.full.yml"],
    "production": ["docker-compose.yml", "docker-compose.production.yml"],
    "full-production": ["docker-compose.yml", "docker-compose.full.yml", "docker-compose.production.yml"],
    "pilot": ["docker-compose.yml", "docker-compose.full.yml", "docker-compose.local-pilot.yml"],
    "remote-pilot": ["docker-compose.yml", "docker-compose.full.yml", "docker-compose.local-pilot.yml", "docker-compose.remote-pilot.yml"],
}


def render_redis(tmp_path, mode="pilot"):
    if not shutil.which("docker"):
        if os.environ.get("CI"):
            pytest.fail("Docker Compose is required for deployment acceptance")
        pytest.skip("Docker Compose unavailable")
    files = MATRIX[mode]
    variables = set()
    for name in files:
        variables.update(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", (REPOSITORY / name).read_text(encoding="utf-8")))
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    env.update({key: "fixture" for key in variables})
    env.update(BACKEND_PORT="8000", WEB_CONCURRENCY="4", PILOT_GATEWAY_PORT="18080",
               PILOT_N8N_PORT="15678", PILOT_S3_PORT="19000", PILOT_S3_CONSOLE_PORT="19001",
               PILOT_SSH_PORT="22", PR_NUMBER="1")
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    command = ["docker", "compose", "--project-name", "isolated-redis-budget-test", "--env-file", str(empty)]
    for name in files:
        command.extend(["-f", str(REPOSITORY / name)])
    result = subprocess.run([*command, "config", "--format", "json"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]["redis"]


def maxmemory_bytes(service):
    command = service.get("command") or []
    assert "--maxmemory" in command, "A container limit without Redis maxmemory reaches kernel OOM"
    value = command[command.index("--maxmemory") + 1].lower()
    match = re.fullmatch(r"(\d+)(mb|gb|kb)?", value)
    assert match, value
    return int(match[1]) * {None: 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}[match[2]]


@pytest.mark.parametrize("mode", MATRIX)
def test_runtime_redis_profiles_leave_process_and_persistence_headroom(tmp_path, mode):
    service = render_redis(tmp_path, mode)
    dataset = maxmemory_bytes(service)
    container = int(service["deploy"]["resources"]["limits"]["memory"])
    assert dataset > 0
    # Four times dataset leaves room for COW, AOF buffers and charged filesystem cache.
    # This is a baseline admission rule, not a bound on arbitrary client buffers.
    assert container >= 4 * dataset, {"profile": mode, "maxmemory": dataset, "container": container}


def test_pilot_keeps_existing_dataset_capacity_and_persistence(tmp_path):
    service = render_redis(tmp_path)
    assert maxmemory_bytes(service) == 512 * 1024**2
    assert int(service["deploy"]["resources"]["limits"]["memory"]) == 2048 * 1024**2
    command = service["command"]
    assert command[command.index("--appendonly") + 1] == "yes"
    assert command[command.index("--appendfsync") + 1] == "everysec"
    assert command[command.index("--maxmemory-policy") + 1] == "allkeys-lru"
