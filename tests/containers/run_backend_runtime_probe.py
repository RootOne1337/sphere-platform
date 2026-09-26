"""Run the packaged runtime probe with private, throwaway Docker services.

Requires a prebuilt backend image. No host ports, existing databases or API
listeners are used. Only containers created and verified by this invocation are
removed; PostgreSQL stores data on tmpfs, not a persistent volume.
"""

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path


def docker(*args, timeout=120):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
        encoding="utf-8", timeout=timeout, check=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    run_id = "sphere-image-audit-" + uuid.uuid4().hex[:12]
    label = "sphere.audit.runtime=" + run_id
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    probe = Path(__file__).resolve().with_name("backend_runtime_probe.py")
    image_id = docker("image", "inspect", args.image, "--format", "{{.Id}}")
    network_id = None
    owned = []
    summary = {"image_id": image_id, "network_internal": True, "host_ports": [],
        "api_listener": False, "source_mount": False, "environment": "development",
        "scenario": "fresh migrations, CLI bootstrap, real app lifespan/ASGI login/registration/visibility, repeat in new processes",
        "apk_installed": False, "containers_removed": False}
    try:
        network_id = docker("network", "create", "--internal", "--label", label, run_id)
        for suffix, image, options in [
            ("postgres", "postgres:15-alpine", ["--tmpfs", "/var/lib/postgresql/data:rw,nosuid,nodev,size=256m",
                "-e", "POSTGRES_DB=sphere_image_audit", "-e", "POSTGRES_USER=audit",
                "-e", "POSTGRES_PASSWORD=isolated-image-database",
                "--health-cmd", "pg_isready -U audit -d sphere_image_audit"]),
            ("redis", "redis:7.2-alpine", ["--tmpfs", "/data:rw,nosuid,nodev,size=32m",
                "--health-cmd", "redis-cli ping"]),
        ]:
            container = docker("run", "-d", "--name", run_id + "-" + suffix, "--label", label,
                "--network", network_id, "--network-alias", suffix, "--health-interval", "1s",
                "--health-timeout", "3s", "--health-retries", "30", *options, image)
            owned.append(container)
        deadline = time.monotonic() + 60
        while True:
            states = [docker("inspect", item, "--format", "{{.State.Health.Status}}") for item in owned]
            if states == ["healthy", "healthy"]:
                break
            if "unhealthy" in states or time.monotonic() > deadline:
                raise RuntimeError(f"Disposable services not ready: {states}")
            time.sleep(0.5)
        env = {"POSTGRES_URL": "postgresql+asyncpg://audit:isolated-image-database@postgres:5432/sphere_image_audit",
            "REDIS_URL": "redis://redis:6379/0", "REDIS_PASSWORD": "",
            "ENVIRONMENT": "development", "JWT_SECRET_KEY": "isolated-image-runtime-1fc57ee290664f789ddc",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
            "SERVER_PUBLIC_URL": "http://image-probe.local", "WG_ROUTER_URL": "http://127.0.0.1:1"}
        flags = [part for key, value in env.items() for part in ("-e", key + "=" + value)]
        container = docker("create", "--name", run_id + "-probe", "--label", label,
            "--network", network_id, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--mount",
            f"type=bind,source={probe},target=/tmp/backend_runtime_probe.py,readonly",
            *flags, image_id, "python", "/tmp/backend_runtime_probe.py")
        owned.append(container)
        result = subprocess.run(["docker", "start", "-a", container], capture_output=True,
            text=True, encoding="utf-8", timeout=240)
        output = result.stdout + result.stderr
        (evidence / "image-runtime-probe.txt").write_text(output, encoding="utf-8")
        summary["exit_code"] = int(docker("inspect", container, "--format", "{{.State.ExitCode}}"))
        print(output, flush=True)
        if result.returncode or summary["exit_code"]:
            raise RuntimeError("Packaged runtime probe failed; see recorded output")
    finally:
        # Match both immutable Docker ID and unique ownership label before cleanup.
        for container in reversed(owned):
            info = json.loads(docker("inspect", container))[0]
            assert info["Id"] == container and info["Config"]["Labels"].get("sphere.audit.runtime") == run_id
            docker("rm", "-f", "-v", container)
        summary["containers_removed"] = True
        if network_id:
            info = json.loads(docker("network", "inspect", network_id))[0]
            assert info["Id"] == network_id and info["Labels"].get("sphere.audit.runtime") == run_id
            docker("network", "rm", network_id)
        (evidence / "image-runtime-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
