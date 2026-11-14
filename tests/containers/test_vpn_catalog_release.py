"""Catalog packaging cannot silently turn the schema-free installer into a migrator."""

import copy
import hashlib
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.pilot import install_reviewed_backend as installer
from scripts.pilot import vpn_catalog_release as release
from scripts.pilot.package_local_backend import build_spec, validate_resume_context

OLD, NEW = "a" * 40, "b" * 40
CONTENT = b"canonical fixture"
HASHES = {
    "requirementsSha256": hashlib.sha256(CONTENT).hexdigest(),
    "actionContractSha256": hashlib.sha256(CONTENT).hexdigest(),
}


def run_boundary(
    *,
    changes=None,
    migration_status=None,
    dependency_changed=False,
    migration_changed=False,
    runtime_changed=False,
):
    def command(args):
        if "--name-only" in args:
            return "\n".join(changes or sorted(release.CATALOG_PATHS))
        if "--name-status" in args:
            return migration_status if migration_status is not None else "A\t" + release.MIGRATION
        if args[-1] == "backend/Dockerfile":
            return "changed" if runtime_changed else ""
        return "changed" if dependency_changed else ""

    def git_blob(args, **kwargs):
        data = CONTENT
        if args[-1].endswith(release.MIGRATION) and migration_changed:
            data += b"changed"
        return subprocess.CompletedProcess(args, 0, stdout=data)

    with (
        patch.object(release, "command", side_effect=command),
        patch.object(release.subprocess, "run", side_effect=git_blob),
        patch.object(release, "MIGRATION_SHA256", hashlib.sha256(CONTENT).hexdigest()),
    ):
        return release.source_boundary(OLD, NEW, HASHES)


def test_one_reviewed_additive_migration_is_packaged_without_dependency_install():
    assert set(run_boundary()) == release.CATALOG_PATHS
    spec = build_spec("parent:fixed", NEW, "local-run", catalog=True)
    assert spec.count("\nCOPY ") == 1
    assert "COPY --chown=sphere:sphere source/ /app/" in spec
    assert "RUN " not in spec
    assert "source/" not in build_spec("parent:fixed", NEW, "local-run")


@pytest.mark.parametrize(
    "changes",
    [
        ["backend/requirements.txt"],
        ["backend/unreviewed.py"],
        ["alembic/env.py"],
        ["agent-config/environments/development.json"],
    ],
)
def test_unreviewed_sources_remain_refused(changes):
    with pytest.raises(ValueError, match="Unreviewed"):
        run_boundary(changes=changes)


@pytest.mark.parametrize(
    "status",
    [
        "",
        "M\t" + release.MIGRATION,
        "D\t" + release.MIGRATION,
        "A\t" + release.MIGRATION + "\nM\talembic/versions/old.py",
    ],
)
def test_modified_historical_or_additional_migrations_cannot_use_catalog_boundary(status):
    with pytest.raises(ValueError, match="Exactly one additive"):
        run_boundary(migration_status=status)


def test_migration_bytes_and_dependencies_must_match_reviewed_source():
    with pytest.raises(ValueError, match="parent runtime recipe"):
        run_boundary(runtime_changed=True)
    with pytest.raises(ValueError, match="may not change dependencies"):
        run_boundary(dependency_changed=True)
    with pytest.raises(ValueError, match="migration changed"):
        run_boundary(migration_changed=True)


def test_ordinary_installer_still_rejects_catalog_migration_even_after_it_is_packaged():
    with patch.object(installer, "command", return_value=release.MIGRATION):
        with pytest.raises(ValueError, match="Unreviewed packaged"):
            installer.source_boundary(OLD, NEW, HASHES)


def test_transition_cannot_claim_live_migration_or_another_schema_head():
    original = {
        "schemaTransition": release.transition(),
        "migrationHeads": [release.CATALOG_HEAD],
        "parentSource": OLD,
        "sourceRevision": NEW,
        **HASHES,
    }
    with patch.object(release, "source_boundary") as boundary:
        release.validate_transition(original)
        boundary.assert_called_once_with(OLD, NEW, original)
    for mutate in [
        lambda x: x["schemaTransition"].update(liveMigrationPerformed=True),
        lambda x: x["schemaTransition"].update({"from": ["another"]}),
        lambda x: x["schemaTransition"].update(migrationSha256="0" * 64),
        lambda x: x.update(migrationHeads=[release.PREVIOUS_HEAD]),
        lambda x: x.pop("schemaTransition"),
    ]:
        row = copy.deepcopy(original)
        mutate(row)
        with patch.object(release, "source_boundary") as boundary, pytest.raises(ValueError):
            release.validate_transition(row)
        boundary.assert_not_called()


def test_interrupted_context_requires_original_files_recipe_and_no_partial_next_probe():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp).resolve()
        private = root / ".local-pilot"
        folder = private / "candidate"
        source = folder / "context/source/backend"
        source.mkdir(parents=True)
        (folder / "runtime").mkdir()
        for log in ["build.private.log", "runtime.private.log"]:
            (folder / log).write_bytes(b"success")
        recipe = "FROM pinned\nCOPY source/ /app/\n"
        (folder / "context/Dockerfile.local").write_bytes(recipe.replace("\n", "\r\n").encode())
        page = source / "main.py"
        page.write_bytes(CONTENT)
        expected = {"backend/main.py": hashlib.sha256(CONTENT).hexdigest()}
        with patch.object(installer, "ROOT", root), patch.object(installer, "PRIVATE", private):
            validate_resume_context(folder, expected, recipe)
            for extra in ["receipt.json", "metrics.private.log", "unexpected"]:
                path = folder / extra
                path.touch()
                with pytest.raises(ValueError, match="no later files"):
                    validate_resume_context(folder, expected, recipe)
                path.unlink()
            page.write_bytes(CONTENT + b"changed")
            with pytest.raises(ValueError, match="context changed"):
                validate_resume_context(folder, expected, recipe)
            page.write_bytes(CONTENT)
            with pytest.raises(ValueError, match="recipe changed"):
                validate_resume_context(folder, expected, recipe + "RUN something\n")
