"""Exercise the actual remote gateway config on an isolated Docker network."""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_remote_gateway_preserves_host_without_triggering_public_http_redirect(tmp_path):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker is unavailable")

    def run(*args, check=True):
        return subprocess.run([docker, *args], capture_output=True, text=True, timeout=45,
                              check=check, creationflags=0x08000000 if os.name == "nt" else 0)

    if run("info", check=False).returncode:
        if os.environ.get("CI"):
            pytest.fail("Docker daemon required for gateway regression")
        pytest.skip("Docker daemon unavailable")
    suffix = uuid.uuid4().hex[:12]
    network, upstream, edge = [f"sphere-audit-host-{suffix}-{part}" for part in ("net", "upstream", "edge")]
    upstream_config = tmp_path / "nginx.conf"
    upstream_config.write_text('''events {} http {
    server {
        listen 80;
        server_name primary.example.test recovered.example.test pilot.example.test;
        return 301 https://$host$request_uri;
    }
    server { listen 80 default_server; server_name _; return 200 "wrong-http-listener"; }
    server {
        listen 8081 default_server;
        server_name _;
        location /api/ { return 200 "$http_host|$http_x_forwarded_host"; }
        location /ws/ { return 200 "$http_host|$http_x_forwarded_host|$http_upgrade|$http_connection"; }
    }
}
''', encoding="utf-8")
    try:
        run("network", "create", "--internal", network)
        run("run", "-d", "--name", upstream, "--network", network, "--network-alias", "nginx",
            "--mount", f"type=bind,source={upstream_config},target=/etc/nginx/nginx.conf,readonly", "nginx:alpine")
        run("run", "-d", "--name", edge, "--network", network,
            "--mount", f"type=bind,source={ROOT / 'infrastructure/nginx/remote-pilot.conf'},target=/etc/nginx/remote-pilot.conf,readonly",
            "nginx:alpine", "nginx", "-c", "/etc/nginx/remote-pilot.conf", "-g", "daemon off;")
        run("exec", edge, "nginx", "-t", "-c", "/etc/nginx/remote-pilot.conf")
        deadline = time.monotonic() + 15
        while True:
            ready = run("exec", edge, "wget", "-T", "2", "-qO-", "--header", "Host: probe.example.test",
                        "http://127.0.0.1:8080/api/v1/updates/latest", check=False)
            if ready.returncode == 0:
                break
            assert time.monotonic() < deadline, ready.stderr
            time.sleep(0.1)

        for host in ("primary.example.test", "recovered.example.test", "pilot.example.test:8443"):
            response = run("exec", edge, "wget", "-T", "2", "-qO-",
                           "--header", f"Host: {host}", "--header", "X-Forwarded-Host: untrusted.invalid",
                           "http://127.0.0.1:8080/api/v1/updates/latest", check=False)
            assert response.returncode == 0, response.stderr
            assert response.stdout == f"{host}|{host}"

            response = run("exec", edge, "wget", "-T", "2", "-qO-",
                           "--header", f"Host: {host}", "--header", "X-Forwarded-Host: untrusted.invalid",
                           "--header", "Upgrade: websocket", "--header", "Connection: Upgrade",
                           "http://127.0.0.1:8080/ws/stream/test-device", check=False)
            assert response.returncode == 0, response.stderr
            assert response.stdout == f"{host}|{host}|websocket|upgrade"

        gateway = (ROOT / "infrastructure/nginx/remote-pilot.conf").read_text(encoding="utf-8")
        main_nginx = (ROOT / "infrastructure/nginx/nginx.conf").read_text(encoding="utf-8")
        assert "http://nginx:8081" in gateway
        assert "listen 8081 default_server;" in main_nginx
        for compose_name in (
            "docker-compose.yml",
            "docker-compose.production.yml",
            "docker-compose.local-pilot.yml",
            "docker-compose.remote-pilot.yml",
        ):
            compose = (ROOT / compose_name).read_text(encoding="utf-8")
            assert "8081:8081" not in compose
    finally:
        run("rm", "-f", edge, upstream, check=False)
        run("network", "rm", network, check=False)
