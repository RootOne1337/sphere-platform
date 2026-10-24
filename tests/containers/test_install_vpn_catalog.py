"""The additive catalog installer may only add its two staged credentials."""

import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from scripts.pilot import install_reviewed_backend as live
from scripts.pilot import install_vpn_catalog as install
from tests.containers.test_install_reviewed_backend import TAG, candidate, configuration


def primary():
    return {
        "POSTGRES_URL": "postgresql+asyncpg://primary:old@postgres/sphere",
        "JWT_SECRET_KEY": "independent",
    }


def secret():
    return {
        "VPN_PROFILE_DATABASE_ROLE": "sphere_vpn_catalog",
        "VPN_PROFILE_DATABASE_PASSWORD": "a" * 64,
        "VPN_PROFILE_POSTGRES_URL": "postgresql+asyncpg://sphere_vpn_catalog:"
        + "a" * 64
        + "@postgres/sphere",
        "VPN_PROFILE_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
        "activated": False,
    }


def test_only_two_exact_secret_values_can_be_added_to_the_existing_image_delta():
    old = configuration()
    new = candidate(old)
    env = {"VPN_PROFILE_ENCRYPTION_KEYS": "private-key", "VPN_PROFILE_POSTGRES_URL": "private-dsn"}
    new["services"]["backend"]["environment"].update(env)
    install.validate_delta(old, new, TAG, env)
    for mutate in [
        lambda x: x["services"]["backend"]["environment"].update(JWT_SECRET_KEY="changed"),
        lambda x: x["services"]["backend"]["environment"].update(
            VPN_PROFILE_ENCRYPTION_KEYS="wrong"
        ),
        lambda x: x["services"]["backend"].update(privileged=True),
        lambda x: x["services"].pop("postgres"),
    ]:
        bad = copy.deepcopy(new)
        mutate(bad)
        with pytest.raises(ValueError):
            install.validate_delta(old, bad, TAG, env)
    with pytest.raises(ValueError):
        install.validate_delta(old, new, TAG, env | {"POSTGRES_URL": "other"})


def test_localized_windows_acl_output_is_not_decoded_and_exact_current_sid_is_used():
    sid = b"S-1-5-21-123-456-789-1001"
    owner = subprocess.CompletedProcess(
        [], 0, stdout=b'"' + bytes([0xE0, 0xA1]) + b'","' + sid + b'"\r\n'
    )
    applied = subprocess.CompletedProcess([], 0, stdout=bytes([0xE0, 0xA1, 0x80]))
    with patch.object(install.subprocess, "run", side_effect=[owner, applied]) as run:
        install.restrict_private_directory(Path("private"))
        assert run.call_args.args[0][-2:] == [
            "*" + sid.decode() + ":(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
        ]
    with (
        patch.object(
            install.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout=b"")
        ),
        pytest.raises(ValueError),
    ):
        install.restrict_private_directory(Path("private"))


def test_secret_file_does_not_allow_existing_credential_replacement_or_another_database():
    original = secret()
    with patch.object(live, "workspace_path", return_value=Path("private")):
        with patch.object(install, "bounded_json", return_value=original):
            assert install.secrets_environment(Path("private"), primary()) == {
                k: original[k] for k in install.ENV_KEYS
            }
        for mutate in [
            lambda x: x.update(activated=True),
            lambda x: x.update(VPN_PROFILE_DATABASE_ROLE="primary"),
            lambda x: x.update(VPN_PROFILE_DATABASE_PASSWORD="wrong"),
            lambda x: x.update(
                VPN_PROFILE_POSTGRES_URL=x["VPN_PROFILE_POSTGRES_URL"].replace(
                    "@postgres/", "@other/"
                )
            ),
            lambda x: x.update(
                VPN_PROFILE_POSTGRES_URL=x["VPN_PROFILE_POSTGRES_URL"] + "?user=primary"
            ),
            lambda x: x.update(VPN_PROFILE_ENCRYPTION_KEYS=x["VPN_PROFILE_ENCRYPTION_KEYS"] + "\n"),
        ]:
            data = copy.deepcopy(original)
            mutate(data)
            with (
                patch.object(install, "bounded_json", return_value=data),
                pytest.raises((ValueError, TypeError)),
            ):
                install.secrets_environment(Path("private"), primary())
        with (
            patch.object(install, "bounded_json", return_value=original),
            pytest.raises(ValueError),
        ):
            install.secrets_environment(
                Path("private"), primary() | {"VPN_PROFILE_POSTGRES_URL": "already-configured"}
            )


def test_restore_proof_requires_exact_backup_bytes_and_successful_same_source_migration():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        backup = root / "database.dump"
        backup.write_bytes(b"bounded fixture database")
        restored = root / "restored.json"
        digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        base = {
            "databaseHeads": [install.PREVIOUS_HEAD],
            "databaseBackup": {"sha256": digest, "fullRestoreTested": False},
        }
        result = {
            "state": "success",
            "archiveRestored": True,
            "minimalRoleHttpLifecycle": True,
            "legacyRowCountsPreserved": True,
            "isolatedServicesRemoved": True,
            "liveMigrationPerformed": False,
            "restoredSchemaHead": install.CATALOG_HEAD,
            "backupSha256": digest,
            "sourceRevision": "a" * 40,
            "migrationWorkerSha256": hashlib.sha256(
                (install.ROOT / "scripts/pilot/vpn_catalog_db_worker.py").read_bytes()
            ).hexdigest(),
        }
        (root / "receipt.json").write_text(json.dumps(base))
        restored.write_text(json.dumps(result))
        with (
            patch.object(live, "workspace_path", side_effect=lambda path, **kw: path),
            patch.object(install, "command", return_value=""),
        ):
            assert install.recovery_evidence(backup, restored, "b" * 40)["backupSha256"] == digest
            for key, value in [
                ("backupSha256", "0" * 64),
                ("minimalRoleHttpLifecycle", False),
                ("isolatedServicesRemoved", False),
                ("liveMigrationPerformed", True),
                ("state", "failure"),
            ]:
                restored.write_text(json.dumps(result | {key: value}))
                with pytest.raises(ValueError):
                    install.recovery_evidence(backup, restored, "b" * 40)
            restored.write_text(json.dumps(result))
            with (
                patch.object(install, "command", return_value="changed"),
                pytest.raises(ValueError),
            ):
                install.recovery_evidence(backup, restored, "b" * 40)
            backup.write_bytes(b"modified")
            with pytest.raises(ValueError, match="Backup bytes changed"):
                install.recovery_evidence(backup, restored, "b" * 40)


def test_resume_requires_positive_migration_receipt_and_original_api_container():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = "a" * 40
        current = {"Id": "original-container", "Image": "original-image"}
        recovery = {"backupSha256": "b" * 64, "restoreReceiptSha256": "c" * 64}
        plan = {"sourceRevision": source, "applyRequested": True, **recovery}
        intent = {
            "sourceRevision": source,
            "previousBackend": {"id": current["Id"], "imageId": current["Image"]},
        }
        migration = {
            "state": "success",
            "schemaHead": install.CATALOG_HEAD,
            "actualLoginChecked": True,
            "minimalGrantsApplied": True,
            "legacyRoleChanged": False,
            "workerSha256": hashlib.sha256(
                (install.ROOT / "scripts/pilot/vpn_catalog_db_worker.py").read_bytes()
            ).hexdigest(),
        }
        for name, data in [("plan", plan), ("intent", intent), ("migration", migration)]:
            (folder / (name + ".json")).write_text(json.dumps(data))
        with patch.object(live, "workspace_path", side_effect=lambda p, **kw: p):
            assert "resumedMigrationReceiptSha256" in install.confirmed_migration(
                folder, source, current, recovery
            )
            for key, value in [
                ("state", "unknown"),
                ("schemaHead", install.PREVIOUS_HEAD),
                ("actualLoginChecked", False),
                ("workerSha256", "0" * 64),
            ]:
                (folder / "migration.json").write_text(json.dumps(migration | {key: value}))
                with pytest.raises(ValueError):
                    install.confirmed_migration(folder, source, current, recovery)
            (folder / "migration.json").write_text(json.dumps(migration))
            with pytest.raises(ValueError):
                install.confirmed_migration(
                    folder, source, current | {"Id": "other-container"}, recovery
                )
            (folder / "installed.json").write_text("{}")
            with pytest.raises(ValueError):
                install.confirmed_migration(folder, source, current, recovery)
