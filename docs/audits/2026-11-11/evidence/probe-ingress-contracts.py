"""Check current Compose preview and nginx request limits with disposable fixtures."""

import asyncio
import base64
import json
import os
from pathlib import Path
import runpy
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parents[4]
TLS = runpy.run_path(str(Path(__file__).with_name("probe-nginx-renewal.py")))
PATH = "/api/v1/vpn/profiles/batch/preflight"
UPSTREAM = """from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        result = str(len(body)).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)
HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
"""


def docker(*args, check=True, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", check=check, timeout=30, **kwargs)


def preview_check(folder):
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    env.update(PR_NUMBER="411", PREVIEW_DB_PASSWORD="fixture",
               PREVIEW_JWT_SECRET="fixture", PREVIEW_DOMAIN="example.test", GITHUB_OWNER="fixture")
    empty_env = folder / "empty.env"
    empty_env.touch()
    result = docker("compose", "--env-file", str(empty_env), "-f",
                    str(ROOT / "docker-compose.preview.yml"), "config", "-q",
                    cwd=folder, env=env, check=False)
    return {"exit_code": result.returncode,
            "rejects_dynamic_volume_key": "additional properties 'preview-${PR_NUMBER}-pgdata' not allowed"
                                          in result.stderr}


def fixture_body(count, comment_lines):
    key = base64.b64encode(bytes(range(1, 33))).decode()
    config = (f"[Interface]\nPrivateKey = {key}\nAddress = 192.0.2.2/32\n"
              f"[Peer]\nPublicKey = {key}\nAllowedIPs = 0.0.0.0/0\nEndpoint = relay.example.test:51820\n"
              + ("# Fixture metadata " + "a" * 100 + "\n") * comment_lines)
    profile = {"protocol": "wireguard", "protocol_version": "1", "config_text": config,
               "traffic_policy": {"mode": "selected_apps", "included_packages": ["example.test.app"]}}
    items = [{"request_id": str(uuid.UUID(int=index)), "name": f"Fixture {index}", "profile": profile}
             for index in range(1, count + 1)]
    return json.dumps({"items": items}).encode()


async def direct_preflight(payload):
    from starlette.requests import Request as ASGIRequest
    from backend.api.v1.vpn.profile_router import inspect_profiles

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    # Exercise the handler's normal read-only preflight after authorization.
    result = await inspect_profiles(ASGIRequest({"type": "http"}, receive), user=object())
    return {"valid": result.config_valid, "items": len(result.items), "persisted": result.persisted}


def send(port, payload, https):
    request = Request(f"{'https' if https else 'http'}://127.0.0.1:{port}{PATH}",
                      data=payload, method="POST",
                      headers={"Host": TLS["HOST"], "Content-Type": "application/json"})
    context = ssl._create_unverified_context() if https else None
    try:
        with urlopen(request, context=context, timeout=4) as response:
            return {"status": response.status, "upstream_bytes": int(response.read().decode())}
    except HTTPError as exc:
        with exc:
            return {"status": exc.code, "nginx_413": b"413 Request Entity Too Large" in exc.read()}


def nginx_check(folder, cases):
    name = "sphere-audit-ingress-" + uuid.uuid4().hex[:10]
    network, upstream, gateway = name + "-net", name + "-up", name + "-edge"
    certs = folder / "certs"
    certs.mkdir()
    TLS["cert_files"](certs, 1)
    config = folder / "nginx.conf"
    original = (ROOT / "infrastructure/nginx/nginx.conf").read_text(encoding="utf-8")
    config.write_text(original.replace("${SERVER_HOSTNAME}", TLS["HOST"]), encoding="utf-8")
    source = folder / "fixture.py"
    source.write_text(UPSTREAM, encoding="utf-8")
    docker("image", "inspect", "python:3.12-slim", "nginx:alpine")
    docker("network", "create", network)
    try:
        docker("run", "-d", "--pull", "never", "--name", upstream, "--network", network,
               "--network-alias", "backend", "--mount",
               f"type=bind,src={source},dst=/fixture.py,readonly", "python:3.12-slim",
               "python", "/fixture.py")
        docker("run", "-d", "--pull", "never", "--name", gateway, "--network", network,
               "-p", "127.0.0.1::443", "-p", "127.0.0.1::8081", "--entrypoint", "nginx",
               "--mount", f"type=bind,src={config},dst=/tmp/nginx.conf,readonly",
               "--mount", f"type=bind,src={certs},dst=/etc/letsencrypt/live/{TLS['HOST']},readonly",
               "nginx:alpine", "-c", "/tmp/nginx.conf", "-g", "daemon off;")
        ports = {target: int(docker("port", gateway, f"{target}/tcp").stdout.strip().rsplit(":", 1)[1])
                 for target in (443, 8081)}
        deadline = time.monotonic() + 10
        while True:
            try:
                control = send(ports[443], cases["small"], True)
                if control["status"] == 200:
                    break
            except URLError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Disposable gateway or upstream did not start")
            time.sleep(0.15)
        return {str(target): {name: send(port, payload, target == 443) for name, payload in cases.items()}
                for target, port in ports.items()}
    finally:
        docker("rm", "-f", gateway, upstream, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix="sphere-audit-ingress-") as directory:
        folder = Path(directory)
        cwd = Path.cwd()
        try:
            os.chdir(folder)
            os.environ.update(JWT_SECRET_KEY="a" * 64, ENVIRONMENT="development", DEV_SKIP_AUTH="false")
            cases = {"small": fixture_body(2, 0), "large": fixture_body(96, 100)}
            preflight = {name: asyncio.run(direct_preflight(body)) for name, body in cases.items()}
            if not all(case["valid"] for case in preflight.values()):
                raise RuntimeError("Preflight fixture should use valid, read-only input")
            result = {"preview": preview_check(folder),
                      "request_bytes": {name: len(body) for name, body in cases.items()},
                      "direct_read_only_preflight": preflight,
                      "nginx_with_body_counting_upstream": nginx_check(folder, cases)}
        finally:
            os.chdir(cwd)
        print(json.dumps(result, indent=2))
