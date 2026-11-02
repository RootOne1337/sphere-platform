#!/usr/bin/env python3
"""Capture a live pilot snapshot. Output contains credentials: protect it as a secret."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VOLUMES = ["minio_data", "n8n_data", "redis_data", "ota_data", "device_logs",
           "identity", "pilot_ssh_identity", "certbot-data", "certbot-www"]
CONTAINERS = ["postgres", "redis", "minio", "n8n", "backend", "frontend", "nginx", "public-gateway"]
PREFIX = "sphere-pilot-20260911_"


def run_to_file(command, destination):
    temporary = destination.with_suffix(destination.suffix + ".partial")
    with temporary.open("xb") as output:
        subprocess.run(command, stdout=output, stderr=subprocess.PIPE, check=True)
    os.replace(temporary, destination)


def add(manifest, path, kind, source, consistency):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    manifest["artifacts"].append(dict(path=path.name, sha256=h.hexdigest(), size=path.stat().st_size,
                                      kind=kind, source=source, consistency=consistency))


def protect_directory(out):
    if os.name == 'nt':
        import csv
        import io
        user = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], check=True, capture_output=True, text=True)
        sid = next(csv.reader(io.StringIO(user.stdout)))[1]
        subprocess.run(['icacls', str(out), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F',
                        '*S-1-5-18:(OI)(CI)F'], check=True, capture_output=True)
    else:
        out.chmod(0o700)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/migration/backup_data.py NEW_OUTPUT_DIRECTORY")
    out = Path(sys.argv[1]).resolve()
    allowed = (ROOT / '.local-pilot' / 'migration-20261102').resolve()
    if out.is_relative_to(ROOT) and not out.is_relative_to(allowed):
        raise SystemExit('Destination must be outside repository or inside ignored migration staging')
    same_drive = os.path.splitdrive(str(out))[0].lower() == os.path.splitdrive(str(ROOT))[0].lower()
    reserve = 12 * 1024**3 if same_drive else 1024**3
    if shutil.disk_usage(out.parent).free < reserve:
        raise SystemExit('Insufficient free space: refusing backup')
    for suffix in VOLUMES:
        if subprocess.run(['docker', 'volume', 'inspect', PREFIX + suffix], capture_output=True).returncode:
            raise SystemExit(f'Missing source volume: {PREFIX + suffix}')
    for name in CONTAINERS:
        container = f'sphere-pilot-20260911-{name}-1'
        state = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', container],
                               capture_output=True, text=True, check=True).stdout.strip()
        if state != 'true':
            raise SystemExit(f'Source container is not running: {container}')
    out.mkdir(parents=False, exist_ok=False)
    protect_directory(out)
    manifest = {"version": 1, "created_utc": datetime.now(timezone.utc).isoformat(), "artifacts": []}
    pg = "sphere-pilot-20260911-postgres-1"
    try:
        for db in ("postgres", "sphereplatform", "n8n"):
            p = out / f"postgres-{db}.dump"
            run_to_file(["docker", "exec", pg, "sh", "-c", 'exec pg_dump -U "$POSTGRES_USER" -Fc "$1"', "sh", db], p)
            add(manifest, p, "postgres-custom", db, "transactionally consistent per database; separate snapshots")
        p = out / "postgres-globals.sql"
        run_to_file(["docker", "exec", pg, "sh", "-c", 'exec pg_dumpall -U "$POSTGRES_USER" --globals-only'], p)
        add(manifest, p, "postgres-globals", pg, "live globals, separate from database snapshots")
        for suffix in VOLUMES:
            volume = PREFIX + suffix
            p = out / f"volume-{suffix}.tar.gz"
            run_to_file(["docker", "run", "--rm", "--network", "none", "--mount",
                         f"type=volume,src={volume},dst=/data,readonly", "alpine:latest",
                         "tar", "czf", "-", "-C", "/data", "."], p)
            add(manifest, p, "docker-volume", volume, "live file copy; application consistency not guaranteed")
        # Container inspect contains secrets, including N8N_ENCRYPTION_KEY; never print it.
        p = out / "container-configs-sensitive.json"
        ids = [f"sphere-pilot-20260911-{name}-1" for name in CONTAINERS]
        run_to_file(["docker", "inspect", *ids], p)
        add(manifest, p, "sensitive-container-config", "pilot containers", "live inspect; contains credentials")
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Created {len(manifest['artifacts'])} artifacts in {out}; contains secrets.")
    except Exception:
        print(f"Backup incomplete: {out}; no complete manifest was written.", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
