"""Exercise the actual remote gateway config on an isolated Docker network."""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_remote_gateway_preserves_request_host_and_overwrites_forwarded_host(tmp_path):
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
    upstream_config.write_text('''events {} http { server { listen 80; location / {
        return 200 "$http_host|$http_x_forwarded_host";
    } } }
''', encoding="utf-8")
    try:
        run("network", "create", "--internal", network)
        run("run", "-d", "--name", upstream, "--network", network, "--network-alias", "nginx",
            "--mount", f"type=bind,source={upstream_config},target=/etc/nginx/nginx.conf,readonly", "nginx:alpine")
        run("run", "-d", "--name", edge, "--network", network,
            "--mount", f"type=bind,source={ROOT / 'infrastructure/nginx/remote-pilot.conf'},target=/etc/nginx/remote-pilot.conf,readonly",
            "nginx:alpine", "nginx", "-c", "/etc/nginx/remote-pilot.conf", "-g", "daemon off;")
        run("exec", edge, "nginx", "-t", "-c", "/etc/nginx/remote-pilot.conf")
        for host in ("primary.example.test", "recovered.example.test", "pilot.example.test:8443"):
            deadline = time.monotonic() + 15
            while True:
                response = run("exec", edge, "wget", "-T", "2", "-qO-", "--header", f"Host: {host}",
                               "--header", "X-Forwarded-Host: untrusted.invalid",
                               "http://127.0.0.1:8080/api/v1/updates/latest", check=False)
                if response.returncode == 0:
                    break
                assert time.monotonic() < deadline, response.stderr
                time.sleep(0.1)
            assert response.stdout == f"{host}|{host}"
    finally:
        run("rm", "-f", edge, upstream, check=False)
        run("network", "rm", network, check=False)
