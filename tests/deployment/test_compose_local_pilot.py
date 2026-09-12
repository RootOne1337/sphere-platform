"""Render the local pilot overlay to verify coexistence with another installation."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


def render_pilot(tmp_path, *, remote_profile=None):
    docker = shutil.which("docker")
    if not docker:
        if os.environ.get("CI"):
            pytest.fail("Docker Compose is required for deployment acceptance")
        pytest.skip("Docker Compose unavailable")
    files = ["docker-compose.yml", "docker-compose.full.yml", "docker-compose.local-pilot.yml"]
    if remote_profile:
        files.append("docker-compose.remote-pilot.yml")
    variables = set()
    for name in files:
        variables.update(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", (REPOSITORY / name).read_text(encoding="utf-8")))
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    env.update({name: "fixture" for name in variables})
    env.update(PILOT_IMAGE_PREFIX="isolated-pilot-test", PILOT_REVISION="test",
        PILOT_GATEWAY_PORT="18080", PILOT_N8N_PORT="15678", PILOT_S3_PORT="19000",
        PILOT_S3_CONSOLE_PORT="19001", BACKEND_PORT="8000", WEB_CONCURRENCY="4",
        PILOT_AGENT_URL="http://10.0.2.2:18080", PILOT_BROWSER_URL="http://127.0.0.1:18080",
        PILOT_REMOTE_PRIMARY="https://primary.example.test", PILOT_REMOTE_FALLBACK="https://backup.example.test",
        PILOT_SSH_PORT="22")
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    command = [docker, "compose", "--project-name", "isolated-pilot-test", "--env-file", str(empty)]
    for name in files:
        command.extend(["-f", str(REPOSITORY / name)])
    if remote_profile:
        command.extend(["--profile", remote_profile])
    rendered = subprocess.run([*command, "config", "--format", "json"], cwd=tmp_path,
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert rendered.returncode == 0, rendered.stderr
    return json.loads(rendered.stdout)


@pytest.fixture
def pilot(tmp_path):
    return render_pilot(tmp_path)


def test_pilot_resources_and_ports_are_isolated(pilot):
    assert pilot["name"] == "isolated-pilot-test"
    assert set(pilot["services"]) == {"backend", "frontend", "postgres", "redis", "nginx", "n8n", "minio"}
    for resources in (pilot["volumes"], pilot["networks"]):
        for resource in resources.values():
            assert not resource.get("external")
            assert resource["name"].startswith("isolated-pilot-test_")
    for service in pilot["services"].values():
        assert "container_name" not in service
        for port in service.get("ports", []):
            assert port["host_ip"] == "127.0.0.1"
    for name in ("backend", "frontend", "postgres", "redis"):
        assert not pilot["services"][name].get("ports")


def test_pilot_runs_built_images_with_real_auth_and_healthchecks(pilot):
    for name in ("backend", "frontend"):
        service = pilot["services"][name]
        assert service["image"] == f"isolated-pilot-test-{name}:test"
        assert not service.get("command")
        assert service.get("user") not in {"0", "root"}
    backend = pilot["services"]["backend"]
    assert backend["environment"]["DEV_SKIP_AUTH"] == "false"
    assert backend["environment"]["SERVER_PUBLIC_URL"] == "http://10.0.2.2:18080"
    assert backend["build"]["dockerfile"] == "backend/Dockerfile"
    assert len(backend["volumes"]) == 1
    assert backend["volumes"][0]["target"] == "/app/agent-config"
    assert backend["volumes"][0]["read_only"]
    assert not pilot["services"]["frontend"].get("volumes")
    for service in pilot["services"].values():
        assert service["healthcheck"]["test"]
        assert not service["healthcheck"].get("disable")


@pytest.mark.parametrize("profile,tunnel", [
    ("quick", "cloudflare-quick"), ("cloudflare", "cloudflared"), ("serveo", "ssh-tunnel"),
])
def test_remote_routes_keep_private_storage_and_do_not_open_host_ports(tmp_path, profile, tunnel):
    pilot = render_pilot(tmp_path, remote_profile=profile)
    services = pilot["services"]
    assert set(services) == {"backend", "frontend", "postgres", "redis", "nginx", "n8n", "minio",
                             "public-gateway", tunnel}
    for resources in (pilot["volumes"], pilot["networks"]):
        for resource in resources.values():
            assert not resource.get("external")
            assert resource["name"].startswith("isolated-pilot-test_")
    for name, service in services.items():
        assert "container_name" not in service
        for port in service.get("ports", []):
            assert port["host_ip"] == "127.0.0.1"
        if name in {"public-gateway", tunnel}:
            assert not service.get("ports")
            assert service["healthcheck"]["test"]
            assert service["restart"] == "unless-stopped"
            assert int(service["deploy"]["resources"]["limits"]["memory"]) <= 192 * 1024 * 1024
    assert services["backend"]["environment"]["DEV_SKIP_AUTH"] == "false"
    assert "https://primary.example.test" in services["backend"]["environment"]["CORS_EXTRA_ORIGINS"]
    assert "https://backup.example.test" in services["backend"]["environment"]["CORS_EXTRA_ORIGINS"]
    public_mounts = services["public-gateway"]["volumes"]
    assert all(m["read_only"] for m in public_mounts)
    assert {m["target"] for m in public_mounts} == {"/etc/nginx/remote-pilot.conf", "/public"}
    assert not services[tunnel].get("privileged")
    if profile == "quick":
        assert not services[tunnel].get("volumes") and not services[tunnel].get("secrets")
    elif profile == "cloudflare":
        assert services[tunnel]["volumes"][0]["target"] == "/etc/cloudflared"
        assert ".cloudflared" not in services[tunnel]["volumes"][0]["source"]
    else:
        assert services[tunnel]["secrets"][0]["source"] == "serveo_identity"
        assert not services[tunnel]["build"].get("args")
