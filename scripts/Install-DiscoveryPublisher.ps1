[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][string]$PythonExecutable,
    [Parameter(Mandatory)][ValidatePattern('^Sphere-Publisher-[a-z0-9_-]+$')][string]$TaskName
)
$ErrorActionPreference = 'Stop'
$publisherConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$publisherPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$publisherRunner = Join-Path $PSScriptRoot 'Invoke-DiscoveryPublisher.ps1'
$publisherRoot = Split-Path -Parent $PSScriptRoot
foreach ($publisherPath in @($publisherConfig, $publisherPython, $publisherRunner)) {
    if ($publisherPath.Contains('"') -or $publisherPath.Contains("`r") -or $publisherPath.Contains("`n")) {
        throw 'Task paths cannot contain quotes or line breaks.'
    }
}
$publisherIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$publisherArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -ConfigPath "{1}" -PythonExecutable "{2}"' -f $publisherRunner, $publisherConfig, $publisherPython
$publisherShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$publisherExisting = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($publisherExisting) {
    if ($publisherExisting.Actions.Count -ne 1 -or
        $publisherExisting.Actions[0].Execute -ne $publisherShell -or
        $publisherExisting.Actions[0].Arguments -ne $publisherArguments -or
        $publisherExisting.Principal.UserId -ne $publisherIdentity) {
        throw 'Existing scheduled task has a different owner/action; it was not changed.'
    }
}
$publisherAction = New-ScheduledTaskAction -Execute $publisherShell -Argument $publisherArguments -WorkingDirectory $publisherRoot
$publisherTriggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $publisherIdentity),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1))
)
$publisherSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$publisherPrincipal = New-ScheduledTaskPrincipal -UserId $publisherIdentity -LogonType Interactive -RunLevel Limited
$publisherTask = New-ScheduledTask -Action $publisherAction -Trigger $publisherTriggers -Settings $publisherSettings `
    -Principal $publisherPrincipal -Description "Publish signed routes only for configuration $publisherConfig. Uses this user's Docker/GitHub context; no stored task password."
Register-ScheduledTask -TaskName $TaskName -InputObject $publisherTask -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
[pscustomobject]@{ TaskName = $TaskName; User = $publisherIdentity; Config = $publisherConfig; IntervalSeconds = 60; RequiresUserLogon = $true }
