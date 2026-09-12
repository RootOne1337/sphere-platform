[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][string]$PythonExecutable,
    [Parameter(Mandatory)][ValidatePattern('^Sphere-LDPlayer-[a-z0-9_-]+$')][string]$TaskName
)
$ErrorActionPreference = 'Stop'
$watchdogConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$watchdogPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$watchdogRunner = Join-Path $PSScriptRoot 'Invoke-LDPlayerWatchdog.ps1'
$watchdogRoot = Split-Path -Parent $PSScriptRoot
foreach ($watchdogPath in @($watchdogConfig, $watchdogPython, $watchdogRunner)) {
    if ($watchdogPath.Contains('"') -or $watchdogPath.Contains("`r") -or $watchdogPath.Contains("`n")) {
        throw 'Task paths cannot contain quotes or line breaks.'
    }
}
# Validate the native read-only adapter before registering any background work.
Push-Location -LiteralPath $watchdogRoot
try {
    & $watchdogPython -m scripts.ldplayer_watchdog --config $watchdogConfig --check-config
    if ($LASTEXITCODE -ne 0) { throw 'Watchdog configuration or host inspection failed.' }
} finally {
    Pop-Location
}
$watchdogIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$watchdogArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -ConfigPath "{1}" -PythonExecutable "{2}"' -f $watchdogRunner, $watchdogConfig, $watchdogPython
$watchdogShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$watchdogExisting = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($watchdogExisting) {
    if ($watchdogExisting.Actions.Count -ne 1 -or
        $watchdogExisting.Actions[0].Execute -ne $watchdogShell -or
        $watchdogExisting.Actions[0].Arguments -ne $watchdogArguments -or
        $watchdogExisting.Principal.UserId -ne $watchdogIdentity) {
        throw 'Existing scheduled task has a different owner/action; it was not changed.'
    }
}
$watchdogAction = New-ScheduledTaskAction -Execute $watchdogShell -Argument $watchdogArguments -WorkingDirectory $watchdogRoot
$watchdogTriggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $watchdogIdentity),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1))
)
$watchdogSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$watchdogPrincipal = New-ScheduledTaskPrincipal -UserId $watchdogIdentity -LogonType Interactive -RunLevel Limited
$watchdogTask = New-ScheduledTask -Action $watchdogAction -Trigger $watchdogTriggers -Settings $watchdogSettings `
    -Principal $watchdogPrincipal -Description "Recover only missing LDPlayer NAT processes allowlisted in $watchdogConfig. No server credential; no VM restart."
Register-ScheduledTask -TaskName $TaskName -InputObject $watchdogTask -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
[pscustomobject]@{ TaskName = $TaskName; User = $watchdogIdentity; Config = $watchdogConfig; IntervalSeconds = 60; RequiresUserLogon = $true }
