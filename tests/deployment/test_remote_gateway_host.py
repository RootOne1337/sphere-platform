"""Exercise the actual remote gateway config on an isolated Docker network."""

import hashlib
import os
import re
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
    network, upstream, edge, reviewed = [f"sphere-audit-host-{suffix}-{part}" for part in ("net", "upstream", "edge", "reviewed")]
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
        location / { return 200 "original-ui"; }
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

        # No opt-in file: old UI works even though no review gateway exists.
        original = run("exec", edge, "wget", "-T", "2", "-qO-",
                       "--header", "Host: primary.example.test", "http://127.0.0.1:8080/login")
        assert original.stdout == "original-ui"

        public = tmp_path / "public"
        public.mkdir()
        (public / "web-upstream.map").write_text("primary.example.test http://review-gateway:8080;\n", encoding="utf-8")
        (public / "agent.json").write_text('{"fixture":"bootstrap-preserved"}', encoding="utf-8")
        (public / "agent.signed.json").write_text('{"fixture":"signed-preserved"}', encoding="utf-8")
        static = tmp_path / "static"
        static.mkdir()
        javascript = "// tunnel asset integrity fixture\n" * 32768
        (static / "large.js").write_text(javascript, encoding="utf-8", newline="\n")
        reviewed_config = tmp_path / "reviewed.conf"
        reviewed_config.write_text('''events {} http { server {
            listen 8080;
            location /observability/grafana/public/ {
                alias /fixture/;
                default_type application/javascript;
            }
            location / {
                add_header Set-Cookie "sphere_observability=fixture; HttpOnly; SameSite=Strict; Path=/observability/grafana";
                return 200 "reviewed-ui|$http_host|$http_x_forwarded_host|$http_x_forwarded_proto|$request_uri";
            }
        }}''', encoding="utf-8")
        run("run", "-d", "--name", reviewed, "--network", network, "--network-alias", "review-gateway",
            "--mount", f"type=bind,source={reviewed_config},target=/etc/nginx/nginx.conf,readonly",
            "--mount", f"type=bind,source={static},target=/fixture,readonly", "nginx:alpine")
        # Install the private pilot routing map on this disposable edge only.
        run("cp", str(public), f"{edge}:/public")
        run("exec", edge, "nginx", "-t", "-c", "/etc/nginx/remote-pilot.conf")
        run("exec", edge, "nginx", "-s", "reload", "-c", "/etc/nginx/remote-pilot.conf")

        for path in ("/login", "/scripts/builder?id=fixture", "/_next/static/fixture.js",
                     "/api/observability/http?window=1h", "/observability/grafana/"):
            expected = f"reviewed-ui|primary.example.test|primary.example.test|https|{path}"
            deadline = time.monotonic() + 15
            while True:
                response = run("exec", edge, "wget", "-T", "2", "-qO-", "--header", "Host: primary.example.test",
                               "--header", "X-Forwarded-Host: untrusted.invalid", "http://127.0.0.1:8080" + path,
                               check=False)
                if response.returncode == 0 and response.stdout == expected:
                    break
                assert time.monotonic() < deadline, response.stderr + response.stdout
                time.sleep(0.1)

        # A tunnel adds Via. Negotiated static compression must preserve every
        # decoded byte, and clients without gzip must still receive plain JS.
        asset_url = "http://127.0.0.1:8080/observability/grafana/public/large.js"
        plain = run("exec", edge, "wget", "-T", "5", "-qO-",
                    "--header", "Host: primary.example.test", asset_url)
        assert hashlib.sha256(plain.stdout.encode()).digest() == hashlib.sha256(javascript.encode()).digest()
        compressed = run("exec", edge, "wget", "-T", "5", "-S", "-O", "/tmp/grafana.js.gz",
                         "--header", "Host: primary.example.test", "--header", "Accept-Encoding: gzip",
                         "--header", "Via: 1.1 tunnel", asset_url)
        assert "content-encoding: gzip" in compressed.stderr.lower()
        assert "vary: accept-encoding" in compressed.stderr.lower()
        decoded = run("exec", edge, "gzip", "-dc", "/tmp/grafana.js.gz")
        assert hashlib.sha256(decoded.stdout.encode()).digest() == hashlib.sha256(javascript.encode()).digest()

        # API and WebSockets still use the original upstream/public identity.
        response = run("exec", edge, "wget", "-T", "2", "-qO-", "--header", "Host: primary.example.test",
                       "http://127.0.0.1:8080/api/v1/updates/latest")
        assert response.stdout == "primary.example.test|primary.example.test"
        response = run("exec", edge, "wget", "-T", "2", "-qO-", "--header", "Host: primary.example.test",
                       "--header", "Upgrade: websocket", "--header", "Connection: Upgrade",
                       "http://127.0.0.1:8080/ws/android")
        assert response.stdout == "primary.example.test|primary.example.test|websocket|upgrade"
        for path, expected in (("/api/v1/config/agent", '{"fixture":"bootstrap-preserved"}'),
                               ("/bootstrap/agent.signed.json", '{"fixture":"signed-preserved"}')):
            response = run("exec", edge, "wget", "-T", "2", "-qO-", "--header", "Host: primary.example.test",
                           "http://127.0.0.1:8080" + path)
            assert response.stdout == expected
        response = run("exec", edge, "wget", "-T", "2", "-qO-", "--header", "Host: recovered.example.test",
                       "http://127.0.0.1:8080/login")
        assert response.stdout == "original-ui"  # Opt-in is exact-host, not a blanket public change.
        response = run("exec", edge, "wget", "-T", "2", "-S", "-O", "/dev/null",
                       "--header", "Host: primary.example.test", "http://127.0.0.1:8080/login")
        cookie = next(line for line in response.stderr.splitlines() if "Set-Cookie:" in line)
        assert "secure" in cookie.lower() and "httponly" in cookie.lower() and "SameSite=Strict" in cookie
        response = run("exec", edge, "wget", "-T", "2", "-qO-", "--header", "Host: primary.example.test",
                       "http://127.0.0.1:8080/metrics", check=False)
        assert response.returncode != 0 and "404" in response.stderr

        # A 200 only records response headers. The gateway log must also show
        # which public ingress was used and whether its response completed.
        access_lines = run("logs", edge).stdout
        assert re.search(
            r"primary\.example\.test GET /api/v1/updates/latest 200 "
            r"[0-9.]+ [1-9][0-9]* [1-9][0-9]* OK",
            access_lines,
        ), access_lines

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
        run("rm", "-f", edge, upstream, reviewed, check=False)
        run("network", "rm", network, check=False)
