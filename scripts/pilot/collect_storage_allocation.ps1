# Finite, read-only Windows volume/VSS observations. No cleanup or system changes.
[CmdletBinding()]
param(
    [ValidateRange(1, 61)][int]$Samples = 31,
    [ValidateRange(60, 120)][int]$IntervalSeconds = 60
)
$ErrorActionPreference = 'Stop'
if (($Samples - 1) * $IntervalSeconds -gt 3600) {
    throw 'Observation window must not exceed one hour.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    [Console]::Error.WriteLine('Administrator required for VSS/volume reads. No collector/output started.')
    exit 2
}
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$base = Join-Path $workspace '.local-pilot'
$baseItem = Get-Item -LiteralPath $base
if ($baseItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Report root must not be a reparse point.'
}
$output = [IO.Path]::GetFullPath((Join-Path $base ('admin-storage-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss') + '-' + [Guid]::NewGuid().ToString('N'))))
if (-not $output.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Report directory escaped the intended workspace.'
}
[IO.Directory]::CreateDirectory($output) | Out-Null
$encoding = [Text.UTF8Encoding]::new($false)

function Read-NativeQuery([string]$Name, [string]$Executable, [string]$Arguments) {
    $query = [Diagnostics.Process]::new()
    $query.StartInfo = [Diagnostics.ProcessStartInfo]::new()
    $query.StartInfo.FileName = Join-Path ([Environment]::SystemDirectory) $Executable
    $query.StartInfo.Arguments = $Arguments
    $query.StartInfo.UseShellExecute = $false
    $query.StartInfo.CreateNoWindow = $true
    $query.StartInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $query.StartInfo.RedirectStandardOutput = $true
    $query.StartInfo.RedirectStandardError = $true
    $started = [DateTime]::UtcNow.ToString('o')
    try {
        $query.Start() | Out-Null
        $stdout = $query.StandardOutput.ReadToEndAsync()
        $stderr = $query.StandardError.ReadToEndAsync()
        if (-not $query.WaitForExit(10000)) {
            # This Process object owns only the query started above, never another PID.
            $query.Kill()
            $query.WaitForExit(2000) | Out-Null
            return @{ name = $Name; state = 'timeout'; startedAt = $started }
        }
        $text = $stdout.GetAwaiter().GetResult()
        $errorText = $stderr.GetAwaiter().GetResult()
        return @{
            name = $Name; state = 'returned'; exitCode = $query.ExitCode
            startedAt = $started; finishedAt = [DateTime]::UtcNow.ToString('o')
            stdout = $text.Substring(0, [Math]::Min(32768, $text.Length))
            stderr = $errorText.Substring(0, [Math]::Min(4096, $errorText.Length))
            truncated = ($text.Length -gt 32768 -or $errorText.Length -gt 4096)
        }
    } finally { $query.Dispose() }
}

$status = @{ state = 'running'; pid = $PID; startUtc = [DateTime]::UtcNow.ToString('o'); samplesWritten = 0; reportBytes = 0; administrator = $true; systemChangesPerformed = $false; samplesLimit = $Samples; intervalSeconds = $IntervalSeconds; reportDirectory = $output }
[IO.File]::WriteAllText((Join-Path $output 'status.json'), ($status | ConvertTo-Json), $encoding)
$status | ConvertTo-Json -Compress
try {
    for ($index = 0; $index -lt $Samples; $index++) {
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $free = (Get-PSDrive -Name C).Free
        if ($free -lt 512MB) { $status.state = 'stopped_low_disk'; break }
        $record = @{
            observedAt = [DateTime]::UtcNow.ToString('o'); sample = $index; freeDiskBytes = $free
            vss = Read-NativeQuery 'vss-shadowstorage' 'vssadmin.exe' 'list shadowstorage /for=C:'
            volume = Read-NativeQuery 'volume-diskfree' 'fsutil.exe' 'volume diskfree C:'
            systemChangesPerformed = $false
        }
        $json = $record | ConvertTo-Json -Depth 5
        $bytes = $encoding.GetByteCount($json)
        if ($bytes -gt 128KB -or $status.reportBytes + $bytes -gt 4MB) {
            $status.state = 'stopped_report_budget'; break
        }
        $destination = Join-Path $output ('sample-{0:D3}.json' -f $index)
        [IO.File]::WriteAllText(($destination + '.tmp'), $json, $encoding)
        [IO.File]::Move(($destination + '.tmp'), $destination)
        $status.samplesWritten = $index + 1
        $status.reportBytes += $bytes
        $status.lastSampleAt = $record.observedAt
        [IO.File]::WriteAllText((Join-Path $output 'status.json'), ($status | ConvertTo-Json), $encoding)
        if ($index -lt $Samples - 1) {
            $delay = [Math]::Max(0, $IntervalSeconds * 1000 - $timer.ElapsedMilliseconds)
            if ($delay -gt 0) { Start-Sleep -Milliseconds ([int]$delay) }
        }
    }
    if ($status.state -eq 'running') { $status.state = 'complete' }
} catch {
    $status.state = 'stopped_error'
    $status.errorType = $_.Exception.GetType().Name
    throw
} finally {
    $status.finishedAt = [DateTime]::UtcNow.ToString('o')
    [IO.File]::WriteAllText((Join-Path $output 'status.json'), ($status | ConvertTo-Json), $encoding)
    $status | ConvertTo-Json -Compress
}
if ($status.state -ne 'complete') { exit 2 }
