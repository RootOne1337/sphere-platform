[CmdletBinding()]
param(
    [switch]$Plan,
    [switch]$Install,
    [switch]$InstallTask,
    [string]$PythonPath,
    [string]$BrowserOrigin = 'http://127.0.0.1:28080'
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$workerDir = Join-Path $repoRoot '.local-pilot\motor-worker-venv'
$offlineDir = Join-Path $repoRoot '.local-pilot\motor-amd-venv'
$requirements = Join-Path $repoRoot 'requirements-motor-vision.txt'
$taskName = 'Sphere-RouteProcessor'
$originUri = $null
if ($BrowserOrigin -notmatch '^https?://[^/?#\s\\*]+$' -or
    -not [Uri]::TryCreate($BrowserOrigin, [UriKind]::Absolute, [ref]$originUri) -or
    $originUri.UserInfo -or $originUri.HostNameType -eq [UriHostNameType]::Unknown -or
    $originUri.Port -lt 1 -or $originUri.GetLeftPart([UriPartial]::Authority) -cne $BrowserOrigin) {
    throw 'BrowserOrigin must be a canonical http(s) origin with no credentials, path, query, fragment or wildcard.'
}

Write-Output "Repository: $repoRoot"
Write-Output "Optional Windows loopback route worker: 127.0.0.1:3342; expected browser origin $BrowserOrigin."
Write-Output 'Creates two isolated Python 3.12 environments from requirements-motor-vision.txt (includes requirements-motor-worker.txt).'
Write-Output 'It does not install reconstruction tools, model weights, trained models, or start a reconstruction job.'
Write-Output 'The optional Scheduled Task is registered at user logon only when -InstallTask is specified; registration does not start it now.'
if ($Plan -and $Install) { throw 'Choose either -Plan or -Install.' }
if ($InstallTask -and -not ($Install -or $Plan)) { throw '-InstallTask requires -Install (or -Plan to preview).'}
if (-not $Install) {
    Write-Output "Plan only: create $workerDir and $offlineDir; task registration requested: $($InstallTask.IsPresent)."
    foreach ($dir in @($workerDir, $offlineDir)) {
        $existingPython = Join-Path $dir 'Scripts\python.exe'
        if (Test-Path -LiteralPath $existingPython -PathType Leaf) {
            $status = & $existingPython -c 'import sys,importlib.util;print(sys.version.split()[0],*(bool(importlib.util.find_spec(x)) for x in sys.argv[1:]))' numpy cv2 av
            if ($LASTEXITCODE -eq 0) { Write-Output "Existing runtime $dir : $status" } else { Write-Output "Existing runtime $dir : check failed" }
        } else { Write-Output "Existing runtime absent: $dir" }
    }
    try {
        $response = Invoke-RestMethod -Uri 'http://127.0.0.1:3342/health' -Headers @{ Origin=$BrowserOrigin; 'X-Sphere-Reconstruction'='1' } -TimeoutSec 3
        if ($response.service -eq 'sphere-reconstruction-v1' -and $response.one_active_job -eq $true) { Write-Output 'Existing loopback worker: health identity confirmed.' }
        else { Write-Output 'Existing loopback worker: unexpected health identity.' }
    } catch { Write-Output 'Existing loopback worker: health unavailable; no service started.' }
    $toolsDir = Join-Path $repoRoot '.local-pilot\reconstruction-tools'
    foreach ($name in @('pycolmap-4.2.1','brush-app-v0.3.0-windows.zip','brush-system-timing','openmvs-v2.4.0-cpu')) {
        Write-Output "Tool $name present: $(Test-Path -LiteralPath (Join-Path $toolsDir $name))"
    }
    Write-Output 'Read-only checks included local Python processes and loopback HTTP; no persistent changes made.'
    return
}

if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) { throw 'Pinned motor requirements file is missing.' }
foreach ($dir in @($workerDir, $offlineDir)) {
    if (Test-Path -LiteralPath $dir) { throw "Destination already exists: $dir. Preserve it; inspect or select a clean checkout." }
}
if ($InstallTask) {
    if (-not (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue)) { throw 'Windows ScheduledTasks PowerShell module is required for -InstallTask.' }
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw "Scheduled task $taskName already exists; it will not be replaced." }
}
if (-not $PythonPath) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $launcher) { throw 'Python launcher not found. Supply -PythonPath to a Python 3.12 executable.' }
    $candidates = @(& $launcher.Source -3.12 -c 'import sys; print(sys.executable)')
    if ($LASTEXITCODE -ne 0 -or $candidates.Count -ne 1) { throw 'Python 3.12 not found; supply -PythonPath.' }
    $PythonPath = $candidates[0]
}
$python = (Resolve-Path -LiteralPath $PythonPath).Path
$version = @(& $python -c 'import sys;print(sys.version_info.major,sys.version_info.minor,sep=chr(46))')
if ($LASTEXITCODE -ne 0 -or $version.Count -ne 1 -or $version[0] -ne '3.12') { throw 'PythonPath must point to a working Python 3.12 interpreter.' }

foreach ($dir in @($workerDir, $offlineDir)) {
    & $python -m venv $dir
    if ($LASTEXITCODE -ne 0) { throw "Creating venv failed: $dir. Partial files were preserved for inspection." }
    $envPython = Join-Path $dir 'Scripts\python.exe'
    & $envPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Installing pinned requirements failed: $dir. Partial files were preserved for inspection." }
    & $envPython -c 'import numpy,cv2,av;print(numpy.__version__,cv2.__version__,av.__version__)'
    if ($LASTEXITCODE -ne 0) { throw "Runtime import check failed: $dir." }
}
if ($InstallTask) {
    $pythonw = Join-Path $workerDir 'Scripts\pythonw.exe'
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m scripts.pilot.route_service_watchdog --origin `"$BrowserOrigin`"" -WorkingDirectory $repoRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Description 'Optional Sphere local route worker; no automatic job replay.' | Out-Null
    Write-Output "Registered $taskName for user logon; it was not started."
}
Write-Output 'Environments created. For manual use, start from repository root:'
Write-Output ".\.local-pilot\motor-worker-venv\Scripts\python.exe -m scripts.pilot.reconstruction_service --origin `"$BrowserOrigin`""
Write-Output 'Additional reconstruction tools and models remain separately required; validate the worker and browser connection before use.'
