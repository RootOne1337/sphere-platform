# Finite, named ETW recording plus volume/VSS/process metadata. No cleanup.
[CmdletBinding()]
param(
    [ValidateRange(30, 1800)][int]$DurationSeconds = 600,
    [ValidateRange(5, 60)][int]$IntervalSeconds = 10,
    [ValidateRange(32, 1024)][int]$StopAfterDropMiB = 128
)
$ErrorActionPreference = 'Stop'
if ($IntervalSeconds -gt $DurationSeconds) { throw 'Interval exceeds observation duration.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    [Console]::Error.WriteLine('Administrator required for named kernel ETW/VSS capture. Nothing started.')
    exit 2
}
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$base = Join-Path $workspace '.local-pilot'
if ((Get-Item -LiteralPath $base).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Report root must not be a reparse point.'
}
$profile = Join-Path $PSScriptRoot 'disk-writer.wprp'
$xml = [xml][IO.File]::ReadAllText($profile)
$profiles = $xml.WindowsPerformanceRecorder.Profiles
if (@($profiles.Profile).Count -ne 1 -or $profiles.Profile.LoggingMode -ne 'Memory' -or
    @($profiles.SystemCollector).Count -ne 1 -or $profiles.SystemCollector.BufferSize.Value -ne '1024' -or
    $profiles.SystemCollector.Buffers.Value -ne '128' -or $profiles.EventCollector) {
    throw 'Profile must retain the reviewed single 128 MiB memory collector.'
}
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss') + '-' + [Guid]::NewGuid().ToString('N')
$instance = 'SphereDiskWriter-' + $stamp
$output = [IO.Path]::GetFullPath((Join-Path $base ('disk-writer-' + $stamp)))
if (-not $output.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Report directory escaped workspace.'
}
[IO.Directory]::CreateDirectory($output) | Out-Null
$encoding = [Text.UTF8Encoding]::new($false)
function Invoke-Recorder([string]$Arguments, [int]$TimeoutMilliseconds = 10000) {
    $native = [Diagnostics.Process]::new()
    $native.StartInfo = [Diagnostics.ProcessStartInfo]::new()
    $native.StartInfo.FileName = Join-Path ([Environment]::SystemDirectory) 'wpr.exe'
    $native.StartInfo.Arguments = $Arguments
    $native.StartInfo.UseShellExecute = $false
    $native.StartInfo.CreateNoWindow = $true
    $native.StartInfo.RedirectStandardOutput = $true
    $native.StartInfo.RedirectStandardError = $true
    try {
        $native.Start() | Out-Null
        $stdout = $native.StandardOutput.ReadToEndAsync()
        $stderr = $native.StandardError.ReadToEndAsync()
        if (-not $native.WaitForExit($TimeoutMilliseconds)) {
            $native.Kill()
            $native.WaitForExit(2000) | Out-Null
            return @{ state='timeout' }
        }
        $text = $stdout.GetAwaiter().GetResult()
        $errorText = $stderr.GetAwaiter().GetResult()
        return @{ state='returned'; exitCode=$native.ExitCode;
            stdout=$text.Substring(0, [Math]::Min(16384, $text.Length));
            stderr=$errorText.Substring(0, [Math]::Min(4096, $errorText.Length));
            truncated=($text.Length -gt 16384 -or $errorText.Length -gt 4096) }
    } finally { $native.Dispose() }
}
function Save-Status {
    $path = Join-Path $output 'status.json'
    [IO.File]::WriteAllText(($path + '.tmp'), ($status | ConvertTo-Json -Depth 8), $encoding)
    # Windows PowerShell 5.1 coerces a null backup path to an invalid empty
    # string for this overload. Keep one bounded owned previous-status file.
    if (Test-Path -LiteralPath $path) { [IO.File]::Replace(($path + '.tmp'), $path, (Join-Path $output 'status.previous.json')) }
    else { [IO.File]::Move(($path + '.tmp'), $path) }
}
function Convert-VssSnapshot([object]$Storage) {
    # CIM references otherwise serialize their entire class/property graph,
    # inflating every sample. Retain only stable IDs and exact byte counters.
    $volume = $Storage.Volume.CimInstanceProperties['DeviceID'].Value
    $diffVolume = $Storage.DiffVolume.CimInstanceProperties['DeviceID'].Value
    if (-not $volume -or -not $diffVolume -or $null -eq $Storage.UsedSpace -or
        $null -eq $Storage.AllocatedSpace -or $null -eq $Storage.MaxSpace) {
        throw 'Incomplete VSS observation; do not substitute zero.'
    }
    return [pscustomobject]@{ Volume=[string]$volume; DiffVolume=[string]$diffVolume;
        UsedSpace=[long]$Storage.UsedSpace; AllocatedSpace=[long]$Storage.AllocatedSpace;
        MaxSpace=[long]$Storage.MaxSpace }
}
$status = @{ state='preflight'; pid=$PID; instance=$instance; startUtc=[DateTime]::UtcNow.ToString('o');
    durationSeconds=$DurationSeconds; intervalSeconds=$IntervalSeconds; samplesWritten=0; reportBytes=0;
    bufferPayloadMiB=128; administrator=$true; fileMode=$false; reportDirectory=$output;
    cleanupPerformed=$false; autostartConfigured=$false; traceStarted=$false }
$owned = $false
$startAttempted = $false
$samples = [IO.StreamWriter]::new((Join-Path $output 'samples.jsonl'), $false, $encoding)
try {
    $preflight = Invoke-Recorder '-status'
    $status.preflight = $preflight
    if ($preflight.state -ne 'returned' -or $preflight.exitCode -ne 0 -or
        $preflight.stdout -notmatch 'WPR is not recording') {
        throw 'Existing/unknown WPR session: refuse to disturb another recording.'
    }
    $firstFree = [IO.DriveInfo]::new('C:\').AvailableFreeSpace
    if ($firstFree -lt 20GB) { throw 'Disk headroom below 20 GiB; no trace started.' }
    $status.state = 'starting'
    Save-Status
    $startAttempted = $true
    $start = Invoke-Recorder ('-start "' + $profile + '!SphereDiskWriter" -instancename ' + $instance) 30000
    $status.startResult = $start
    if ($start.state -ne 'returned' -or $start.exitCode -ne 0) { throw 'Named ETW start failed or is unknown.' }
    $owned = $true
    $status.traceStarted = $true
    $status.state = 'recording'
    Save-Status
    $status | ConvertTo-Json -Compress -Depth 5
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $DurationSeconds) {
        $cycle = [Diagnostics.Stopwatch]::StartNew()
        $os = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 5
        $free = [IO.DriveInfo]::new('C:\').AvailableFreeSpace
        $top = @(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -OperationTimeoutSec 5 |
            Where-Object { $_.Name -notin @('_Total', 'Idle') } |
            Sort-Object IOWriteBytesPersec -Descending | Select-Object -First 32 |
            Select-Object Name, IDProcess, IOWriteBytesPersec, IOWriteOperationsPersec, PrivateBytes)
        $vss = $null; $vssError = $null
        try { $vss = @(Get-CimInstance Win32_ShadowStorage -OperationTimeoutSec 5 | ForEach-Object { Convert-VssSnapshot $_ }) }
        catch { $vssError = $_.Exception.GetType().Name }
        $record = @{ observedAt=[DateTime]::UtcNow.ToString('o'); sample=$status.samplesWritten;
            freeDiskBytes=$free; availableRamBytes=([long]$os.FreePhysicalMemory * 1024);
            vss=$vss; vssError=$vssError; topProcessIo=$top;
            processIoIncludesNonFileIo=$true; traceStatus=(Invoke-Recorder ('-status -instancename ' + $instance)) }
        $json = $record | ConvertTo-Json -Depth 8 -Compress
        $bytes = $encoding.GetByteCount($json) + 1
        if ($bytes -gt 128KB -or $status.reportBytes + $bytes -gt 8MB) { $status.exitReason='metadata_budget'; break }
        $samples.WriteLine($json); $samples.Flush()
        $status.samplesWritten++; $status.reportBytes += $bytes
        $status.lastSampleAt = $record.observedAt
        $status.freeDiskBytes = $free; $status.observedFreeDropBytes = $firstFree - $free
        Save-Status
        if ($free -lt 20GB -or $record.availableRamBytes -lt 4GB) { $status.exitReason='resource_headroom'; break }
        if ($timer.Elapsed.TotalSeconds -ge 30 -and $firstFree - $free -ge $StopAfterDropMiB * 1MB) {
            $status.exitReason='free_drop_trigger'; break
        }
        $delay = [Math]::Min($IntervalSeconds * 1000 - $cycle.ElapsedMilliseconds,
            $DurationSeconds * 1000 - $timer.ElapsedMilliseconds)
        if ($delay -gt 0) { Start-Sleep -Milliseconds ([int]$delay) }
    }
    if (-not $status.exitReason) { $status.exitReason='duration_limit' }
    $status.state = 'saving_trace'
} catch {
    $status.state = 'failed'
    $status.errorType = $_.Exception.GetType().Name
    $status.error = $_.Exception.Message.Substring(0, [Math]::Min(1024, $_.Exception.Message.Length))
} finally {
    $samples.Dispose()
    if ($owned) {
        $trace = Join-Path $output 'disk-writer.etl'
        $stop = Invoke-Recorder ('-stop "' + $trace + '" "Sphere bounded disk writer capture" -skipPdbGen -compress -instancename ' + $instance) 120000
        $status.stopResult = $stop
        if ($stop.state -eq 'returned' -and $stop.exitCode -eq 0 -and (Test-Path -LiteralPath $trace)) {
            $status.traceBytes = (Get-Item -LiteralPath $trace).Length
            if ($status.state -eq 'saving_trace') { $status.state='complete' }
        } else { $status.state='trace_save_failed' }
    }
    # Any cancellation is restricted to our fresh unique named instance; never
    # issue global cancel/stop even if start/stop had an unknown native outcome.
    if ($startAttempted -and $status.state -ne 'complete') {
        $status.cancelOwnInstance = Invoke-Recorder ('-cancel -instancename ' + $instance)
    }
    $status.finishedAt = [DateTime]::UtcNow.ToString('o')
    Save-Status
    $status | ConvertTo-Json -Compress -Depth 5
}
if ($status.state -ne 'complete') { exit 2 }
