"""Install only the reviewed additive VPN catalog with recovery evidence.

The legacy schema-free installer remains unchanged. No VPN tunnels, game
commands, APK installation or device permissions are touched by this tool.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

from scripts.pilot import install_reviewed_backend as live
from scripts.pilot.install_reviewed_web import freeze_compose, write
from scripts.pilot.local_backend_artifact import admit_local, command
from scripts.pilot.local_ci import execution_lock
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.reviewed_image_archive import bounded_json, require
from scripts.pilot.vpn_catalog_release import CATALOG_HEAD, PREVIOUS_HEAD, validate_transition

ROOT = Path(__file__).resolve().parents[2]
ENV_KEYS = {"VPN_PROFILE_ENCRYPTION_KEYS", "VPN_PROFILE_POSTGRES_URL"}


def secrets_environment(path: Path, primary: dict) -> dict[str, str]:
    path = live.workspace_path(path, private=True)
    data = bounded_json(path, 8192)
    require(
        isinstance(data, dict)
        and data.get("VPN_PROFILE_DATABASE_ROLE") == "sphere_vpn_catalog"
        and re.fullmatch(r"[a-f0-9]{64}", data.get("VPN_PROFILE_DATABASE_PASSWORD", ""))
        and data.get("activated") is False,
        "Staged catalog credential identity changed",
    )
    env = {key: data.get(key) for key in ENV_KEYS}
    require(
        all(
            isinstance(v, str) and v and len(v) < 4096 and not any(c in v for c in "\n\r\0")
            for v in env.values()
        ),
        "Invalid catalog secret format",
    )
    Fernet(env["VPN_PROFILE_ENCRYPTION_KEYS"].encode())
    url, old = make_url(env["VPN_PROFILE_POSTGRES_URL"]), make_url(primary["POSTGRES_URL"])
    require(
        url.drivername == "postgresql+asyncpg"
        and url.username == "sphere_vpn_catalog"
        and url.password == data["VPN_PROFILE_DATABASE_PASSWORD"]
        and not url.query
        and old.username != url.username
        and (url.host, url.port or 5432, url.database)
        == (old.host, old.port or 5432, old.database),
        "Catalog database identity changed",
    )
    require(
        not primary.get("VPN_PROFILE_ENCRYPTION_KEYS", "").strip()
        and not primary.get("VPN_PROFILE_POSTGRES_URL", "").strip(),
        "Existing catalog credentials require explicit rotation/reconciliation",
    )
    require(
        env["VPN_PROFILE_ENCRYPTION_KEYS"]
        not in {
            primary.get("JWT_SECRET_KEY"),
            primary.get("ACCOUNT_CREDENTIAL_KEYS"),
            primary.get("VPN_KEY_ENCRYPTION_KEY"),
        },
        "Catalog key must be independent",
    )
    return env


def validate_delta(old: dict, candidate: dict, tag: str, env: dict) -> None:
    require(set(env) == ENV_KEYS, "Unexpected catalog environment keys")
    adjusted = copy.deepcopy(candidate)
    current = adjusted["services"]["backend"]["environment"]
    previous = old["services"]["backend"]["environment"]
    for key, value in env.items():
        require(current.get(key) == value, "Catalog environment mismatch")
        if key in previous:
            current[key] = previous[key]
        else:
            current.pop(key)
    live.validate_delta(old, adjusted, tag)


def recovery_evidence(backup: Path, restored: Path, source: str) -> dict:
    backup = live.workspace_path(backup, private=True)
    restored = live.workspace_path(restored, private=True)
    require(backup.stat().st_size <= 512 * 1024 * 1024, "Backup exceeds budget")
    info = bounded_json(backup.parent / "receipt.json", 16384)
    require(
        info.get("databaseHeads") == [PREVIOUS_HEAD]
        and info.get("databaseBackup", {}).get("fullRestoreTested") is False,
        "Original backup receipt changed",
    )
    with backup.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    require(digest == info["databaseBackup"]["sha256"], "Backup bytes changed")
    result = bounded_json(restored, 16384)
    require(
        result.get("state") == "success"
        and result.get("archiveRestored") is True
        and result.get("minimalRoleHttpLifecycle") is True
        and result.get("legacyRowCountsPreserved") is True
        and result.get("isolatedServicesRemoved") is True
        and result.get("liveMigrationPerformed") is False
        and result.get("restoredSchemaHead") == CATALOG_HEAD,
        "Isolated restore/migration evidence incomplete",
    )
    # Explicit bytes binding is required, not merely a claim that some database
    # restored. Old operational receipts can be paired only after verification.
    require(result.get("backupSha256") == digest, "Restore belongs to another backup")
    require(
        result.get("migrationWorkerSha256")
        == hashlib.sha256(
            (ROOT / "scripts/pilot/vpn_catalog_db_worker.py").read_bytes()
        ).hexdigest(),
        "Restore used another migration worker",
    )
    revision = result.get("sourceRevision", "")
    require(
        bool(re.fullmatch(r"[a-f0-9]{40}", revision))
        and not command(["git", "diff", revision, source, "--", "backend", "alembic"]),
        "Restored candidate source differs",
    )
    return {
        "backupSha256": digest,
        "restoreReceiptSha256": hashlib.sha256(restored.read_bytes()).hexdigest(),
    }


def prepare_database(image: str, current: dict, secret: Path, env: dict, output: Path) -> dict:
    worker = ROOT / "scripts/pilot/vpn_catalog_db_worker.py"
    tool_source = command(["git", "rev-parse", "HEAD"])
    require(
        not command(
            [
                "git",
                "diff",
                tool_source,
                "--",
                "scripts/pilot/vpn_catalog_db_worker.py",
                "scripts/pilot/install_vpn_catalog.py",
            ]
        ),
        "Uncommitted catalog migration tooling",
    )
    pg = live.inspect(live.POSTGRES)
    networks = set(current["NetworkSettings"]["Networks"]) & set(pg["NetworkSettings"]["Networks"])
    require(len(networks) == 1, "Ambiguous API/database network")
    original = dict(v.split("=", 1) for v in current["Config"]["Env"] if "=" in v)
    environment = {key: original[key] for key in ["POSTGRES_URL", "JWT_SECRET_KEY"]}
    environment.update(env, ENVIRONMENT="development", PYTHONDONTWRITEBYTECODE="1")
    env_file = output / "migration.private.env"
    with env_file.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in environment.items()))
    name = "sphere-vpn-catalog-migrate-" + uuid4().hex[:12]
    owner = uuid4().hex
    container = command(
        [
            "docker",
            "create",
            "--name",
            name,
            "--label",
            "io.sphere.catalog-migrate=" + owner,
            "--network",
            next(iter(networks)),
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory=384m",
            "--cpus=1",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=32m",
            "--mount",
            f"type=bind,source={secret},target=/run/secrets/vpn-catalog.json,readonly",
            "--mount",
            f"type=bind,source={worker},target=/run/catalog-worker.py,readonly",
            "--env-file",
            str(env_file),
            image,
            "python",
            "/run/catalog-worker.py",
        ]
    )
    try:
        result = subprocess.run(
            ["docker", "start", "-a", container], capture_output=True, timeout=90, check=False
        )
        metadata = live.inspect(container)
        require(
            metadata["State"]["ExitCode"] == 0
            and result.returncode == 0
            and len(result.stdout) <= 16384
            and len(result.stderr) <= 32768,
            "Catalog migration outcome unknown; inspect schema/role before retry",
        )
        reply = json.loads(result.stdout)
        require(
            reply.get("state") == "success"
            and reply.get("schemaHead") == CATALOG_HEAD
            and reply.get("actualLoginChecked") is True
            and reply.get("legacyRoleChanged") is False,
            "Catalog migration receipt not confirmed",
        )
        write(
            output / "migration.json",
            reply
            | {
                "toolingSource": tool_source,
                "workerSha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
            },
        )
        return reply
    finally:
        item = live.inspect(container)
        require(
            item["Id"] == container
            and item["Config"]["Labels"].get("io.sphere.catalog-migrate") == owner,
            "Migration cleanup owner changed",
        )
        command(["docker", "rm", "-f", container])


def install(
    artifact: Path,
    source: str,
    expected_current: str,
    secret: Path,
    backup: Path,
    restored: Path,
    *,
    apply: bool = False,
) -> dict:
    with execution_lock(ROOT / ".local-pilot/vpn-catalog-install.lock"):
        artifact = live.workspace_path(artifact, private=True)
        admitted = admit_local(artifact, source)
        receipt = bounded_json(artifact / "receipt.json", 32768)
        validate_transition(receipt)
        before = live.snapshot()
        current = live.inspect(live.BACKEND)
        runtime_env = dict(v.split("=", 1) for v in current["Config"]["Env"] if "=" in v)
        require(
            current["State"]["Health"]["Status"] == "healthy"
            and runtime_env.get("SPHERE_BUILD_SHA") == expected_current
            and receipt["parentImageId"] == current["Image"]
            and receipt["parentSource"] == expected_current
            and live.schema_heads(current) == [PREVIOUS_HEAD],
            "Installed API/schema baseline changed",
        )
        secret = live.workspace_path(secret, private=True)
        env = secrets_environment(secret, runtime_env)
        recovery = recovery_evidence(backup, restored, source)
        labels = current["Config"]["Labels"]
        files = labels["com.docker.compose.project.config_files"].split(",")
        require(
            0 < len(files) <= 64 and len(files) == len(set(files)) and all(files),
            "Compose file inventory invalid",
        )
        env_file = live.workspace_path(
            Path(labels["com.docker.compose.project.environment_file"]), private=True
        )
        prefix = ["docker", "compose", "--project-name", live.PROJECT, "--env-file", str(env_file)]
        old_cmd = list(prefix)
        for file in files:
            old_cmd += ["--file", str(live.workspace_path(Path(file)))]
        old = json.loads(command(old_cmd + ["config", "--format", "json"]))
        require(
            old["services"]["backend"]["image"] == before[live.BACKEND]["imageTag"]
            and all(
                runtime_env.get(k) == v
                for k, v in old["services"]["backend"].get("environment", {}).items()
            ),
            "Baseline Compose differs from installed API",
        )
        output = ROOT / ".local-pilot" / ("vpn-catalog-install-" + uuid4().hex[:12])
        output.mkdir()
        # Frozen Compose includes existing secrets, so restrict the new folder.
        identity = command(["whoami"])
        command(
            [
                "icacls",
                str(output),
                "/inheritance:r",
                "/grant:r",
                identity + ":(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ]
        )
        frozen = freeze_compose(prefix, old, output / "baseline.json", runner=command)
        override = output / "candidate.yml"
        override.write_text(
            "services:\n  backend:\n    image: "
            + admitted["imageTag"]
            + "\n    build: !reset null\n    environment:\n"
            + "".join(f"      {k}: {json.dumps(v)}\n" for k, v in env.items()),
            encoding="utf-8",
        )
        candidate_cmd = frozen + ["--file", str(override)]
        candidate = json.loads(command(candidate_cmd + ["config", "--format", "json"]))
        validate_delta(old, candidate, admitted["imageTag"], env)
        catalog_hash = live.ota_hash()
        findings = evaluate(collect(ROOT))
        plan = {
            "sourceRevision": source,
            "imageId": admitted["imageId"],
            "runtimeInstalled": False,
            "applyRequested": apply,
            "observedAtUtc": datetime.now(timezone.utc).isoformat(),
            "reportDirectory": str(output),
            "resourceFindings": findings,
            **recovery,
            "schemaTransition": {"from": PREVIOUS_HEAD, "to": CATALOG_HEAD},
            "physicalVpnChanged": False,
        }
        write(output / "plan.json", plan)
        if not apply:
            return plan
        require(not findings and not evaluate(collect(ROOT)), "Host resources not admitted")
        live.preserved(before, live.snapshot())
        require(live.inspect(live.BACKEND)["Id"] == current["Id"], "API changed before migration")
        write(
            output / "intent.json",
            {
                "sourceRevision": source,
                "previousBackend": before[live.BACKEND],
                "databaseDowngradeAllowed": False,
            },
        )
        prepare_database(admitted["imageId"], current, secret, env, output)
        require(live.schema_heads(current) == [CATALOG_HEAD], "Schema migration unconfirmed")
        require(
            not evaluate(collect(ROOT)),
            "Host resources not admitted before API replacement; migration retained",
        )
        live.preserved(before, live.snapshot())
        up = [
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "--timeout",
            "35",
            "--wait",
            "--wait-timeout",
            "90",
            "backend",
        ]
        try:
            command(candidate_cmd + up, timeout=150)
            live.ready(source)
            after = live.snapshot()
            live.preserved(before, after)
            installed = live.inspect(live.BACKEND)
            require(
                installed["Image"] == admitted["imageId"]
                and installed["State"]["Health"]["Status"] == "healthy"
                and live.schema_heads(installed) == [CATALOG_HEAD]
                and live.ota_hash() == catalog_hash,
                "API/schema/OTA result differs",
            )
            actual_env = dict(v.split("=", 1) for v in installed["Config"]["Env"] if "=" in v)
            require(
                all(
                    actual_env.get(k) == v
                    for k, v in candidate["services"]["backend"]["environment"].items()
                ),
                "Installed API environment differs",
            )
            result = plan | {
                "runtimeInstalled": True,
                "schemaMigrationPerformed": True,
                "catalogCredentialsConfigured": True,
                "otherContainersPreserved": True,
                "previousImagePreserved": True,
            }
            write(output / "installed.json", result)
            return result
        except Exception:
            matches = command(
                [
                    "docker",
                    "ps",
                    "--all",
                    "--filter",
                    f"name=^/{live.BACKEND}$",
                    "--format",
                    "{{.ID}}",
                ]
            )
            item = live.inspect(live.BACKEND) if matches else None
            if item is None or (
                item["Image"] in {admitted["imageId"], current["Image"]}
                and item["Config"]["Labels"].get("com.docker.compose.project") == live.PROJECT
            ):
                command(frozen + up, timeout=150)
                live.ready(expected_current)
                require(
                    live.schema_heads(current) == [CATALOG_HEAD],
                    "Unexpected schema after API rollback",
                )
                write(
                    output / "rollback.json", {"apiRestored": True, "additiveSchemaRetained": True}
                )
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["artifact", "secret", "backup", "restored"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-current", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                install(
                    args.artifact,
                    args.source,
                    args.expected_current,
                    args.secret,
                    args.backup,
                    args.restored,
                    apply=args.apply,
                )
            )
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "state": "not-admitted-or-unknown",
                    "detail": "Inspect private intent/migration/install receipts; never blindly retry",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
