"""Read-only Compose render and offline shell scenarios. Use the backend Python environment."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[4]
BASE = "docker-compose.yml"
FULL = "docker-compose.full.yml"
PRODUCTION = "docker-compose.production.yml"
SCREENSHOT = ["SCREENSHOT_STORAGE_ENDPOINT", "SCREENSHOT_STORAGE_ACCESS_KEY",
              "SCREENSHOT_STORAGE_SECRET_KEY"]


def compose(files, empty_env):
    content = "\n".join((ROOT / file).read_text(encoding="utf-8") for file in files)
    variables = set(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", content))
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    env.update(dict.fromkeys(variables, "audit-fixture"))
    env.update(dict.fromkeys(SCREENSHOT, "audit-fixture"))
    env.update(SERVER_HOSTNAME="audit.example.test", BACKEND_PORT="58080",
               WEB_CONCURRENCY="4", ENVIRONMENT="production")
    command = ["docker", "compose", "--env-file", str(empty_env), "-p", "audit-config-20261111"]
    for file in files:
        command.extend(["-f", file])
    return subprocess.run(command + ["config", "--format", "json"], cwd=ROOT,
                          env=env, text=True, encoding="utf-8", capture_output=True,
                          timeout=40)


def compose_evidence(tmp):
    empty_env = tmp / "empty.env"
    empty_env.touch()
    results = {}
    for label, files in (("base_production", [BASE, PRODUCTION]),
                         ("base_full_production", [BASE, FULL, PRODUCTION])):
        process = compose(files, empty_env)
        process.check_returncode()
        model = json.loads(process.stdout)
        services = model["services"]
        results[label] = {
            "host_ports": {
                name: [{k: port[k] for k in ("host_ip", "published", "target") if k in port}
                       for port in services[name].get("ports", [])]
                for name in ("postgres", "redis", "backend", "frontend", "nginx", "n8n", "minio")
            },
            "screenshot_env_forwarded": [
                key for key in SCREENSHOT if key in services["backend"]["environment"]
            ],
            "tls_named_volume": model["volumes"]["certbot-data"]["name"],
        }
    staging = compose([PRODUCTION], empty_env)
    results["staging_workflow_file_set"] = {
        "exit_code": staging.returncode,
        "diagnostic": staging.stderr.strip().splitlines()[-1] if staging.stderr.strip() else "",
    }
    return results


def write(path, content):
    path.write_text(content, encoding="utf-8", newline="\n")
    if os.name != "nt":
        path.chmod(0o700)


def shell_evidence(tmp):
    git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
    bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
    if not bash:
        raise RuntimeError("Bash is required for the offline shell scenarios")
    scripts = tmp / "scripts"
    scripts.mkdir()
    for name in ("backup-database.sh", "health-check.sh", "init_ssl.sh"):
        write(scripts / name, (ROOT / "scripts" / name).read_text(encoding="utf-8"))
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    write(bin_dir / "docker", """#!/bin/bash
if [[ "$1" == "inspect" ]]; then
    case "$2" in
        *Health*) echo unhealthy ;;
        *Running*) echo true ;;
        *) exit 1 ;;
    esac
elif [[ "$1" == "compose" || "$1" == "run" ]]; then
    printf '%s\n' "$*" >> docker-fixture.log
    if [[ "$1" == "run" && "${FIXTURE_CERTBOT_FAIL:-0}" == "1" ]]; then exit 1; fi
else
    exit 1
fi
""")
    write(bin_dir / "curl", "#!/bin/bash\nprintf 200\n")
    write(bin_dir / "sleep", "#!/bin/bash\nexit 0\n")
    write(bin_dir / "nslookup", "#!/bin/bash\nexit 0\n")
    write(tmp / ".env", "SERVER_HOSTNAME=audit.example.test\nACME_EMAIL=audit@example.test\n")
    wrapper = 'export PATH="$PWD/bin:$PATH"; exec bash "$@"'

    def run(name, *arguments, certbot_fail=False):
        env = dict(os.environ, FIXTURE_CERTBOT_FAIL=str(int(certbot_fail)))
        return subprocess.run([bash, "--noprofile", "--norc", "-c", wrapper,
                               "audit", f"scripts/{name}", *arguments], cwd=tmp,
                              env=env, text=True, encoding="utf-8", capture_output=True,
                              timeout=30)

    health = run("health-check.sh", "--json")
    health_data = json.loads(health.stdout)

    archive = tmp / "backup-fixtures"
    archive.mkdir()
    old_pg = archive / "pg_sphereplatform_old.sql.gz"
    old_redis = archive / "redis_snapshot_old.rdb"
    for path in (old_pg, old_redis):
        write(path, "fixture")
        epoch = time.time() - 30 * 86400
        os.utime(path, (epoch, epoch))
    backup = run("backup-database.sh", "--redis-only", "--dir=backup-fixtures", "--keep=7")
    documented_args = run("backup-database.sh", "--redis-only", "--dir", "documented-dir", "--keep", "14")

    certbot = run("init_ssl.sh", certbot_fail=True)
    tls_trace = (tmp / "docker-fixture.log").read_text(encoding="utf-8").splitlines()
    return {
        "health_check_on_running_unhealthy": {
            "exit_code": health.returncode,
            "docker_check": health_data["checks"]["Backend"],
            "summary": health_data["summary"],
        },
        "backup_on_failed_redis_snapshot_and_copy": {
            "exit_code": backup.returncode,
            "reports_completed": "Бэкап завершён" in backup.stdout,
            "old_postgres_file_retained": old_pg.exists(),
            "old_redis_file_retained": old_redis.exists(),
            "new_redis_files": len(list(archive.glob("redis_snapshot_20*.rdb"))),
            "documented_space_separated_args_exit_code": documented_args.returncode,
            "documented_destination_created": (tmp / "documented-dir").exists(),
            "default_destination_created": (tmp / "backups").exists(),
        },
        "certbot_failure_after_stopping_nginx": {
            "exit_code": certbot.returncode, "mock_docker_commands": tls_trace,
        },
    }


def screenshot_factory_evidence(tmp):
    probe = """
import json
from fastapi import HTTPException
from backend.services.task_screenshots import get_screenshot_storage
try:
    get_screenshot_storage()
except HTTPException as exc:
    print(json.dumps({"http_status": exc.status_code, "detail": exc.detail}))
"""
    folder = tmp / "no-storage"
    folder.mkdir()
    env = dict(os.environ, PYTHONPATH=str(ROOT), JWT_SECRET_KEY="a" * 64,
               ENVIRONMENT="production", DEV_SKIP_AUTH="false")
    env = {key: value for key, value in env.items() if not key.startswith("SCREENSHOT_STORAGE_")}
    result = subprocess.run([sys.executable, "-c", probe], env=env, cwd=folder,
                            text=True, encoding="utf-8", capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sphere-audit-config-") as directory:
        temp = Path(directory)
        result = {"compose": compose_evidence(temp), "offline_shell": shell_evidence(temp),
                  "screenshot_storage_factory_without_forwarded_environment": screenshot_factory_evidence(temp)}
        print(json.dumps(result, ensure_ascii=True, indent=2))
