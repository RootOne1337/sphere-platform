"""Exercise the real review gateway's redirect behind different public origins."""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_root_redirect_keeps_the_client_origin(tmp_path):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker unavailable")
    image = os.environ.get("SPHERE_AUDIT_NGINX_IMAGE", "nginx:alpine")

    def run(*args, data=None):
        # HTTP CRLF must survive Windows stdin without text-mode CRLF expansion.
        result = subprocess.run([docker, *args], input=data.encode() if data else None,
                                capture_output=True, timeout=20,
                                creationflags=0x08000000 if os.name == "nt" else 0)
        return subprocess.CompletedProcess(result.args, result.returncode,
                                           result.stdout.decode(), result.stderr.decode())

    if run("info").returncode:
        if os.environ.get("CI"):
            pytest.fail("Docker required for redirect regression")
        pytest.skip("Docker daemon unavailable")
    template = (ROOT / "infrastructure/nginx/review.conf").read_text(encoding="utf-8")
    config = tmp_path / "nginx.conf"
    config.write_text(template.replace("${SPHERE_REVIEW_UI_IP}", "127.0.0.2"), encoding="utf-8")
    name = "sphere-audit-review-redirect-" + uuid.uuid4().hex[:12]
    try:
        started = run("run", "-d", "--name", name, "--network", "none", "--user", "101:101",
                      "--read-only", "--cap-drop", "ALL", "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m",
                      "--mount", f"type=bind,source={config},target=/etc/nginx/nginx.conf,readonly",
                      image, "nginx", "-g", "daemon off;")
        assert started.returncode == 0, "Isolated gateway failed to start"
        deadline = time.monotonic() + 8
        for host, scheme in (("127.0.0.1:3015", "http"), ("public.example.test", "https"),
                             ("preview.example.test:8443", "https")):
            request = (f"GET / HTTP/1.1\r\nHost: {host}\r\nX-Forwarded-Proto: {scheme}\r\n"
                       "Connection: close\r\n\r\n")
            while True:
                response = run("exec", "-i", name, "nc", "-w", "2", "127.0.0.1", "8080", data=request)
                if "HTTP/1.1" in response.stdout:
                    break
                assert time.monotonic() < deadline, "Gateway did not become ready"
                time.sleep(0.1)
            assert response.stdout.startswith("HTTP/1.1 307 ")
            location = next(line.split(":", 1)[1].strip() for line in response.stdout.splitlines()
                            if line.lower().startswith("location:"))
            # A relative URL retains HTTPS and the external port at both proxies.
            assert location == "/dashboard", location
    finally:
        run("rm", "-f", name)
