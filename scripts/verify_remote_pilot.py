"""Opt-in acceptance against an owner's prepared pilot; creates/deletes one probe device.

Requires httpx and websockets. Secrets come from ignored local files, never argv.
This is an HTTP/WS protocol probe, not execution of the Android APK.
"""

import argparse
import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from websockets import connect


async def restart_gateway(project):
    """Explicit fault injection into one isolated local pilot gateway only."""
    assert project.startswith("sphere-pilot-"), "Only an explicitly named isolated pilot is allowed"
    process = await asyncio.create_subprocess_exec("docker", "ps", "-q", "--filter",
        "label=com.docker.compose.project=" + project, "--filter",
        "label=com.docker.compose.service=public-gateway", stdout=asyncio.subprocess.PIPE)
    output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    ids = output.decode().split()
    assert process.returncode == 0 and len(ids) == 1, "Expected exactly one pilot public gateway"
    process = await asyncio.create_subprocess_exec("docker", "restart", ids[0],
        stdout=asyncio.subprocess.PIPE)
    await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, "Gateway restart failed"


async def verify(args):
    base = args.base_url.rstrip("/")
    assert base.startswith("https://"), "A public pilot must use HTTPS"
    credentials = json.loads(args.credentials_file.read_text(encoding="utf-8"))
    config = json.loads(args.enrollment_config.read_text(encoding="utf-8"))
    evidence = {"time_utc": datetime.now(timezone.utc).isoformat(), "url": base,
        "installed_apk": False, "checks": [], "probe_device_deleted": False}
    device_id = None
    auth = None
    try:
        async with httpx.AsyncClient(base_url=base, timeout=20, follow_redirects=False) as client:
            # Verify the selected installation before submitting its credentials.
            for path in ("/api/v1/config/agent", "/api/v1/config/agent?environment=development",
                         "//api/v1/config/agent", "/api/v1/config/%61gent"):
                response = await client.get(base + path)
                assert response.status_code == 200, f"Discovery status {response.status_code}"
                discovery = response.json()
                assert discovery["installation_id"] == args.installation_id
                assert not {"api_key", "enrollment_api_key", "access_token", "refresh_token"} & discovery.keys()
                assert config["enrollment_api_key"] not in response.text
            evidence["checks"].append("credential-free discovery including normalized path variants")
            response = await client.post("/api/v1/auth/login", json={
                "email": credentials["email"], "password": credentials["password"]})
            assert response.status_code == 200, f"Login status {response.status_code}"
            auth = {"Authorization": "Bearer " + response.json()["access_token"]}
            evidence["checks"].append("public HTTPS operator login")
            try:
                registration = await client.post("/api/v1/devices/register",
                    headers={"X-API-Key": config["enrollment_api_key"]},
                    json={"fingerprint": "remote-pilot-probe-" + uuid.uuid4().hex,
                          "model": "Synthetic protocol acceptance (not an APK)", "device_type": "physical"})
                assert registration.status_code == 201, f"Registration status {registration.status_code}"
                identity = registration.json()
                device_id = identity["device_id"]
                evidence["device_id"] = device_id
                evidence["checks"].append("one authenticated registration")
                uri = "wss://" + base.removeprefix("https://") + "/ws/android/" + device_id
                for attempt in range(2):
                    async with connect(uri, open_timeout=20, close_timeout=5, ping_interval=15) as socket:
                        started = time.monotonic()
                        await socket.send(json.dumps({"type": "auth", "token": identity["access_token"]}))
                        ack = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
                        assert ack["type"] == "auth_ok" and ack["device_id"] == device_id
                        evidence["checks"].append({"ws_auth_attempt": attempt + 1,
                            "auth_ack_ms": round((time.monotonic() - started) * 1000, 1)})
                        if attempt == 0:
                            while True:
                                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=40))
                                if message.get("type") == "ping":
                                    await socket.send(json.dumps({"type": "pong", "ts": message["ts"]}))
                                    evidence["checks"].append("server heartbeat received and pong sent")
                                    break
                            response = await client.get(f"/api/v1/devices/{device_id}", headers=auth)
                            assert response.status_code == 200
                            evidence["checks"].append("operator can read the registered device")
                            if args.restart_gateway_project:
                                await restart_gateway(args.restart_gateway_project)
                                await asyncio.wait_for(socket.wait_closed(), timeout=15)
                                evidence["checks"].append("isolated gateway restart interrupted the live WebSocket")
                                deadline = time.monotonic() + 30
                                while True:
                                    try:
                                        ready = await client.get("/api/v1/health/readyz", timeout=5)
                                        if ready.status_code == 200:
                                            break
                                    except httpx.HTTPError:
                                        pass
                                    assert time.monotonic() < deadline, "Gateway did not recover"
                                    await asyncio.sleep(1)
                    # Only this probe's connection closes. Same credentials reconnect,
                    # unless explicit gateway fault injection was selected above.
                evidence["checks"].append("WebSocket reconnect with original device credentials")
            finally:
                if device_id is not None:
                    response = await client.delete(f"/api/v1/devices/{device_id}", headers=auth)
                    assert response.status_code == 204, f"Probe cleanup status {response.status_code}"
                    evidence["probe_device_deleted"] = True
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--enrollment-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restart-gateway-project",
        help="Opt-in fault injection: restart public-gateway of this local sphere-pilot-* project")
    asyncio.run(verify(parser.parse_args()))


if __name__ == "__main__":
    main()
