# Read Windows repair readiness. Optional Scan queues NTFS defects; no repair/reboot.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [switch]$ScanVolume
)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$base = Join-Path $workspace '.local-pilot'
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $output.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output must be inside this project .local-pilot.'
}
$ancestor = $output
while ($ancestor.Length -ge $base.Length) {
    $item = Get-Item -LiteralPath $ancestor
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse output path rejected.' }
    if ($ancestor -eq $base) { break }
    $ancestor = [IO.Path]::GetDirectoryName($ancestor)
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$encoding = [Text.UTF8Encoding]::new($false)
$report = [ordered]@{
    schemaVersion = 1; startedAt = [DateTime]::UtcNow.ToString('o'); state = 'collecting'
    pid = $PID; administrator = $administrator; requestedDrive = 'C'
    repairPerformed = $false; rebootPerformed = $false; servicesStopped = $false
    volumeScanRequested = [bool]$ScanVolume; scanMayQueueOfflineDefects = [bool]$ScanVolume
    errors = @()
}
function Save-Report {
    $json = $report | ConvertTo-Json -Depth 8
    if ($encoding.GetByteCount($json) -gt 256KB) { throw 'Report budget exceeded.' }
    [IO.File]::WriteAllText((Join-Path $output 'host-diagnostics.private.json'), $json, $encoding)
}
function Get-Observation([string]$Name, [scriptblock]$Query) {
    try {
        $value = & $Query
        if ($null -eq $value -or ($value -is [string] -and [string]::IsNullOrWhiteSpace($value))) {
            $report.errors += @{name=$Name; errorType='UnavailableObservation'; message='Query returned no measurement.'}
        } else { $report[$Name] = $value }
    }
    catch { $report.errors += @{name=$Name; errorType=$_.Exception.GetType().Name; message=$_.Exception.Message.Substring(0,[Math]::Min(512,$_.Exception.Message.Length))} }
    Save-Report
}
function Read-Native([string]$Executable, [string]$Arguments) {
    $process = [Diagnostics.Process]::new()
    $process.StartInfo.FileName = Join-Path ([Environment]::SystemDirectory) $Executable
    $process.StartInfo.Arguments = $Arguments
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    try {
        $process.Start() | Out-Null
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(15000)) {
            $process.Kill()
            return @{state='query-timeout'; executable=$Executable}
        }
        $text = $stdout.GetAwaiter().GetResult()
        $errorText = $stderr.GetAwaiter().GetResult()
        return @{state='returned'; exitCode=$process.ExitCode; stdout=$text.Substring(0,[Math]::Min(32768,$text.Length)); stderr=$errorText.Substring(0,[Math]::Min(1024,$errorText.Length)); truncated=($text.Length -gt 32768 -or $errorText.Length -gt 1024)}
    } finally { $process.Dispose() }
}
Save-Report
Get-Observation 'volumeBefore' { Get-Volume -DriveLetter C | Select-Object DriveLetter,FileSystemType,HealthStatus,OperationalStatus,SizeRemaining,Size }
Get-Observation 'physicalDisk' { Get-PhysicalDisk | Select-Object FriendlyName,HealthStatus,OperationalStatus,Size,BusType }
Get-Observation 'reliability' { Get-PhysicalDisk | Get-StorageReliabilityCounter -ErrorAction Stop | Select-Object DeviceId,Temperature,TemperatureMax,Wear,PowerOnHours,ReadErrorsTotal,ReadErrorsUncorrected,WriteErrorsTotal,WriteErrorsUncorrected }
Get-Observation 'memoryModules' { Get-CimInstance Win32_PhysicalMemory | Select-Object BankLabel,Capacity,Speed,ConfiguredClockSpeed }
Get-Observation 'os' { Get-CimInstance Win32_OperatingSystem | Select-Object Version,BuildNumber,LastBootUpTime,FreePhysicalMemory,TotalVisibleMemorySize }
Get-Observation 'memory' {
    Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory |
        Select-Object AvailableMBytes,CommittedBytes,CommitLimit,PoolNonpagedBytes,PoolPagedBytes
}
Get-Observation 'processMemory' {
    Get-Process | Sort-Object PrivateMemorySize64 -Descending | Select-Object -First 16 |
        ForEach-Object {
            $started = $null
            try { $started = $_.StartTime.ToUniversalTime().ToString('o') } catch { }
            [pscustomobject]@{pid=$_.Id; name=$_.Name; startedAt=$started; privateBytes=$_.PrivateMemorySize64; workingSetBytes=$_.WorkingSet64}
        }
}
Get-Observation 'systemEvents' {
    Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddDays(-7)} |
        Where-Object { ($_.ProviderName -match 'Ntfs|^disk$|storahci|stornvme|WHEA|volmgr|MemoryDiagnostics') -and $_.Level -le 3 } |
        Select-Object -First 32 TimeCreated,ProviderName,Id,RecordId,@{Name='Message';Expression={$_.Message.Substring(0,[Math]::Min(1100,$_.Message.Length))}}
}
Get-Observation 'priorRepairLogs' {
    Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddDays(-7)} |
        Where-Object {$_.ProviderName -match 'Wininit|Chkdsk'} |
        Select-Object -First 4 TimeCreated,ProviderName,Id,RecordId,@{Name='Message';Expression={$_.Message.Substring(0,[Math]::Min(8192,$_.Message.Length))}}
}
if ($administrator) {
    Get-Observation 'comHosts' {
        @(Get-CimInstance Win32_Process -Filter "Name='dllhost.exe'" | ForEach-Object {
            $appId = $null
            $registration = $null
            if ($_.CommandLine -match '\{[a-fA-F0-9-]{36}\}') {
                $appId = $Matches[0]
                $key = Get-Item -LiteralPath ('Registry::HKEY_CLASSES_ROOT\AppID\' + $appId) -ErrorAction SilentlyContinue
                if ($key) { $registration = $key.GetValue('') }
            }
            [pscustomobject]@{pid=$_.ProcessId; parentPid=$_.ParentProcessId; createdAt=$_.CreationDate; appId=$appId; registration=$registration; commandLineAvailable=[bool]$_.CommandLine}
        })
    }
    Get-Observation 'bootExecute' { (Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager').BootExecute }
    Get-Observation 'dirtyQuery' { Read-Native 'fsutil.exe' 'dirty query C:' }
    Get-Observation 'diskfree' { Read-Native 'fsutil.exe' 'volume diskfree C:' }
    Get-Observation 'shadowstorage' { Read-Native 'vssadmin.exe' 'list shadowstorage /for=C:' }
    # Isolate the known intermittently unresponsive VSS WMI provider. A native
    # query deadline owns only this child; it never kills a volume scan/provider.
    Get-Observation 'shadowStorageExact' {
        $query = Read-Native 'WindowsPowerShell\v1.0\powershell.exe' '-NoProfile -NonInteractive -Command "$ErrorActionPreference=''Stop''; Get-CimInstance -ClassName Win32_ShadowStorage -OperationTimeoutSec 10 | Select-Object Volume,DiffVolume,UsedSpace,AllocatedSpace,MaxSpace | ConvertTo-Json -Depth 4 -Compress"'
        if ($query.state -ne 'returned' -or $query.exitCode -ne 0 -or $query.truncated) {
            throw 'Exact VSS counters unavailable within the bounded query.'
        }
        $query.stdout | ConvertFrom-Json
    }
    Get-Observation 'bitlocker' { Get-BitLockerVolume -MountPoint C: | Select-Object MountPoint,VolumeStatus,ProtectionStatus,EncryptionMethod,LockStatus }
    if ($ScanVolume) {
        $report.state = 'ntfs-scan-running'
        $report.scanStartedAt = [DateTime]::UtcNow.ToString('o')
        Save-Report
        # Microsoft's Scan action reports defects and queues them for offline repair.
        # Never use SpotFix/OfflineScanAndFix here; never interrupt a running scan.
        Get-Observation 'ntfsScanResult' { Repair-Volume -DriveLetter C -Scan | Out-String }
        $report.scanFinishedAt = [DateTime]::UtcNow.ToString('o')
    }
    Get-Observation 'volumeAfter' { Get-Volume -DriveLetter C | Select-Object DriveLetter,FileSystemType,HealthStatus,OperationalStatus,SizeRemaining,Size }
    $report.state = 'diagnostics-complete'
} else {
    $report.state = 'administrator-required; repair-not-started'
}
$report.completedAt = [DateTime]::UtcNow.ToString('o')
Save-Report
[pscustomobject]@{state=$report.state; outputDirectory=$output; administrator=$administrator; errorCount=$report.errors.Count; repairPerformed=$false; rebootPerformed=$false} | ConvertTo-Json -Compress
