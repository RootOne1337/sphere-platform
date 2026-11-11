"""Start the pinned TURN config and verify TLS with synthetic fixture identity."""

import json
from pathlib import Path
import runpy
import socket
import ssl
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
TLS = runpy.run_path(str(Path(__file__).with_name("probe-nginx-renewal.py")))
IMAGE = "coturn/coturn@sha256:59af4221a2c45c1195a1a4a865542b3ea744be1dd8e228d11bde87c6631081cf"


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, check=check,
                          text=True, timeout=20)


def bind(source, target):
    return f"type=bind,src={source},dst={target},readonly"


def run(folder):
    name = f"sphere-audit-turn-{uuid.uuid4().hex[:10]}"
    entrypoint = folder / "entrypoint.sh"
    entrypoint.write_text((ROOT / "infrastructure/turn/entrypoint.sh").read_text(encoding="utf-8"),
                          encoding="utf-8", newline="\n")
    TLS["cert_files"](folder, 1)
    key = folder / "rest-key"
    key.write_text("a" * 64, encoding="utf-8")
    command = ["run", "-d", "--pull", "never", "--name", name, "--read-only", "--user", "65534:65534",
               "--cap-drop", "ALL", "--cap-add", "NET_BIND_SERVICE",
               "--security-opt", "no-new-privileges:true",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=4m,mode=1777",
               "-p", "127.0.0.1::5349", "-e", f"SPHERE_TURN_HOST={TLS['HOST']}",
               "--mount", bind(ROOT / "infrastructure/turn/turnserver.conf", "/etc/sphere-turn/turnserver.conf"),
               "--mount", bind(entrypoint, "/etc/sphere-turn/entrypoint.sh"),
               "--mount", bind(key, "/run/secrets/turn-rest-key"),
               "--mount", bind(folder / "fullchain.pem", "/run/secrets/turn-tls-chain.pem"),
               "--mount", bind(folder / "privkey.pem", "/run/secrets/turn-tls-key.pem"),
               "--entrypoint", "/bin/sh", IMAGE, "/etc/sphere-turn/entrypoint.sh"]
    docker("image", "inspect", IMAGE)
    try:
        docker(*command)
        port = int(docker("port", name, "5349/tcp").stdout.strip().rsplit(":", 1)[1])
        context = ssl.create_default_context(cafile=str(folder / "fullchain.pem"))
        deadline = time.monotonic() + 10
        version = None
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1) as connection:
                    with context.wrap_socket(connection, server_hostname=TLS["HOST"]) as secured:
                        version = secured.version()
                        break
            except OSError:
                time.sleep(0.2)
        if version is None:
            state = docker("inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", name, check=False)
            raise RuntimeError(f"Local TURN TLS did not become available: {state.stdout.strip()}")
        stun = docker("exec", name, "turnutils_stunclient", "-p", "3478", "127.0.0.1", check=False)
        return {"pinned_image": True, "started_as_non_root": True,
                "loopback_tls_verified": version,
                "stun_binding_utility_exit": stun.returncode,
                "stun_binding_mapped_address_returned": "reflexive addr" in stun.stdout.lower()}
    finally:
        docker("rm", "-f", name, check=False)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sphere-audit-turn-") as directory:
        print(json.dumps(run(Path(directory)), indent=2))
