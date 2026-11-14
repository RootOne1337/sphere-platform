"""Run short production bootstrap and restore checks with a disposable PostgreSQL."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from urllib.parse import quote, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[4]
IMAGE = "postgres:15-alpine"
PASSWORD = "audit-only-local"


def docker(*args, check=True, binary=False, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, check=check,
                          text=not binary, timeout=30, **kwargs)


def app_env(url):
    return dict(os.environ, PYTHONPATH=str(ROOT), POSTGRES_URL=url,
                JWT_SECRET_KEY="a" * 64, DEV_SKIP_AUTH="false", ENVIRONMENT="production")


def compose_url(folder):
    files = ["docker-compose.yml", "docker-compose.production.yml"]
    contents = "\n".join((ROOT / file).read_text(encoding="utf-8") for file in files)
    variables = re.findall(r"\$\{([A-Z][A-Z0-9_]*)", contents)
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    env.update(dict.fromkeys(variables, "audit-fixture"))
    env.update(POSTGRES_USER="postgres", POSTGRES_PASSWORD=PASSWORD,
               POSTGRES_URL="postgresql+asyncpg://audit_runtime:fixture@postgres:5432/sphereplatform")
    env_file = folder / "empty.env"
    env_file.touch()
    result = docker("compose", "--env-file", str(env_file), "-f", str(ROOT / files[0]),
                    "-f", str(ROOT / files[1]), "config", "--format", "json",
                    cwd=folder, env=env)
    services = json.loads(result.stdout)["services"]
    postgres_user = services["postgres"]["environment"]["POSTGRES_USER"]
    user = urlsplit(services["backend"]["environment"]["POSTGRES_URL"]).username
    return {"bootstrap_user_used_for_backend": user == postgres_user,
            "supplied_runtime_url_used": user == "audit_runtime"}


def run_guard_and_alembic(folder, container, port):
    source = (
        "import asyncio, json\n"
        "from sqlalchemy import text\n"
        "from backend.database.engine import engine\n"
        "from backend.core.startup_checks import check_db_role_not_superuser\n"
        "async def main():\n"
        "    async with engine.connect() as conn:\n"
        "        is_superuser = await conn.scalar(text('SELECT rolsuper FROM pg_roles WHERE rolname=current_user'))\n"
        "    try:\n"
        "        await check_db_role_not_superuser()\n"
        "        rejected = False\n"
        "    except RuntimeError as exc:\n"
        "        rejected = 'SUPERUSER or BYPASSRLS' in str(exc)\n"
        "    await engine.dispose()\n"
        "    print(json.dumps(dict(connected=True, role_is_superuser=is_superuser, production_guard_rejected=rejected)))\n"
        "asyncio.run(main())\n"
    )
    base_url = f"postgresql+asyncpg://postgres:{PASSWORD}@127.0.0.1:{port}/sphereplatform"
    result = subprocess.run([sys.executable, "-c", source], cwd=folder,
                            env=app_env(base_url), capture_output=True,
                            text=True, check=True, timeout=15)
    guard = json.loads(result.stdout)

    # A real PostgreSQL login whose password contains characters escaped in a DSN.
    fixture_password = "fixture@percent%"
    docker("exec", container, "psql", "-U", "postgres", "-d", "sphereplatform",
           "-v", "ON_ERROR_STOP=1", "-c",
           f"CREATE ROLE audit_migrate LOGIN PASSWORD '{fixture_password}'")
    dsn = f"postgresql+asyncpg://audit_migrate:{quote(fixture_password, safe='')}@127.0.0.1:{port}/sphereplatform"
    connectivity = subprocess.run([sys.executable, "-c",
        "import asyncio, asyncpg, os;\n"
        "async def main():\n"
        "    conn = await asyncpg.connect(os.environ['POSTGRES_URL'].replace('+asyncpg', ''));\n"
        "    try: print(await conn.fetchval('SELECT 1'))\n"
        "    finally: await conn.close()\n"
        "asyncio.run(main())"], cwd=folder, env=app_env(dsn), text=True,
        capture_output=True, check=True, timeout=15)
    config = folder / "alembic.ini"
    original = (ROOT / "alembic/alembic.ini").read_text(encoding="utf-8")
    config.write_text(original.replace("script_location = alembic",
                                       f"script_location = {(ROOT / 'alembic').as_posix()}"),
                      encoding="utf-8")
    alembic = [sys.executable, "-m", "alembic", "-c", str(config), "current"]
    attempts = []
    for candidate in (base_url, dsn):
        result = subprocess.run(alembic, cwd=folder, env=app_env(candidate),
                                text=True, capture_output=True, timeout=15)
        attempts.append(result)
    return guard, {
        "direct_escaped_dsn_select_1": connectivity.stdout.strip() == "1",
        "alembic_control_exit": attempts[0].returncode,
        "alembic_escaped_dsn_exit": attempts[1].returncode,
        "alembic_configparser_interpolation_error": "invalid interpolation syntax" in attempts[1].stderr,
    }


def restore_probe(folder, container, unique):
    folder.mkdir()
    data = {
        "postgres-sphereplatform.dump": (
            "postgres-custom", docker("exec", container, "pg_dump", "-U", "postgres", "-Fc",
                                      "sphereplatform", binary=True).stdout),
        "postgres-globals.sql": (
            "postgres-globals", docker("exec", container, "pg_dumpall", "-U", "postgres",
                                       "--globals-only", binary=True).stdout),
    }
    artifacts = []
    for name, (kind, payload) in data.items():
        (folder / name).write_bytes(payload)
        artifacts.append({"path": name, "kind": kind, "size": len(payload),
                          "sha256": hashlib.sha256(payload).hexdigest()})
    (folder / "manifest.json").write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    password_file = folder / "fixture-password.txt"
    password_file.write_text(PASSWORD, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("restore_data", ROOT / "scripts/migration/restore_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    underlying = module.docker
    results = {}

    for key, switches in (("preserve_roles", ["--preserve-roles"]), ("without_roles_control", [])):
        project = f"migration-audit-{unique}-{key.replace('_', '-')}"
        volume = project + "_postgres_data"
        if docker("volume", "inspect", volume, check=False).returncode == 0:
            raise RuntimeError("Fixture volume unexpectedly exists")
        trace = []

        def record(*args, **kwargs):
            try:
                return underlying(*args, **kwargs)
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
                trace.append({"role_already_exists": 'role "postgres" already exists' in stderr,
                              "failed_stage": "globals_psql" if "psql" in args else "other"})
                raise

        arguments = ["restore_data.py", str(folder), "--project", project, "--compose-volumes",
                     "--database", "sphereplatform", "--pg-password-file", str(password_file), *switches]
        out = io.StringIO()
        failed = False
        try:
            with patch.object(sys, "argv", arguments), patch.object(module, "docker", record):
                with contextlib.redirect_stdout(out):
                    try:
                        module.main()
                    except subprocess.CalledProcessError:
                        failed = True
            results[key] = {"failed": failed, "database_reported_restored": "Restored database " in out.getvalue(),
                            "errors": trace}
        finally:
            if docker("volume", "inspect", volume, check=False).returncode == 0:
                docker("volume", "rm", volume)
    return results


def main():
    unique = uuid.uuid4().hex[:10]
    name = f"sphere-audit-prod-db-{unique}"
    docker("image", "inspect", IMAGE)
    with tempfile.TemporaryDirectory(prefix="sphere-audit-prod-db-") as directory:
        folder = Path(directory)
        compose = compose_url(folder)
        try:
            docker("run", "-d", "--pull", "never", "--name", name, "-p", "127.0.0.1::5432",
                   "-e", f"POSTGRES_PASSWORD={PASSWORD}", "-e", "POSTGRES_USER=postgres",
                   "-e", "POSTGRES_DB=sphereplatform", IMAGE)
            deadline = time.monotonic() + 20
            while docker("exec", name, "pg_isready", "-h", "127.0.0.1", "-d", "sphereplatform",
                         "-U", "postgres", check=False).returncode != 0:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Fixture PostgreSQL did not start")
                time.sleep(0.2)
            port = int(docker("port", name, "5432/tcp").stdout.strip().rsplit(":", 1)[1])
            guard, alembic = run_guard_and_alembic(folder, name, port)
            restore = restore_probe(folder / "snapshot", name, unique)
        finally:
            docker("rm", "-f", "-v", name, check=False)
    print(json.dumps({"compose": compose, "production_startup_guard": guard,
                      "alembic": alembic, "restore": restore}, indent=2))


if __name__ == "__main__":
    main()
