#!/usr/bin/env python3
"""Verify hashes and rehearse database restores in a disposable isolated container."""
import hashlib
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def main():
    folder = Path(sys.argv[1]).resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        p = folder / item["path"]
        h = hashlib.sha256()
        with p.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest() != item["sha256"] or p.stat().st_size != item["size"]:
            raise ValueError(f"Hash/size mismatch: {p.name}")
        if item["kind"] == "docker-volume":
            with tarfile.open(p, "r:gz") as archive:
                for member in archive:
                    if member.isfile():
                        f = archive.extractfile(member)
                        while f.read(1024 * 1024):
                            pass
    print(f"Verified {len(manifest['artifacts'])} artifact hashes and volume archives.", flush=True)
    cid = docker("run", "-d", "--network", "none", "-e", "POSTGRES_PASSWORD=rehearsal-only", "postgres:15-alpine", capture_output=True, text=True).stdout.strip()
    try:
        for _ in range(60):
            result = subprocess.run(["docker", "exec", cid, "pg_isready", "-U", "postgres"], capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        for name in ("sphereplatform", "n8n"):
            docker("exec", cid, "createdb", "-U", "postgres", name, capture_output=True)
            with (folder / f"postgres-{name}.dump").open("rb") as f:
                docker("exec", "-i", cid, "pg_restore", "-U", "postgres", "-d", name,
                       "--exit-on-error", "--no-owner", "--no-privileges", stdin=f, capture_output=True)
            sql = "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
            count = docker("exec", cid, "psql", "-U", "postgres", "-d", name, "-Atc", sql, capture_output=True, text=True).stdout.strip()
            print(f"Restored {name}: {count} public tables; no external network or ports.", flush=True)
            rows_sql = """SELECT table_name || E'\\t' ||
              (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text
              FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"""
            restored = docker("exec", cid, "psql", "-U", "postgres", "-d", name, "-Atc", rows_sql, capture_output=True, text=True).stdout.splitlines()
            live = docker("exec", "sphere-pilot-20260911-postgres-1", "sh", "-c",
                          'exec psql -U "$POSTGRES_USER" -d "$1" -Atc "$2"', "sh", name, rows_sql,
                          capture_output=True, text=True).stdout.splitlines()
            differences = len(set(restored) ^ set(live))
            print(f"{name}: compared row counts in {len(restored)} tables; {differences} differing entries against live database.", flush=True)
        with tarfile.open(folder / "volume-minio_data.tar.gz", "r:gz") as archive:
            archived = {m.name.removeprefix('./') for m in archive if m.isfile()}
        result = docker("run", "--rm", "--network", "none", "--mount",
                        "type=volume,src=sphere-pilot-20260911_minio_data,dst=/data,readonly",
                        "alpine:latest", "find", "/data", "-type", "f", capture_output=True, text=True)
        live_files = {line.removeprefix('/data/') for line in result.stdout.splitlines()}
        print(f"MinIO underlying files: archive {len(archived)}, live {len(live_files)}, path differences {len(archived ^ live_files)}; this is not an S3 object-level restore test.", flush=True)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", cid], capture_output=True)


if __name__ == "__main__":
    main()
