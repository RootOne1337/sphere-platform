"""Existing installation configuration must survive unattended full-deploy."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["powershell", "bash"])
def secret_stage(request, tmp_path):
    shell = request.param
    executable = shutil.which("pwsh" if shell == "powershell" else "bash")
    if shell == "bash" and os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} required for full-deploy configuration preservation")
        pytest.skip(f"{shell} unavailable")
    root = tmp_path / "existing installation"
    root.mkdir()
    fake = root / "generator_boundary.py"
    fake.write_text('''import json, os, sys
from pathlib import Path
assert sys.argv[1:] == ["scripts/generate_secrets.py", "--output", ".env.local"]
Path(os.environ["BOOTSTRAP_CALLS"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
Path(".env.local").write_text("ENVIRONMENT=production\\nPOSTGRES_PASSWORD=synthetic-new-password\\n", encoding="utf-8")
''', encoding="utf-8")
    calls = root / "generator-calls.json"
    script = root / ("stage.ps1" if shell == "powershell" else "stage.sh")
    if shell == "powershell":
        script.write_text('''$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$ProjectDir = $env:BOOTSTRAP_ROOT
$LogFile = Join-Path $ProjectDir 'stage.log'
$Headless = $true
$SkipSecrets = $env:BOOTSTRAP_SKIP -eq '1'
$Production = $false
Set-Location -LiteralPath $ProjectDir
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:BOOTSTRAP_SOURCE, [ref]$null, [ref]$null)
$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -in @('Write-Log', 'Step-GenerateSecrets')}, $true) | ForEach-Object { Invoke-Expression $_.Extent.Text }
function global:python { & $env:BOOTSTRAP_PYTHON $env:BOOTSTRAP_FAKE @args }
Step-GenerateSecrets
''', encoding="utf-8")
    else:
        source = (REPOSITORY / "scripts/full-deploy.sh").read_text(encoding="utf-8")
        preamble, entrypoint = source.rsplit('\nmain "$@"', 1)
        assert not entrypoint.strip()
        (root / "library.sh").write_text(preamble + "\n", encoding="utf-8")
        script.write_text('''source "$BOOTSTRAP_ROOT/library.sh" --headless
PROJECT_DIR="$BOOTSTRAP_ROOT"
LOG_FILE="$BOOTSTRAP_ROOT/stage.log"
if [[ "$BOOTSTRAP_SKIP" == 1 ]]; then SKIP_SECRETS=true; fi
python3() { "$BOOTSTRAP_PYTHON" "$BOOTSTRAP_FAKE" "$@"; }
python() { "$BOOTSTRAP_PYTHON" "$BOOTSTRAP_FAKE" "$@"; }
generate_secrets
''', encoding="utf-8")

    def run(existing, skip=False):
        snapshots = {}
        for name in existing:
            data = ("# installation config " + name + "\nENVIRONMENT=development\n"
                    "POSTGRES_PASSWORD=synthetic-retained-password\n"
                    "SPHERE_BOOTSTRAP_ORG_SLUG=retained-operator\n").encode()
            (root / name).write_bytes(data)
            snapshots[name] = data
        env = os.environ.copy()
        env.update(BOOTSTRAP_ROOT=root.as_posix(), BOOTSTRAP_PYTHON=Path(sys.executable).as_posix(),
            BOOTSTRAP_FAKE=fake.as_posix(), BOOTSTRAP_CALLS=str(calls), BOOTSTRAP_SKIP=str(int(skip)),
            BOOTSTRAP_SOURCE=str(REPOSITORY / "scripts/full-deploy.ps1"), SPHERE_ENV="development")
        args = [executable, "-NoProfile", "-NonInteractive", "-File", str(script)] if shell == "powershell" else [executable, script.as_posix()]
        result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        for name, data in snapshots.items():
            assert (root / name).read_bytes() == data, "An existing credential file was changed"
        return root, json.loads(calls.read_text()) if calls.exists() else None
    return run


@pytest.mark.parametrize("existing,skip", [
    ([".env"], False), ([".env"], True), ([".env.local"], False),
    ([".env", ".env.local"], False), ([], False),
])
def test_unattended_bootstrap_preserves_existing_credentials(secret_stage, existing, skip):
    root, generated = secret_stage(existing, skip)
    if existing:
        assert generated is None, "Existing installation was shadowed by newly generated credentials"
        if ".env.local" not in existing:
            assert not (root / ".env.local").exists()
    else:
        assert generated == ["scripts/generate_secrets.py", "--output", ".env.local"]
        assert "ENVIRONMENT=development" in (root / ".env.local").read_text(encoding="utf-8-sig")
