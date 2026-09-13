[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][string]$PythonExecutable,
    [Parameter(Mandatory)][ValidatePattern('^Sphere-Publisher-[a-z0-9_-]+$')][string]$TaskName
)
$ErrorActionPreference = 'Stop'
$publisherConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$publisherPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$publisherWindowlessPython = (Resolve-Path -LiteralPath (Join-Path (Split-Path -Parent $publisherPython) 'pythonw.exe')).Path
$publisherRunner = Join-Path $PSScriptRoot 'Invoke-DiscoveryPublisher.ps1'
$publisherRoot = Split-Path -Parent $PSScriptRoot
foreach ($publisherPath in @($publisherConfig, $publisherPython, $publisherWindowlessPython, $publisherRunner)) {
    if ($publisherPath.Contains('"') -or $publisherPath.Contains("`r") -or $publisherPath.Contains("`n")) {
        throw 'Task paths cannot contain quotes or line breaks.'
    }
}
$publisherIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$publisherLegacyArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -ConfigPath "{1}" -PythonExecutable "{2}"' -f $publisherRunner, $publisherConfig, $publisherPython
$publisherArguments = '-m scripts.discovery_publisher --config "{0}" --once' -f $publisherConfig
$publisherShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$publisherExisting = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($publisherExisting) {
    $publisherOwner = $publisherExisting.Principal.UserId
    $publisherOwnerSid = if ($publisherOwner -match '^S-1-') {
        [System.Security.Principal.SecurityIdentifier]::new($publisherOwner).Value
    } else {
        ([System.Security.Principal.NTAccount]::new($publisherOwner)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    }
    $publisherSameAction = $publisherExisting.Actions.Count -eq 1 -and (
        ($publisherExisting.Actions[0].Execute -eq $publisherWindowlessPython -and $publisherExisting.Actions[0].Arguments -eq $publisherArguments) -or
        ($publisherExisting.Actions[0].Execute -eq $publisherShell -and $publisherExisting.Actions[0].Arguments -eq $publisherLegacyArguments))
    if ($publisherExisting.Actions.Count -ne 1 -or
        -not $publisherSameAction -or
        $publisherOwnerSid -ne [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value) {
        throw 'Existing scheduled task has a different owner/action; it was not changed.'
    }
}
$publisherAction = New-ScheduledTaskAction -Execute $publisherWindowlessPython -Argument $publisherArguments -WorkingDirectory $publisherRoot
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
