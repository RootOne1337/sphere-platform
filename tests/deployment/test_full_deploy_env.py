"""Render synthetic Compose through the shipped PowerShell wrapper; no daemon."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture
def render(tmp_path):
    pwsh, docker = shutil.which("pwsh"), shutil.which("docker")
    if not pwsh or not docker:
        if os.environ.get("CI"):
            pytest.fail("PowerShell and Docker Compose are required")
        pytest.skip("PowerShell/Docker Compose unavailable")
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    (root / "docker-compose.yml").write_text('''services:
  probe:
    image: busybox:latest
    environment:
      MARKER: ${SPHERE_ENV_TEST_MARKER:-missing}
''', encoding="utf-8")
    (root / "docker-compose.full.yml").write_text("services: {}\n", encoding="utf-8")
    # A different caller directory must not supply the installation's configuration.
    (tmp_path / ".env").write_text("SPHERE_ENV_TEST_MARKER=wrong-caller\n", encoding="utf-8")
    calls = tmp_path / "docker-called.txt"
    wrapper = tmp_path / "run.ps1"
    wrapper.write_text('''$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$ProjectDir = $env:ENV_TEST_ROOT
$ComposeFiles = @('-f', (Join-Path $ProjectDir 'docker-compose.yml'), '-f', (Join-Path $ProjectDir 'docker-compose.full.yml'))
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:ENV_TEST_SOURCE, [ref]$null, [ref]$null)
$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-Compose'}, $true) | ForEach-Object { Invoke-Expression $_.Extent.Text }
function global:docker {
    'called' | Out-File $env:ENV_TEST_CALLS -Append
    & $env:ENV_TEST_DOCKER @args
}
try { Invoke-Compose @('config', '--format', 'json') } catch { Write-Error $_.Exception.Message; exit 1 }
''', encoding="utf-8")

    def run(mode, shell_override=False):
        if mode in {"both", "local"}:
            (root / ".env.local").write_text("SPHERE_ENV_TEST_MARKER=selected-local\n", encoding="utf-8")
        if mode in {"both", "default"}:
            (root / ".env").write_text("SPHERE_ENV_TEST_MARKER=selected-default\n", encoding="utf-8")
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("COMPOSE_") or key == "SPHERE_ENV_TEST_MARKER":
                env.pop(key)
        env.update(ENV_TEST_ROOT=str(root), ENV_TEST_SOURCE=str(REPOSITORY / "scripts/full-deploy.ps1"),
            ENV_TEST_DOCKER=docker, ENV_TEST_CALLS=str(calls), COMPOSE_PROJECT_NAME="isolated-env-probe")
        if shell_override:
            env["SPHERE_ENV_TEST_MARKER"] = "explicit-process-override"
        result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(wrapper)],
            cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        return result, calls.exists()
    return run


@pytest.mark.parametrize("mode", ["both", "local", "default"])
def test_full_deploy_renders_the_selected_installation_env_from_another_directory(render, mode):
    result, called = render(mode)
    assert result.returncode == 0, result.stdout + result.stderr
    assert called
    marker = json.loads(result.stdout)["services"]["probe"]["environment"]["MARKER"]
    assert marker == ("selected-default" if mode == "default" else "selected-local")


def test_explicit_process_environment_keeps_compose_precedence(render):
    result, _ = render("both", shell_override=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["services"]["probe"]["environment"]["MARKER"] == "explicit-process-override"


def test_full_deploy_rejects_missing_installation_env_before_docker(render):
    result, called = render("missing")
    assert result.returncode != 0, result.stdout
    assert not called
