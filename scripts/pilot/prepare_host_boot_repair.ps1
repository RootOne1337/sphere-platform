# Verify the local recovery copy; optionally request CHKDSK /f at the next boot.
# No restart, forced dismount, surface scan, cleanup, or service stop.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BackupDirectory,
    [switch]$ScheduleAtNextBoot
)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$base = Join-Path $workspace '.local-pilot'
$backup = [IO.Path]::GetFullPath($BackupDirectory)
if (-not $backup.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Backup must be inside this project .local-pilot.'
}
function Assert-LocalPath([string]$Path) {
    $ancestor = $Path
    while ($ancestor.Length -ge $base.Length) {
        $item = Get-Item -LiteralPath $ancestor
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse backup path rejected.' }
        if ($ancestor -eq $base) { break }
        $ancestor = [IO.Path]::GetDirectoryName($ancestor)
    }
}
Assert-LocalPath $backup
$manifestPath = Join-Path $backup 'backup-manifest.private.json'
Assert-LocalPath $manifestPath
if ((Get-Item -LiteralPath $manifestPath).Length -gt 256KB) { throw 'Manifest budget exceeded.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$files = @($manifest.files)
if ($files.Count -lt 1 -or $files.Count -gt 32 -or $manifest.gitFsckPassed -ne $true -or $manifest.remoteSourceMatches -ne $true) {
    throw 'Recovery manifest is incomplete.'
}
$bytes = 0L
foreach ($file in $files) {
    if ($file.file -isnot [string] -or [IO.Path]::IsPathRooted($file.file) -or $file.sha256 -notmatch '^[a-fA-F0-9]{64}$') {
        throw 'Invalid recovery entry.'
    }
    $path = [IO.Path]::GetFullPath((Join-Path $backup $file.file))
    if (-not $path.StartsWith($backup + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Recovery entry escaped backup directory.'
    }
    Assert-LocalPath $path
    $item = Get-Item -LiteralPath $path
    if ($item.PSIsContainer -or $item.Length -ne $file.bytes -or $item.Length -gt 64MB) { throw 'Recovery file size mismatch.' }
    $stream = [IO.File]::OpenRead($path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally { $hash.Dispose(); $stream.Dispose() }
    if ($digest -ne $file.sha256) { throw 'Recovery file hash mismatch.' }
    $bytes += $item.Length
}
$report = [ordered]@{
    schemaVersion=1; observedAt=[DateTime]::UtcNow.ToString('o'); state='local-copy-verified'
    sourceRevision=$manifest.sourceRevision; verifiedFiles=$files.Count; verifiedBytes=$bytes
    independentBackupAvailable=[bool]$manifest.independentBackupAvailable
    backupOnAffectedPhysicalDisk=[bool]$manifest.backupOnAffectedPhysicalDisk
    notBackedUp=$manifest.notBackedUp; schedulingRequested=[bool]$ScheduleAtNextBoot
    restartPerformed=$false; servicesStopped=$false; repairCompleted=$false
}
if (-not $ScheduleAtNextBoot) { $report | ConvertTo-Json -Depth 4; exit 0 }
if ($env:SystemDrive -ne 'C:') { throw 'Only this host system volume C: is supported.' }
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator required for boot scheduling. Nothing scheduled.'
}
$diagnostics = Get-Content -LiteralPath (Join-Path $backup 'host-diagnostics.private.json') -Raw | ConvertFrom-Json
if ($diagnostics.state -ne 'diagnostics-complete' -or $diagnostics.administrator -ne $true -or $diagnostics.volumeScanRequested -ne $true -or
    $diagnostics.ntfsScanResult -isnot [string] -or
    $diagnostics.ntfsScanResult.Trim() -notin @('ScanErrorsFoundNeedSpotFix', 'ScanErrorsFoundNeedOfflineFix')) {
    throw 'The elevated volume scan must finish successfully before scheduling.'
}
$volume = Get-Volume -DriveLetter C
if ($volume.FileSystemType -ne 'NTFS' -or ($volume.HealthStatus -eq 'Healthy' -and (@($volume.OperationalStatus) -join ',') -eq 'OK')) {
    throw 'Boot repair is not supported or no longer needed; reassess the volume.'
}
$reportPath = Join-Path $backup 'boot-repair-request.private.json'
if (Test-Path -LiteralPath $reportPath) { throw 'A repair request already exists; inspect it before retrying.' }
$report.volumeBefore = $volume | Select-Object DriveLetter,HealthStatus,OperationalStatus,FileSystemType
$registryPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'
$report.bootExecuteBefore = @((Get-ItemProperty -LiteralPath $registryPath).BootExecute)
$report.command = 'chkdsk.exe C: /f'
$encoding = [Text.UTF8Encoding]::new($false)
function Save-Request { [IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 5), $encoding) }
$report.state = 'request-starting'
Save-Request
$process = [Diagnostics.Process]::new()
$process.StartInfo.FileName = Join-Path ([Environment]::SystemDirectory) 'chkdsk.exe'
$process.StartInfo.Arguments = 'C: /f'
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.CreateNoWindow = $true
$process.StartInfo.RedirectStandardInput = $true
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
try {
    $process.Start() | Out-Null
    $report.requestPid = $process.Id
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    # The running Windows system volume cannot be locked. Accept only next-boot scheduling.
    $process.StandardInput.WriteLine('Y')
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(30000)) {
        $report.state = 'request-still-running; no-cancellation-or-restart'
        Save-Request
        $report | ConvertTo-Json -Depth 5
        exit 2
    }
    $report.nativeExitCode = $process.ExitCode
    $text = $stdout.GetAwaiter().GetResult()
    $errorText = $stderr.GetAwaiter().GetResult()
    $report.stdout = $text.Substring(0, [Math]::Min(32768, $text.Length))
    $report.stderr = $errorText.Substring(0, [Math]::Min(4096, $errorText.Length))
    $report.outputTruncated = $text.Length -gt 32768 -or $errorText.Length -gt 4096
    $report.bootExecuteAfter = @((Get-ItemProperty -LiteralPath $registryPath).BootExecute)
    $report.explicitBootCheckForC = @($report.bootExecuteAfter | Where-Object { $_ -match '(?i)autocheck\s+autochk\b.*C:' }).Count -gt 0
    $report.state = if ($report.explicitBootCheckForC) { 'boot-check-confirmed; repair-pending-restart' } else { 'scheduling-unconfirmed; manual-review-required' }
    $report.completedAt = [DateTime]::UtcNow.ToString('o')
    Save-Request
    [pscustomobject]@{state=$report.state; nativeExitCode=$report.nativeExitCode; explicitBootCheckForC=$report.explicitBootCheckForC; restartPerformed=$false; repairCompleted=$false} | ConvertTo-Json
    if (-not $report.explicitBootCheckForC) { exit 2 }
} catch {
    $report.state = 'request-failed; manual-review-required'
    $report.errorType = $_.Exception.GetType().Name
    Save-Request
    throw
} finally { $process.Dispose() }
