"""One additive VPN catalog boundary; not a general schema-change exception.

These checks admit packaging only. The schema-free installer must continue to
refuse this image until a separate backup/role/key-aware migration is performed.
"""

from __future__ import annotations

import hashlib
import subprocess

from scripts.pilot import install_reviewed_backend as installer
from scripts.pilot.local_backend_artifact import ROOT, command
from scripts.pilot.reviewed_image_archive import require

PREVIOUS_HEAD = "20261006_script_catalog_metadata"
CATALOG_HEAD = "20261021_vpn_profiles"
MIGRATION = "alembic/versions/20261021_vpn_profiles.py"
# The migration was exercised by the full PostgreSQL regressions. Freeze its
# exact canonical bytes here; changing it needs a new release boundary/review.
MIGRATION_SHA256 = "40f8696745da07733011a0e732ef229506b9d3148a18272a1abe5a2851d656d7"
CATALOG_PATHS = {
    MIGRATION,
    "backend/api/v1/vpn/profile_input.py",
    "backend/api/v1/vpn/profile_router.py",
    "backend/api/v1/vpn/router.py",
    "backend/api/v1/vpn/runtime_router.py",
    "backend/api/ws/android/router.py",
    "backend/core/config.py",
    "backend/models/__init__.py",
    "backend/models/vpn_profile.py",
    "backend/schemas/device_status.py",
    "backend/schemas/vpn/catalog.py",
    "backend/schemas/vpn/profile.py",
    "backend/schemas/vpn/runtime.py",
    "backend/services/device_status_cache.py",
    "backend/services/vpn/profile_catalog.py",
    "backend/services/vpn/catalog_database.py",
    "backend/services/vpn/profile_delivery.py",
    "backend/services/vpn/profile_preflight.py",
    "backend/services/vpn/profile_secrets.py",
}


def source_boundary(current: str, source: str, hashes: dict) -> list[str]:
    changes = command(
        ["git", "diff", "--name-only", current, source, "--", *installer.PACKAGED_PATHS]
    ).splitlines()
    require(
        set(changes) <= installer.APPROVED_PATHS | CATALOG_PATHS,
        "Unreviewed VPN catalog packaged change",
    )
    # Keep the ordinary schema-free check unchanged. It separately verifies the
    # dependency/contract hashes; filter only the explicitly reviewed additions.
    for name, key in [
        ("backend/requirements.txt", "requirementsSha256"),
        ("backend/schemas/action_contract.v1.json", "actionContractSha256"),
    ]:
        result = subprocess.run(
            ["git", "show", f"{source}:{name}"],
            cwd=ROOT,
            capture_output=True,
            timeout=15,
            check=False,
        )
        require(
            result.returncode == 0
            and 0 < len(result.stdout) <= 256 * 1024
            and hashlib.sha256(result.stdout).hexdigest() == hashes[key],
            "Catalog dependency/action hash mismatch",
        )
        require(
            not command(["git", "diff", current, source, "--", name]),
            "Catalog update may not change dependencies or action contract",
        )
    schema_changes = command(
        ["git", "diff", "--name-status", current, source, "--", "alembic"]
    ).splitlines()
    require(
        schema_changes == ["A\t" + MIGRATION], "Exactly one additive catalog migration required"
    )
    result = subprocess.run(
        ["git", "show", f"{source}:{MIGRATION}"],
        cwd=ROOT,
        capture_output=True,
        timeout=15,
        check=False,
    )
    require(
        result.returncode == 0 and hashlib.sha256(result.stdout).hexdigest() == MIGRATION_SHA256,
        "Reviewed catalog migration changed",
    )
    return changes


def transition() -> dict:
    return {
        "from": [PREVIOUS_HEAD],
        "to": [CATALOG_HEAD],
        "migration": MIGRATION,
        "migrationSha256": MIGRATION_SHA256,
        "liveMigrationPerformed": False,
    }


def validate_transition(receipt: dict) -> None:
    require(
        receipt.get("schemaTransition") == transition(), "Catalog schema transition binding changed"
    )
    require(receipt.get("migrationHeads") == [CATALOG_HEAD], "Catalog image head changed")
    source_boundary(receipt["parentSource"], receipt["sourceRevision"], receipt)
