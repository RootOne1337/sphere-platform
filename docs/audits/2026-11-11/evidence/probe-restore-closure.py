"""Restore a populated synthetic PostgreSQL/Redis/MinIO backup and verify data."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import uuid

from minio import Minio

ROOT = Path(__file__).resolve().parents[4]
PG_IMAGE = "postgres:15-alpine"
REDIS_IMAGE = "redis:7.2-alpine"
MINIO_IMAGE = "minio/minio:latest"
PG_OWNER = "fixture_owner"
PG_READER = "fixture_reader"
PASSWORD = "audit-fixture-only"
MINIO_USER = "restore-fixture"
BUCKET = "audit-restore-objects"
OBJECT = "tasks/example/evidence.bin"
BODY = b"Sphere isolated restore fixture\x00\x01\x02"


def docker(*args, binary=False, check=True):
    return subprocess.run(["docker", *args], capture_output=True, check=check,
                          text=not binary, timeout=25)


def until(probe, label):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Fixture not ready: {label}")


def mount(volume, destination, *, readonly=False):
    return f"type=volume,src={volume},dst={destination}" + (",readonly" if readonly else "")


def postgres(name, volume=None):
    if volume is None:
        args = ["-e", f"POSTGRES_USER={PG_OWNER}", "-e", f"POSTGRES_PASSWORD={PASSWORD}"]
        user = PG_OWNER
    else:
        args = ["--mount", mount(volume, "/var/lib/postgresql/data")]
        user = "postgres"
    docker("run", "-d", "--pull", "never", "--network", "none", "--name", name,
           *args, PG_IMAGE)
    until(lambda: docker("exec", name, "pg_isready", "-h", "127.0.0.1",
                         "-U", user, "-d", "postgres", check=False).returncode == 0, "PostgreSQL")


def sql(name, user, db, query, *, tcp=False):
    if tcp:
        flags = ["-e", f"PGPASSWORD={PASSWORD}", name, "psql", "-h", "127.0.0.1"]
    else:
        flags = [name, "psql"]
    return docker("exec", *flags, "-XAt", "-v", "ON_ERROR_STOP=1",
                  "-U", user, "-d", db, "-c", query).stdout.strip()


def redis(name, volume):
    docker("run", "-d", "--pull", "never", "--network", "none", "--name", name,
           "--mount", mount(volume, "/data"), REDIS_IMAGE,
           "redis-server", "--appendonly", "yes", "--appendfsync", "always")
    until(lambda: docker("exec", name, "redis-cli", "ping", check=False).stdout.strip() == "PONG",
          "Redis")


def minio(name, volume):
    docker("run", "-d", "--pull", "never", "--name", name, "-p", "127.0.0.1::9000",
           "-e", f"MINIO_ROOT_USER={MINIO_USER}", "-e", f"MINIO_ROOT_PASSWORD={PASSWORD}",
           "--mount", mount(volume, "/data"), MINIO_IMAGE, "server", "/data")
    port = int(docker("port", name, "9000/tcp").stdout.strip().rsplit(":", 1)[1])

    def ready():
        with urlopen(f"http://127.0.0.1:{port}/minio/health/ready", timeout=1) as response:
            return response.status == 200

    until(ready, "MinIO")
    return port


def minio_client(port):
    return Minio(f"127.0.0.1:{port}", access_key=MINIO_USER, secret_key=PASSWORD,
                 secure=False, region="us-east-1")


def object_sha(port):
    response = minio_client(port).get_object(BUCKET, OBJECT)
    try:
        return hashlib.sha256(response.read()).hexdigest()
    finally:
        response.close()
        response.release_conn()


def run(folder):
    token = uuid.uuid4().hex[:10]
    prefix = f"sphere-audit-restore-{token}"
    project = f"migration-audit-close-{token}"
    pg_in, redis_in, minio_in, pg_out, redis_out, minio_out = (
        f"{prefix}-{part}" for part in
        ("pg-source", "redis-source", "minio-source", "pg-target", "redis-target", "minio-target")
    )
    vol_redis, vol_minio = f"{prefix}-redis", f"{prefix}-minio"
    target_pg, target_redis, target_minio = (f"{project}_{suffix}" for suffix in
                                            ("postgres_data", "redis_data", "minio_data"))
    source_volumes = [vol_redis, vol_minio]
    target_volumes = [target_pg, target_redis, target_minio]
    docker("image", "inspect", PG_IMAGE, REDIS_IMAGE, MINIO_IMAGE, "alpine:latest")
    for volume in source_volumes + target_volumes:
        if docker("volume", "inspect", volume, check=False).returncode == 0:
            raise RuntimeError("Fixture volume already exists")
    expected = hashlib.sha256(BODY).hexdigest()
    try:
        for volume in source_volumes:
            docker("volume", "create", volume)
        postgres(pg_in)
        sql(pg_in, PG_OWNER, "postgres", f"CREATE ROLE {PG_READER} LOGIN PASSWORD '{PASSWORD}'")
        for db in ("sphereplatform", "n8n"):
            sql(pg_in, PG_OWNER, "postgres", f"CREATE DATABASE {db}")
        sql(pg_in, PG_OWNER, "sphereplatform",
            f"CREATE TABLE fixture_pointer (object_key text, sha text); "
            f"INSERT INTO fixture_pointer VALUES ('{OBJECT}', '{expected}'); "
            f"GRANT SELECT ON fixture_pointer TO {PG_READER}")
        sql(pg_in, PG_OWNER, "n8n",
            f"CREATE TABLE fixture_workflow (label text); INSERT INTO fixture_workflow VALUES ('example'); "
            f"GRANT SELECT ON fixture_workflow TO {PG_READER}")
        redis(redis_in, vol_redis)
        assert docker("exec", redis_in, "redis-cli", "SET", "fixture:terminal", "completed").stdout.strip() == "OK"
        port = minio(minio_in, vol_minio)
        source = minio_client(port)
        source.make_bucket(BUCKET)
        source.put_object(BUCKET, OBJECT, io.BytesIO(BODY), len(BODY))
        assert object_sha(port) == expected
        docker("stop", "--time", "5", redis_in, minio_in)

        payloads = {}
        for db in ("sphereplatform", "n8n"):
            payloads[f"postgres-{db}.dump"] = ("postgres-custom", docker(
                "exec", pg_in, "pg_dump", "-U", PG_OWNER, "-Fc", db, binary=True).stdout)
        payloads["postgres-globals.sql"] = ("postgres-globals", docker(
            "exec", pg_in, "pg_dumpall", "-U", PG_OWNER, "--globals-only", binary=True).stdout)
        for label, volume in (("redis_data", vol_redis), ("minio_data", vol_minio)):
            payloads[f"volume-{label}.tar.gz"] = ("docker-volume", docker(
                "run", "--rm", "--pull", "never", "--network", "none", "--mount",
                mount(volume, "/data", readonly=True), "alpine:latest",
                "tar", "czf", "-", "-C", "/data", ".", binary=True).stdout)
        artifacts = []
        for name, (kind, data) in payloads.items():
            (folder / name).write_bytes(data)
            artifacts.append({"path": name, "kind": kind, "sha256": hashlib.sha256(data).hexdigest(),
                              "size": len(data)})
        (folder / "manifest.json").write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
        password_file = folder / "fixture-password"
        password_file.write_text(PASSWORD, encoding="utf-8")
        subprocess.run([sys.executable, str(ROOT / "scripts/migration/restore_data.py"), str(folder),
                        "--project", project, "--compose-volumes", "--preserve-roles",
                        "--database", "sphereplatform", "--database", "n8n",
                        "--volume", "redis_data", "--volume", "minio_data",
                        "--pg-password-file", str(password_file)],
                       check=True, capture_output=True, timeout=90)
        postgres(pg_out, target_pg)
        pointer = sql(pg_out, PG_READER, "sphereplatform", "SELECT object_key || '|' || sha FROM fixture_pointer", tcp=True)
        workflow = sql(pg_out, PG_READER, "n8n", "SELECT label FROM fixture_workflow", tcp=True)
        owners = sql(pg_out, "postgres", "postgres",
                     "SELECT count(*) FROM pg_database WHERE datname IN ('sphereplatform','n8n') "
                     f"AND pg_get_userbyid(datdba)='{PG_OWNER}'")
        redis(redis_out, target_redis)
        value = docker("exec", redis_out, "redis-cli", "GET", "fixture:terminal").stdout.strip()
        restored_port = minio(minio_out, target_minio)
        checksum = object_sha(restored_port)
        result = {"restore_cli_exit": 0, "restored_database_owners": int(owners),
                  "restricted_reader_pg_login_and_pointer": pointer == f"{OBJECT}|{expected}",
                  "restricted_reader_n8n_fixture_read": workflow == "example",
                  "redis_aof_fixture_read": value == "completed",
                  "restored_minio_matches_postgres_pointer_sha256": checksum == expected}
        assert all(value is True for name, value in result.items()
                   if name not in {"restore_cli_exit", "restored_database_owners"})
        assert int(owners) == 2
        env = dict(os.environ, JWT_SECRET_KEY="a" * 64, DEV_SKIP_AUTH="false",
                   SPHERE_TEST_MINIO_ENDPOINT=f"127.0.0.1:{restored_port}",
                   SPHERE_TEST_MINIO_USER=MINIO_USER, SPHERE_TEST_MINIO_PASSWORD=PASSWORD)
        test = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               "tests/test_scripts/test_task_screenshot_minio.py"],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        if test.returncode != 0 or "1 passed" not in test.stdout:
            raise RuntimeError(f"Real S3 read regression was not passed: {test.stdout[-1500:]}")
        result["real_s3_authenticated_manifest_content_and_missing_object"] = "1 passed"
        return result
    finally:
        for name in (pg_in, redis_in, minio_in, pg_out, redis_out, minio_out):
            docker("rm", "-f", "-v", name, check=False)
        for volume in source_volumes + target_volumes:
            docker("volume", "rm", volume, check=False)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sphere-audit-restore-") as directory:
        print(json.dumps(run(Path(directory)), indent=2))
