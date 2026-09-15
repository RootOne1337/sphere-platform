"""Shipped bootstrap shells and CLI with real disposable PostgreSQL and ASGI login."""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update

from backend.models import Organization, User
from backend.services.cache_service import CacheService

REPOSITORY = Path(__file__).resolve().parents[2]
FIRST_PASSWORD = "isolated-original-password"
NEXT_PASSWORD = "isolated-new-candidate-password"


@pytest_asyncio.fixture
async def admin_world(world, monkeypatch):
    original_limit = CacheService.check_rate_limit

    async def isolated_limit(self, identifier, **kwargs):
        return await original_limit(self, world.suffix + ":" + identifier, **kwargs)

    monkeypatch.setattr(CacheService, "check_rate_limit", isolated_limit)
    world.admin_email = "bootstrap-restart-" + world.suffix + "@example.org"
    return world


def environment(world, password=FIRST_PASSWORD, slug=None):
    env = os.environ.copy()
    env.update(POSTGRES_URL=world.engine.url.render_as_string(hide_password=False),
        ADMIN_EMAIL=world.admin_email, ADMIN_PASSWORD=password,
        SPHERE_BOOTSTRAP_ORG_SLUG=slug or world.org_a.slug, PYTHONUTF8="1")
    return env


async def cli(world, *, password=FIRST_PASSWORD, create_only=False, slug=None):
    args = [sys.executable, "scripts/create_admin.py"]
    if create_only:
        args.append("--create-only")
    return await asyncio.to_thread(subprocess.run, args, cwd=REPOSITORY,
        env=environment(world, password, slug), capture_output=True, text=True, encoding="utf-8", timeout=30)


async def user_snapshot(world):
    async with world.sessions() as db:
        user = await db.scalar(select(User).where(User.email == world.admin_email))
        return (user.id, user.org_id, user.password_hash, user.role, user.is_active, user.mfa_enabled)


async def login(world, password):
    return await world.client.post("/api/v1/auth/login", json={"email": world.admin_email, "password": password})


@pytest.fixture(params=["powershell", "bash"])
def bootstrap_stage(request, tmp_path):
    shell = request.param
    executable = shutil.which("pwsh" if shell == "powershell" else "bash")
    if shell == "bash" and os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} is required for bootstrap restart acceptance")
        pytest.skip(f"{shell} unavailable")
    root = tmp_path / "installation with spaces"
    root.mkdir()
    (root / ".env.local").write_text("# synthetic test configuration\n", encoding="utf-8")
    boundary = root / "docker_boundary.py"
    boundary.write_text('''import os, subprocess, sys
args = sys.argv[1:]
inner = args[args.index("backend") + 1:]
if inner[:2] == ["python", "scripts/create_admin.py"]:
    result = subprocess.run([sys.executable, *inner[1:]], cwd=os.environ["ADMIN_TEST_REPO"])
    sys.exit(result.returncode)
assert inner == ["python", "-m", "scripts.seed_enrollment_key"], inner
# Enrollment is a separate, already tested SQL contract. Isolate its outcome.
if os.environ["ADMIN_TEST_ENROLLMENT_FAIL"] == "1":
    print("Synthetic enrollment failure", file=sys.stderr)
    sys.exit(17)
print("Synthetic enrollment completed")
''', encoding="utf-8")
    script = root / ("bootstrap.ps1" if shell == "powershell" else "bootstrap.sh")
    if shell == "powershell":
        script.write_text('''$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$ProjectDir = $env:ADMIN_TEST_ROOT
$LogFile = Join-Path $ProjectDir 'deploy.log'
$ComposeFiles = @('-f', 'docker-compose.yml', '-f', 'docker-compose.full.yml')
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:ADMIN_TEST_SOURCE, [ref]$null, [ref]$null)
$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -in @('Write-Log', 'Invoke-Compose', 'Step-SeedData')}, $true) | ForEach-Object { Invoke-Expression $_.Extent.Text }
function global:docker { & $env:ADMIN_TEST_PYTHON $env:ADMIN_TEST_BOUNDARY @args }
try { Step-SeedData } catch { Write-Host $_.Exception.Message; exit 17 }
''', encoding="utf-8")
    else:
        source = (REPOSITORY / "scripts/full-deploy.sh").read_text(encoding="utf-8")
        preamble, end = source.rsplit('\nmain "$@"', 1)
        assert not end.strip()
        (root / "library.sh").write_text(preamble + "\n", encoding="utf-8")
        script.write_text('''source "$ADMIN_TEST_ROOT/library.sh" --headless
PROJECT_DIR="$ADMIN_TEST_ROOT"
LOG_FILE="$ADMIN_TEST_ROOT/deploy.log"
docker() { "$ADMIN_TEST_PYTHON" "$ADMIN_TEST_BOUNDARY" "$@"; }
seed_data
''', encoding="utf-8")

    async def run(world, *, enrollment_fail=False, saved=None):
        if saved is not None:
            (root / ".admin-credentials").write_bytes(saved)
        env = environment(world, NEXT_PASSWORD)
        env.update(ADMIN_TEST_ROOT=root.as_posix(), ADMIN_TEST_REPO=str(REPOSITORY),
            ADMIN_TEST_PYTHON=Path(sys.executable).as_posix(), ADMIN_TEST_BOUNDARY=boundary.as_posix(),
            ADMIN_TEST_SOURCE=str(REPOSITORY / "scripts/full-deploy.ps1"),
            ADMIN_TEST_ENROLLMENT_FAIL=str(int(enrollment_fail)),
            SPHERE_ADMIN_EMAIL=world.admin_email, SPHERE_ADMIN_PASSWORD=NEXT_PASSWORD)
        args = [executable, "-NoProfile", "-NonInteractive", "-File", str(script)] if shell == "powershell" else [executable, script.as_posix()]
        result = await asyncio.to_thread(subprocess.run, args, cwd=root, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=40)
        return result, root, shell
    return run


async def test_full_deploy_repeat_preserves_the_working_operator_login(admin_world, bootstrap_stage):
    w = admin_world
    assert (await cli(w)).returncode == 0
    before = await user_snapshot(w)
    result, root, _ = await bootstrap_stage(w, saved=b"retained credential record\n")
    assert result.returncode == 0, result.stderr
    assert (await login(w, FIRST_PASSWORD)).status_code == 200, "Working operator password was replaced"
    assert (await login(w, NEXT_PASSWORD)).status_code == 401
    assert await user_snapshot(w) == before
    assert NEXT_PASSWORD not in result.stdout + result.stderr
    assert (root / ".admin-credentials").read_bytes() == b"retained credential record\n"


async def test_fresh_full_deploy_reports_a_password_that_can_actually_log_in(admin_world, bootstrap_stage):
    result, _, _ = await bootstrap_stage(admin_world)
    assert result.returncode == 0, result.stderr
    assert (await login(admin_world, NEXT_PASSWORD)).status_code == 200
    assert NEXT_PASSWORD in result.stdout


async def test_created_login_remains_recoverable_when_enrollment_fails(admin_world, bootstrap_stage):
    result, root, shell = await bootstrap_stage(admin_world, enrollment_fail=True)
    assert result.returncode != 0
    assert "Synthetic enrollment failure" in result.stdout + result.stderr
    assert (await login(admin_world, NEXT_PASSWORD)).status_code == 200
    assert NEXT_PASSWORD in result.stdout, "Committed admin credentials were never presented"
    if shell == "bash":
        assert NEXT_PASSWORD in (root / ".admin-credentials").read_text(encoding="utf-8")


@pytest.mark.parametrize("change", [{"is_active": False}, {"role": "viewer"}, {"mfa_enabled": True}])
async def test_create_only_does_not_reset_existing_admin_state(admin_world, change):
    w = admin_world
    assert (await cli(w)).returncode == 0
    async with w.sessions() as db:
        await db.execute(update(User).where(User.email == w.admin_email).values(**change))
        await db.commit()
    before = await user_snapshot(w)
    result = await cli(w, password=NEXT_PASSWORD, create_only=True)
    assert await user_snapshot(w) == before
    if "mfa_enabled" in change:
        assert result.returncode == 0
        assert result.stdout.splitlines()[-1] == "SPHERE_ADMIN_BOOTSTRAP=existing"
    else:
        assert result.returncode != 0
        assert "SPHERE_ADMIN_BOOTSTRAP=" not in result.stdout
    assert NEXT_PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize("new_organization", [False, True])
async def test_concurrent_create_only_commands_converge_without_resetting_the_winner(admin_world, new_organization):
    w = admin_world
    slug = "bootstrap-new-" + w.suffix if new_organization else w.org_a.slug
    results = await asyncio.wait_for(asyncio.gather(
        *(cli(w, password=f"isolated-concurrent-{i}", create_only=True, slug=slug) for i in range(3))), 40)
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    statuses = [r.stdout.splitlines()[-1] for r in results]
    assert statuses.count("SPHERE_ADMIN_BOOTSTRAP=created") == 1, statuses
    assert statuses.count("SPHERE_ADMIN_BOOTSTRAP=existing") == 2, statuses
    winner = statuses.index("SPHERE_ADMIN_BOOTSTRAP=created")
    assert (await login(w, f"isolated-concurrent-{winner}")).status_code == 200
    before = await user_snapshot(w)
    assert (await cli(w, password=NEXT_PASSWORD, create_only=True, slug=slug)).returncode == 0
    assert await user_snapshot(w) == before


async def test_create_only_rejects_a_different_organization_without_creating_it(admin_world):
    w = admin_world
    assert (await cli(w)).returncode == 0
    before = await user_snapshot(w)
    slug = "rejected-bootstrap-" + w.suffix
    result = await cli(w, password=NEXT_PASSWORD, create_only=True, slug=slug)
    assert result.returncode != 0
    assert "another organization" in result.stderr
    assert await user_snapshot(w) == before
    async with w.sessions() as db:
        assert await db.scalar(select(Organization.id).where(Organization.slug == slug)) is None


async def test_direct_admin_cli_still_supports_an_intentional_password_update(admin_world):
    w = admin_world
    assert (await cli(w)).returncode == 0
    assert (await cli(w, password=NEXT_PASSWORD)).returncode == 0
    assert (await login(w, NEXT_PASSWORD)).status_code == 200
    assert (await login(w, FIRST_PASSWORD)).status_code == 401


async def test_commit_failure_rolls_back_identity_without_reporting_credentials_ready(admin_world):
    w = admin_world
    function = "audit_admin_commit_" + w.suffix
    trigger = "audit_admin_commit_trigger_" + w.suffix
    slug = "uncommitted-admin-" + w.suffix
    # Names/email contain only fixture-owned ASCII identifiers. The deferred
    # trigger fails at COMMIT, after the CLI's INSERT has succeeded.
    async with w.engine.begin() as db:
        await db.execute(text(f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'synthetic admin commit rejected'; END; $$"))
        await db.execute(text(f"CREATE CONSTRAINT TRIGGER {trigger} AFTER INSERT ON users "
            f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.email = '{w.admin_email}') "
            f"EXECUTE FUNCTION {function}()"))
    try:
        result = await cli(w, create_only=True, slug=slug)
        assert result.returncode != 0
        assert "synthetic admin commit rejected" in result.stderr
        assert "SPHERE_ADMIN_BOOTSTRAP=" not in result.stdout
        assert "Done." not in result.stdout
        assert "created" not in result.stdout.lower()
        async with w.sessions() as db:
            assert await db.scalar(select(User.id).where(User.email == w.admin_email)) is None
            assert await db.scalar(select(Organization.id).where(Organization.slug == slug)) is None
    finally:
        async with w.engine.begin() as db:
            await db.execute(text(f"DROP TRIGGER {trigger} ON users"))
            await db.execute(text(f"DROP FUNCTION {function}()"))
