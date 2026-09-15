"""Exercise both shipped full-deploy main flows against a native Docker boundary.

Only synthetic temporary files are used. The boundary models a fresh database and
refuses API startup until migration and both bootstrap commands have succeeded.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["powershell", "bash"])
def full_deploy(request, tmp_path):
    shell = request.param
    executable = shutil.which("pwsh" if shell == "powershell" else "bash")
    if shell == "bash" and os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} is required")
        pytest.skip(f"{shell} unavailable")
    root = tmp_path / "checkout with spaces"
    (root / "scripts").mkdir(parents=True)
    (root / ".env.local").write_text("ENVIRONMENT=development\n", encoding="utf-8")
    (root / "VERSION").write_text("isolated-test\n", encoding="utf-8")
    calls = tmp_path / "calls.jsonl"
    state = tmp_path / "state.json"
    boundary = tmp_path / "docker_boundary.py"
    boundary.write_text('''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
statefile = Path(os.environ['SEQUENCE_STATE'])
state = json.loads(statefile.read_text()) if statefile.exists() else {}
stage = 'other'
if args[0] == 'host-python':
    if args[1:] == ['--version']: print(sys.version); sys.exit(0)
    stage = 'host-fallback'
if args[0] == 'version': print('29.2.1'); sys.exit(0)
if args[:2] == ['compose', 'version']: print('2.36.0'); sys.exit(0)
if args[0] == 'inspect': print('healthy'); sys.exit(0)
if args[0] == 'compose':
    op = next((a for a in args if a in ['build', 'up', 'run', 'exec', 'ps']), None)
    if op == 'up': stage = 'dependencies' if 'postgres' in args and 'redis' in args else 'application'
    elif 'upgrade' in args: stage = 'migration'
    elif 'scripts/create_admin.py' in args: stage = 'admin'
    elif 'scripts.seed_enrollment_key' in args: stage = 'enrollment'
with open(os.environ['SEQUENCE_CALLS'], 'a', encoding='utf-8') as log:
    log.write(json.dumps({'args': args, 'stage': stage}) + '\\n')
if stage == 'host-fallback':
    print('Host Python execution forbidden by isolated test boundary', file=sys.stderr); sys.exit(74)
if stage == 'application' and not all(state.get(k) for k in ['dependencies','migration','admin','enrollment']):
    print('API was started before schema and bootstrap were ready', file=sys.stderr); sys.exit(71)
if stage in ['migration','admin','enrollment'] and (not state.get('dependencies') or 'run' not in args or '--no-deps' not in args):
    print('Bootstrap must run as an isolated one-off after dependencies', file=sys.stderr); sys.exit(72)
if stage in ['dependencies','application'] and '--wait' not in args:
    print('Startup did not wait for dependency/application readiness', file=sys.stderr); sys.exit(73)
if os.environ['SEQUENCE_FAILURE'] == stage:
    print('Synthetic failure at ' + stage, file=sys.stderr); sys.exit(17)
if stage != 'other':
    if stage == 'admin':
        print('SPHERE_ADMIN_BOOTSTRAP=' + ('existing' if state.get('admin') else 'created'))
    state[stage] = True
    statefile.write_text(json.dumps(state))
''', encoding="utf-8")
    wrapper = tmp_path / ("run.ps1" if shell == "powershell" else "run.sh")
    if shell == "powershell":
        shutil.copyfile(REPOSITORY / "scripts/full-deploy.ps1", root / "scripts/full-deploy.ps1")
        wrapper.write_text('''$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
function global:docker { & $env:SEQUENCE_PYTHON $env:SEQUENCE_BOUNDARY @args }
function global:python { & $env:SEQUENCE_PYTHON $env:SEQUENCE_BOUNDARY host-python @args }
function global:Invoke-WebRequest { return @{StatusCode=200; Content='{"status":"ready"}'} }
try { & $env:SEQUENCE_SCRIPT -Headless } catch { Write-Host $_.Exception.Message; exit 1 }
''', encoding="utf-8")
    else:
        source = (REPOSITORY / "scripts/full-deploy.sh").read_text(encoding="utf-8")
        prefix, entrypoint = source.rsplit('\nmain "$@"', 1)
        assert not entrypoint.strip()
        (root / "scripts/full-deploy.sh").write_text(prefix + "\n", encoding="utf-8")
        wrapper.write_text('''source "$SEQUENCE_SCRIPT" --headless
docker() { "$SEQUENCE_PYTHON" "$SEQUENCE_BOUNDARY" "$@"; }
python() { "$SEQUENCE_PYTHON" "$SEQUENCE_BOUNDARY" host-python "$@"; }
python3() { "$SEQUENCE_PYTHON" "$SEQUENCE_BOUNDARY" host-python "$@"; }
curl() { printf '%s\\n' '{"status":"ready"}'; }
main
''', encoding="utf-8")

    def run(failure="none"):
        env = os.environ.copy()
        env.update(SEQUENCE_SCRIPT=(root / "scripts" / ("full-deploy.ps1" if shell == "powershell" else "full-deploy.sh")).as_posix(),
            SEQUENCE_BOUNDARY=boundary.as_posix(), SEQUENCE_PYTHON=Path(sys.executable).as_posix(),
            SEQUENCE_STATE=state.as_posix(), SEQUENCE_CALLS=calls.as_posix(), SEQUENCE_FAILURE=failure,
            SPHERE_ADMIN_EMAIL="pilot@example.org", SPHERE_ADMIN_PASSWORD="synthetic-sequence-password",
            COMPOSE_PROJECT_NAME="isolated-sequence")
        args = [executable, "-NoProfile", "-NonInteractive", "-File", str(wrapper)] if shell == "powershell" else [executable, wrapper.as_posix()]
        result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        recorded = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []
        return result, recorded
    return run


def phases(calls):
    return [c["stage"] for c in calls if c["stage"] != "other"]


def test_fresh_full_deploy_orders_dependency_migration_bootstrap_and_application(full_deploy):
    result, calls = full_deploy()
    assert result.returncode == 0, result.stdout + result.stderr
    assert phases(calls) == ["dependencies", "migration", "admin", "enrollment", "application"]


@pytest.mark.parametrize("failure", ["dependencies", "migration", "admin", "enrollment", "application"])
def test_full_deploy_stops_on_phase_failure_without_host_fallback_or_false_success(full_deploy, failure):
    result, calls = full_deploy(failure)
    assert result.returncode != 0, result.stdout + result.stderr
    assert phases(calls)[-1] == failure, calls
    assert "Synthetic failure at " + failure in result.stdout + result.stderr
    assert "РАЗВЁРНУТА УСПЕШНО" not in result.stdout


def test_repeat_full_deploy_keeps_the_same_order(full_deploy):
    first, _ = full_deploy()
    assert first.returncode == 0, first.stdout + first.stderr
    second, calls = full_deploy()
    assert second.returncode == 0, second.stdout + second.stderr
    assert phases(calls) == ["dependencies", "migration", "admin", "enrollment", "application"] * 2
