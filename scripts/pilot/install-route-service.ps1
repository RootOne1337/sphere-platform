# Per-user loopback API watchdog. No admin rights, saved password or native input.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$taskName = 'Sphere-RouteProcessor'
$taskPython = Join-Path $taskRoot '.local-pilot\motor-worker-venv\Scripts\pythonw.exe'
$taskModule = Join-Path $taskRoot 'scripts\pilot\route_service_watchdog.py'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf) -or -not (Test-Path -LiteralPath $taskModule -PathType Leaf)) {
    throw 'Local route runtime is missing.'
}
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskArguments = '-m scripts.pilot.route_service_watchdog'
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    if (@($existingTask.Actions).Count -ne 1 -or $existingTask.Actions[0].Execute -ne $taskPython -or
        $existingTask.Actions[0].Arguments -ne $taskArguments -or $existingTask.Actions[0].WorkingDirectory -ne $taskRoot) {
        throw 'Task name is occupied by another action. It was not changed.'
    }
} else {
    $taskAction = New-ScheduledTaskAction -Execute $taskPython -Argument $taskArguments -WorkingDirectory $taskRoot
    $taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger `
        -Principal $taskPrincipal -Settings $taskSettings `
        -Description 'Sphere loopback route API only; health monitoring, no automatic test or Android input' | Out-Null
}
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
