"""Execute the PowerShell installer with scheduler cmdlets replaced by recorders."""
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Task Scheduler installer")


@pytest.mark.parametrize("scenario", ["new", "foreign-task", "invalid-config"])
def test_installer_checks_before_registration_and_creates_scoped_hidden_task(tmp_path, scenario):
    config = tmp_path / "station config.json"
    config.write_text("{}")
    fake_python = tmp_path / "python stub.ps1"
    fake_python.write_text("$global:LASTEXITCODE = " + ("1" if scenario == "invalid-config" else "0"))
    output = tmp_path / "record.json"
    installer = Path(__file__).resolve().parents[1] / "scripts/Install-LDPlayerWatchdog.ps1"
    harness = tmp_path / "harness.ps1"
    harness.write_text(r'''
param($Installer, $Config, $Python, $OutputPath, $Scenario)
$ErrorActionPreference = 'Stop'
$global:record = @{ registered = $false; started = $false }
function Get-ScheduledTask {
    if ($Scenario -eq 'foreign-task') {
        return [pscustomobject]@{ Actions = @([pscustomobject]@{Execute='foreign';Arguments='foreign'}); Principal = [pscustomobject]@{UserId='other'} }
    }
}
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory)
    $global:record.action = @{ execute=$Execute; arguments=$Argument; directory=$WorkingDirectory }
    return 'action'
}
function New-ScheduledTaskTrigger { param([switch]$AtLogOn, $User, [switch]$Once, $At, $RepetitionInterval)
    if ($Once) { $global:record.interval = $RepetitionInterval.TotalSeconds }
    if ($AtLogOn) { $global:record.logon = $true }
    return 'trigger'
}
function New-ScheduledTaskSettingsSet { param($MultipleInstances, [switch]$StartWhenAvailable, $ExecutionTimeLimit, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries)
    $global:record.multiple = $MultipleInstances
    return 'settings'
}
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel)
    $global:record.principal = @{ user=$UserId; logon=$LogonType; level=$RunLevel }
    return 'principal'
}
function New-ScheduledTask { param($Action, $Trigger, $Settings, $Principal, $Description) return 'task' }
function Register-ScheduledTask { param($TaskName, $InputObject, [switch]$Force)
    $global:record.registered = $true; $global:record.name = $TaskName
}
function Start-ScheduledTask { param($TaskName) $global:record.started = $true }
try { & $Installer -ConfigPath $Config -PythonExecutable $Python -TaskName 'Sphere-LDPlayer-test' | Out-Null }
catch { $global:record.error = $_.Exception.Message }
$global:record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
''', encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(harness),
        str(installer), str(config), str(fake_python), str(output), scenario],
        capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    record = json.loads(output.read_text(encoding="utf-8-sig"))
    if scenario == "new":
        assert "error" not in record, record
        assert record["registered"] and record["started"]
        assert record["name"] == "Sphere-LDPlayer-test"
        assert record["interval"] == 60 and record["logon"]
        assert record["multiple"] == "IgnoreNew"
        assert record["principal"]["level"] == "Limited"
        assert record["principal"]["logon"] == "Interactive"
        assert '-WindowStyle Hidden -File "' in record["action"]["arguments"]
        assert str(config) in record["action"]["arguments"]
    else:
        assert "error" in record and not record["registered"] and not record["started"]
