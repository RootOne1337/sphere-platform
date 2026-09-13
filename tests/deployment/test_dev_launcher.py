"""Run the real PowerShell launcher with a process-backed Docker boundary.

No Docker daemon, containers, network listeners or repository .env are used.
The fake CLI returns native process exit codes (not PowerShell exceptions).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture
def launch(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        if os.environ.get("CI"):
            pytest.fail("PowerShell is required for the launcher regression tests")
        pytest.skip("PowerShell unavailable; launcher was not exercised")
    root = tmp_path / "checkout with spaces"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(REPOSITORY / "scripts/start-dev.ps1", root / "scripts/start-dev.ps1")
    for name in [".env", ".env.example"]:
        (root / name).write_text("# synthetic test configuration\n", encoding="utf-8")
    calls = tmp_path / "calls.jsonl"
    fake = tmp_path / "docker_boundary.py"
    fake.write_text('''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["LAUNCHER_CALLS"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
scenario = os.environ["LAUNCHER_SCENARIO"]
stage = next((s for s in ["info", "config", "build", "up"] if s in args), "other")
failed = scenario == stage
if scenario in ["postgres", "redis", "backend", "frontend"]:
    failed = stage == "up" and "--wait" in args
if args and args[0] == "inspect":
    print("healthy")  # Legacy launcher checks only hard-coded DB containers.
if failed:
    print("Synthetic native CLI failure: " + scenario)
    sys.exit(17)
''', encoding="utf-8")
    wrapper = tmp_path / "run.ps1"
    wrapper.write_text('''$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
function global:docker { & $env:LAUNCHER_PYTHON $env:LAUNCHER_FAKE @args }
& $env:LAUNCHER_SCRIPT -Rebuild
exit $LASTEXITCODE
''', encoding="utf-8")

    def run(scenario="success", missing_env=False, local_env=False):
        if missing_env:
            (root / ".env").unlink()
        if local_env:
            (root / ".env.local").write_text("# synthetic generated configuration\n", encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            LAUNCHER_SCENARIO=scenario, LAUNCHER_CALLS=str(calls),
            LAUNCHER_FAKE=str(fake), LAUNCHER_SCRIPT=str(root / "scripts/start-dev.ps1"),
            LAUNCHER_PYTHON=sys.executable, COMPOSE_PROJECT_NAME="isolated-custom-project",
        )
        result = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-File", str(wrapper)],
            cwd=tmp_path, env=environment, capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        )
        recorded = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
        return result, recorded, root

    return run


@pytest.mark.parametrize("stage", ["info", "config", "build", "up"])
def test_launcher_stops_after_native_docker_failure(launch, stage):
    result, calls, _ = launch(stage)
    assert result.returncode != 0, result.stdout
    assert stage in calls[-1], calls
    assert "СТЕК ЗАПУЩЕН" not in result.stdout


@pytest.mark.parametrize("service", ["postgres", "redis", "backend", "frontend"])
def test_launcher_does_not_report_success_when_service_readiness_fails(launch, service):
    result, calls, _ = launch(service)
    assert result.returncode != 0, result.stdout
    assert "--wait" in calls[-1], calls
    assert "СТЕК ЗАПУЩЕН" not in result.stdout


def test_launcher_requires_configuration_after_creating_env_template(launch):
    result, calls, root = launch(missing_env=True)
    assert result.returncode != 0, result.stdout
    assert (root / ".env").read_bytes() == (root / ".env.example").read_bytes()
    assert not any("up" in call or "build" in call for call in calls), calls


def test_launcher_success_waits_in_the_selected_compose_project(launch):
    result, calls, root = launch()
    assert result.returncode == 0, result.stderr
    assert "СТЕК ЗАПУЩЕН" in result.stdout
    assert any("config" in call and "--quiet" in call for call in calls), calls
    up = next(call for call in calls if "up" in call)
    assert "--wait" in up and "--wait-timeout" in up, up
    assert str(root / "docker-compose.yml") in up
    assert str(root / "docker-compose.full.yml") in up
    assert not any("inspect" in call for call in calls), calls


@pytest.mark.parametrize("missing_env", [False, True])
def test_dev_launcher_uses_generated_local_env_for_every_startup_compose_call(launch, missing_env):
    result, calls, root = launch(missing_env=missing_env, local_env=True)
    assert result.returncode == 0, result.stdout + result.stderr
    for call in calls:
        if call[0] == "compose":
            assert "--env-file" in call, call
            assert call[call.index("--env-file") + 1] == str(root / ".env.local")
    if missing_env:
        assert not (root / ".env").exists()
