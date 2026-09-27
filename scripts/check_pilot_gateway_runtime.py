"""Read-only guard for a pilot public gateway and its generated nginx config.

The bind-mounted source can change while the internal nginx master still uses
an older /tmp/nginx.generated.conf. Check both files and the actual upstream
request before reloading either container. Never inspect legacy projects.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def upstream_port(gateway_config: str) -> int:
    match = re.search(r"\bset\s+\$pilot_upstream\s+http://nginx:(\d+);", gateway_config)
    if not match:
        raise ValueError("public gateway upstream is not a fixed nginx port")
    return int(match.group(1))


def listens_on(config: str, port: int) -> bool:
    return re.search(rf"\blisten\s+{port}\s+default_server\s*;", config) is not None


def docker(*args: str) -> str:
    completed = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=12,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"docker {args[0]} failed")
    return completed.stdout


def checked_container(project: str, service: str) -> str:
    name = f"{project}-{service}-1"
    info = json.loads(docker("inspect", name))[0]
    labels = info["Config"].get("Labels") or {}
    if labels.get("com.docker.compose.project") != project or labels.get(
        "com.docker.compose.service"
    ) != service:
        raise RuntimeError(f"unexpected Compose identity for {service}")
    if info["State"]["Status"] != "running":
        raise RuntimeError(f"{service} is not running")
    return name


def check(project: str, source: Path) -> dict[str, object]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", project):
        raise ValueError("invalid pilot Compose project")
    internal = checked_container(project, "nginx")
    edge = checked_container(project, "public-gateway")
    gateway = docker("exec", edge, "cat", "/etc/nginx/remote-pilot.conf")
    generated = docker("exec", internal, "cat", "/tmp/nginx.generated.conf")
    template = source.read_text(encoding="utf-8")
    port = upstream_port(gateway)
    if not listens_on(template, port):
        raise RuntimeError("source nginx template has no public gateway listener")
    if not listens_on(generated, port):
        raise RuntimeError("running nginx generated config is stale")
    result = docker(
        "exec", edge, "wget", "-T", "3", "-qO-",
        f"http://nginx:{port}/api/v1/health/readyz",
    )
    if json.loads(result).get("status") != "ready":
        raise RuntimeError("public gateway upstream readiness failed")
    return {
        "project": project,
        "upstream_port": port,
        "generated_config_matches_listener": True,
        "upstream_ready": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "infrastructure/nginx/nginx.conf"
    try:
        print(json.dumps(check(args.project, source)))
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(
            json.dumps({"project": args.project, "ready": False, "reason": str(exc)}),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
