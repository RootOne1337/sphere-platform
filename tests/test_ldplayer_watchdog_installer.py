"""Execute the PowerShell installer with scheduler cmdlets replaced by recorders."""
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Task Scheduler installer")


@pytest.mark.parametrize("kind,scenario", [
    (kind, scenario) for kind in ("LDPlayerWatchdog", "DiscoveryPublisher")
    for scenario in ("new", "legacy", "current", "foreign-task", "foreign-owner", "missing-gui")
] + [("LDPlayerWatchdog", "invalid-config")])
def test_installer_checks_before_registration_and_creates_scoped_hidden_task(tmp_path, kind, scenario):
    config = tmp_path / "station config.json"
    config.write_text("{}")
    fake_python = tmp_path / "python stub.ps1"
    fake_python.write_text("$global:LASTEXITCODE = " + ("1" if scenario == "invalid-config" else "0"))
    if scenario != "missing-gui":
        (tmp_path / "pythonw.exe").write_bytes(b"scheduler test fixture; never executed")
    output = tmp_path / "record.json"
    installer = Path(__file__).resolve().parents[1] / f"scripts/Install-{kind}.ps1"
    harness = tmp_path / "harness.ps1"
    harness.write_text(r'''
param($Installer, $Config, $Python, $OutputPath, $Scenario, $Kind)
$ErrorActionPreference = 'Stop'
$global:record = @{ registered = $false; started = $false }
$taskName = if ($Kind -eq 'LDPlayerWatchdog') { 'Sphere-LDPlayer-test' } else { 'Sphere-Publisher-test' }
$moduleName = if ($Kind -eq 'LDPlayerWatchdog') { 'ldplayer_watchdog' } else { 'discovery_publisher' }
$once = if ($Kind -eq 'DiscoveryPublisher') { ' --once' } else { '' }
function Get-ScheduledTask {
    if ($Scenario -eq 'foreign-task') {
        return [pscustomobject]@{ Actions = @([pscustomobject]@{Execute='foreign';Arguments='foreign'}); Principal = [pscustomobject]@{UserId='other'} }
    }
    if ($Scenario -in @('legacy', 'current', 'foreign-owner')) {
        $owner = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name.Split('\')[-1]
        $execute = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
        $arguments = '-m scripts.{0} --config "{1}"{2}' -f $moduleName, $Config, $once
        if ($Scenario -eq 'foreign-owner') { $owner = 'S-1-5-18' }
        if ($Scenario -eq 'legacy') {
            $execute = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
            $runner = Join-Path (Split-Path -Parent $Installer) ('Invoke-' + $Kind + '.ps1')
            $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -ConfigPath "{1}" -PythonExecutable "{2}"' -f $runner, $Config, $Python
        }
        return [pscustomobject]@{Actions=@([pscustomobject]@{Execute=$execute;Arguments=$arguments});Principal=[pscustomobject]@{UserId=$owner}}
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
try { & $Installer -ConfigPath $Config -PythonExecutable $Python -TaskName $taskName | Out-Null }
catch { $global:record.error = $_.Exception.Message }
$global:record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
''', encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(harness),
        str(installer), str(config), str(fake_python), str(output), scenario, kind],
        capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr
    record = json.loads(output.read_text(encoding="utf-8-sig"))
    if scenario in ("new", "legacy", "current"):
        assert "error" not in record, record
        assert record["registered"] and record["started"]
        assert record["name"] == ("Sphere-LDPlayer-test" if kind == "LDPlayerWatchdog" else "Sphere-Publisher-test")
        assert record["interval"] == 60 and record["logon"]
        assert record["multiple"] == "IgnoreNew"
        assert record["principal"]["level"] == "Limited"
        assert record["principal"]["logon"] == "Interactive"
        assert record["action"]["execute"] == str(tmp_path / "pythonw.exe")
        assert record["action"]["arguments"].startswith('-m scripts.')
        assert "powershell" not in record["action"]["arguments"].lower()
        assert str(config) in record["action"]["arguments"]
    else:
        assert "error" in record and not record["registered"] and not record["started"]
