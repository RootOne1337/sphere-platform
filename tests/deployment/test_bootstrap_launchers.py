"""Run the actual bootstrap functions; Docker is a separate isolated process."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from backend.schemas.auth import LoginRequest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["powershell", "bash"])
def bootstrap(request, tmp_path):
    shell = request.param
    executable = shutil.which("pwsh" if shell == "powershell" else "bash")
    if shell == "bash" and os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} is required to verify the shipped bootstrap")
        pytest.skip(f"{shell} unavailable")
    fake = tmp_path / "docker_boundary.py"
    fake.write_text('''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
stage = 'enrollment' if 'scripts.seed_enrollment_key' in args else 'admin'
entry = {'args': args, 'stage': stage,
    'email': os.environ.get('ADMIN_EMAIL'), 'password': os.environ.get('ADMIN_PASSWORD')}
with open(os.environ['PILOT_CALLS'], 'a', encoding='utf-8') as f:
    f.write(json.dumps(entry) + '\\n')
if os.environ['PILOT_FAILURE'] == stage:
    sys.exit(17)
print('Synthetic bootstrap success: ' + stage)
''', encoding="utf-8")
    calls = tmp_path / "calls.jsonl"
    script = tmp_path / ("run.ps1" if shell == "powershell" else "run.sh")
    if shell == "powershell":
        script.write_text('''$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$ProjectDir = $env:PILOT_ROOT
$LogFile = Join-Path $ProjectDir 'deploy.log'
$ComposeFiles = @('-f', 'docker-compose.yml', '-f', 'docker-compose.full.yml')
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:PILOT_SOURCE, [ref]$null, [ref]$null)
$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -in @('Write-Log', 'Invoke-Compose', 'Step-SeedData')}, $true) | ForEach-Object { Invoke-Expression $_.Extent.Text }
function global:docker { & $env:PILOT_PYTHON $env:PILOT_FAKE @args }
try { Step-SeedData } catch { Write-Host $_.Exception.Message; exit 17 }
if ($env:ADMIN_EMAIL -ne 'previous-email' -or $env:ADMIN_PASSWORD -ne 'previous-password') { exit 19 }
''', encoding="utf-8")
    else:
        source = (REPOSITORY / "scripts/full-deploy.sh").read_text(encoding="utf-8")
        prefix, entrypoint = source.rsplit('\nmain "$@"', 1)
        assert not entrypoint.strip()
        library = tmp_path / "full-deploy-library.sh"
        library.write_text(prefix + "\n", encoding="utf-8")
        script.write_text('''source "$PILOT_ROOT/full-deploy-library.sh" --headless
PROJECT_DIR="$PILOT_ROOT"
LOG_FILE="$PILOT_ROOT/deploy.log"
GREEN='' BOLD='' NC=''
log() { printf '%s\\n' "$2"; }
docker() { "$PILOT_PYTHON" "$PILOT_FAKE" "$@"; }
seed_data
test "$ADMIN_EMAIL" = previous-email
test "$ADMIN_PASSWORD" = previous-password
''', encoding="utf-8")

    def run(failure="none", default_email=False):
        env = os.environ.copy()
        env.update(PILOT_ROOT=tmp_path.as_posix(), PILOT_PYTHON=Path(sys.executable).as_posix(),
            PILOT_FAKE=fake.as_posix(), PILOT_CALLS=calls.as_posix(), PILOT_FAILURE=failure,
            PILOT_SOURCE=str(REPOSITORY / "scripts/full-deploy.ps1"),
            SPHERE_ADMIN_EMAIL="pilot@example.invalid", SPHERE_ADMIN_PASSWORD="pilot-test-password",
            SPHERE_BOOTSTRAP_ORG_SLUG="pilot-operator-org",
            ADMIN_EMAIL="previous-email", ADMIN_PASSWORD="previous-password")
        if default_email:
            env.pop("SPHERE_ADMIN_EMAIL", None)
        args = [executable, "-NoProfile", "-NonInteractive", "-File", str(script)] if shell == "powershell" else [executable, script.as_posix()]
        result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
        entries = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []
        return result, entries
    return run


def test_bootstrap_forwards_actual_credentials_without_embedding_them_in_command(bootstrap):
    result, calls = bootstrap()
    assert result.returncode == 0, result.stdout + result.stderr
    admin, enrollment = calls
    assert admin["email"] == "pilot@example.invalid"
    assert admin["password"] == "pilot-test-password"
    assert admin["args"][-2:] == ["python", "scripts/create_admin.py"]
    assert "ADMIN_EMAIL" in admin["args"] and "ADMIN_PASSWORD" in admin["args"]
    assert "pilot-test-password" not in " ".join(admin["args"])
    assert enrollment["stage"] == "enrollment"
    assert "SPHERE_BOOTSTRAP_ORG_SLUG" in admin["args"]
    assert "SPHERE_BOOTSTRAP_ORG_SLUG" in enrollment["args"]


def test_default_bootstrap_email_can_pass_the_real_login_schema(bootstrap):
    result, calls = bootstrap(default_email=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert LoginRequest(email=calls[0]["email"], password=calls[0]["password"])


@pytest.mark.parametrize("failure", ["admin", "enrollment"])
def test_failed_bootstrap_stops_before_claiming_working_credentials(bootstrap, failure):
    result, calls = bootstrap(failure)
    assert result.returncode != 0, result.stdout + result.stderr
    assert calls[-1]["stage"] == failure
    assert "pilot-test-password" not in result.stdout
    assert "УЧЁТНЫЕ ДАННЫЕ АДМИНИСТРАТОРА" not in result.stdout
