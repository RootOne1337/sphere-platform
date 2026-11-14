<# Plan is read-only. Export requires stopped emulators and a new directory on
   another physical disk. Nothing is stopped, reset, or restored by this script.
   Archives contain app data and credentials; protect the destination. #>
[CmdletBinding()]
param(
    [switch]$Export,
    [string]$Destination = '',
    [switch]$IncludeAvd,
    [switch]$IncludeRawLdVms,
    [string]$ConsolePath = 'C:\LDPlayer\LDPlayer9\ldconsole.exe',
    [string]$AvdDirectory = (Join-Path $env:USERPROFILE '.android\avd')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ConsolePath -PathType Leaf)) { throw 'LDPlayer ldconsole.exe not found.' }
$console = (Resolve-Path -LiteralPath $ConsolePath).Path
function Get-Instances {
    try { $lines = @(& $console list2 2>$null) } catch { throw 'LDPlayer list2 failed; no backup attempted.' }
    if ($LASTEXITCODE -ne 0) { throw 'LDPlayer list2 failed; no backup attempted.' }
    $result = @()
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -notmatch '^(\d+),(.*),(-?\d+),(-?\d+),([01]),(-?\d+),(-?\d+),(\d+),(\d+),(\d+)$') { throw 'Unrecognized LDPlayer list2 format; no backup attempted.' }
        $result += [pscustomobject]@{ index=[int]$Matches[1]; name=$Matches[2]; running=($Matches[5] -eq '1'); player_pid=[int]$Matches[6]; vm_pid=[int]$Matches[7] }
    }
    if (-not $result.Count) { throw 'No LDPlayer instances found; no backup attempted.' }
    if (@($result | Select-Object -ExpandProperty index -Unique).Count -ne $result.Count) { throw 'Duplicate LDPlayer index; no backup attempted.' }
    return $result
}
function Get-RunningEmulators {
    return @(Get-Process -ErrorAction Stop | Where-Object {
        $_.ProcessName -match '^(dnplayer|Ld9BoxHeadless|LdBoxHeadless|LdVBoxHeadless|Ld9VBoxHeadless)$' -or
        ($IncludeAvd -and $_.ProcessName -match '^(emulator|emulator64.*|qemu-system.*|studio64)$')
    })
}
function Assert-Offline {
    $current = @(Get-Instances)
    if (@($current | Where-Object running).Count -or @(Get-RunningEmulators).Count) { throw 'An emulator or its process is running. Close it manually, then retry; no stop command is issued.' }
    return $current
}
$initial = @(Get-Instances)
$runningCount = @($initial | Where-Object running).Count
$processCount = @(Get-RunningEmulators).Count
$vmPath = Join-Path (Split-Path -Parent $console) 'vms'
$vmBytes = 0L
if (Test-Path -LiteralPath $vmPath -PathType Container) {
    $vmFiles = @(Get-ChildItem -LiteralPath $vmPath -Force -Recurse)
    if ($IncludeRawLdVms -and @($vmFiles | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'LDPlayer vms tree contains links or reparse points; inventory them separately before export.' }
    $vmBytes = [int64](($vmFiles | Where-Object { -not $_.PSIsContainer } | Measure-Object Length -Sum).Sum)
} elseif ($IncludeRawLdVms) { throw 'LDPlayer vms directory not found.' }
$avdBytes = 0L; $avdFiles = @()
if ($IncludeAvd -and (Test-Path -LiteralPath $AvdDirectory -PathType Container)) {
    $avdFiles = @(Get-ChildItem -LiteralPath $AvdDirectory -Force -Recurse)
    if (@($avdFiles | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'AVD tree contains links or reparse points; inventory them separately before export.' }
    $avdBytes = [int64](($avdFiles | Where-Object { -not $_.PSIsContainer } | Measure-Object Length -Sum).Sum)
}
Write-Output "LDPlayer instances: $($initial.Count); list2 running: $runningCount; emulator processes: $processCount"
Write-Output "LDPlayer vms logical bytes: $vmBytes; selected AVD logical bytes: $avdBytes"
if (-not $Export) { Write-Output 'PLAN ONLY: no files copied and no emulator stopped. Export requires all selected emulators closed and a separate physical disk.'; return }
# Check this before destination validation or creation: never call backup live.
$offline = @(Assert-Offline)
if (-not $Destination) { throw 'Export requires -Destination on another physical disk.' }
$target = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $target) { throw 'Destination already exists; refusing overwrite.' }
$parent = Split-Path -Parent $target
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'Destination parent directory does not exist.' }
$parent = (Resolve-Path -LiteralPath $parent).Path
$cursor = Get-Item -LiteralPath $parent -Force
while ($cursor) {
    if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Destination path contains a link or reparse point.' }
    $cursor = $cursor.Parent
}
$root = [IO.Path]::GetPathRoot($parent)
if ($root -notmatch '^[A-Za-z]:\\$') { throw 'Destination must be a local drive with verifiable disk identity.' }
$destLetter = $root.Substring(0,1)
$destPart = @(Get-Partition -DriveLetter $destLetter -ErrorAction Stop)
if ($destPart.Count -ne 1) { throw 'Cannot uniquely identify destination disk.' }
foreach ($sourcePath in @($console,$AvdDirectory)) {
    if ($sourcePath -eq $AvdDirectory -and -not $IncludeAvd) { continue }
    $sourceRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($sourcePath))
    if ($sourceRoot -notmatch '^[A-Za-z]:\\$') { throw 'Cannot identify source disk.' }
    $sourcePart = @(Get-Partition -DriveLetter $sourceRoot.Substring(0,1) -ErrorAction Stop)
    if ($sourcePart.Count -ne 1 -or $sourcePart[0].DiskNumber -eq $destPart[0].DiskNumber) { throw 'Destination must be on a different Windows disk from emulator sources.' }
}
$volume = Get-Volume -DriveLetter $destLetter -ErrorAction Stop
if ($volume.FileSystem -notin @('NTFS','ReFS')) { throw 'Destination must support access controls (NTFS or ReFS); use an encrypted volume.' }
$neededBytes = $vmBytes + $avdBytes
if ($IncludeRawLdVms) { $neededBytes += $vmBytes }
if ($volume.SizeRemaining -lt [int64]($neededBytes * 1.1 + 5GB)) { throw 'Not enough free destination space for source size plus safety margin.' }
$null = @(Assert-Offline)
New-Item -ItemType Directory -Path $target -ErrorAction Stop | Out-Null
$acl = Get-Acl -LiteralPath $target
$acl.SetAccessRuleProtection($true,$false)
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
Set-Acl -LiteralPath $target -AclObject $acl
$artifacts = @()
foreach ($instance in $offline) {
    $current = @(Assert-Offline)
    if (-not @($current | Where-Object { $_.index -eq $instance.index -and $_.name -eq $instance.name }).Count) { throw 'LDPlayer inventory changed; export incomplete.' }
    $file = Join-Path $target ("ldplayer-index-{0}.ldbk" -f $instance.index)
    if (Test-Path -LiteralPath $file) { throw 'Backup target already exists.' }
    try { $null = @(& $console backup --index "$($instance.index)" --file $file 2>&1) } catch { throw 'LDPlayer backup failed; partial files retained.' }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-Item -LiteralPath $file).Length -le 0) { throw 'LDPlayer backup was not confirmed; partial files retained.' }
    $null = @(Assert-Offline)
    $artifacts += [pscustomobject]@{kind='ldplayer'; index=$instance.index; name=$instance.name; path=(Split-Path -Leaf $file); size=(Get-Item -LiteralPath $file).Length; sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()}
    Write-Output "Verified LDPlayer backup for index $($instance.index)."
}
function Copy-OfflineTree([string]$source, [string]$folder, [object[]]$items, [string]$kind) {
    $sourceRoot = (Resolve-Path -LiteralPath $source).Path.TrimEnd('\')
    $treeTarget = Join-Path $target $folder
    New-Item -ItemType Directory -Path $treeTarget | Out-Null
    $entries = @()
    foreach ($item in $items) {
        $null = @(Assert-Offline)
        $relative = $item.FullName.Substring($sourceRoot.Length).TrimStart('\')
        $out = Join-Path $treeTarget $relative
        if ($item.PSIsContainer) { New-Item -ItemType Directory -Path $out -Force | Out-Null; continue }
        $outParent = Split-Path -Parent $out
        if (-not (Test-Path -LiteralPath $outParent)) { New-Item -ItemType Directory -Path $outParent -Force | Out-Null }
        Copy-Item -LiteralPath $item.FullName -Destination $out -ErrorAction Stop
        $originalHash = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $copyHash = (Get-FileHash -LiteralPath $out -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($originalHash -ne $copyHash) { throw 'Source and copied file differ; export incomplete.' }
        $entries += [pscustomobject]@{kind=$kind; path=($folder + '/' + ($relative -replace '\\','/')); size=(Get-Item -LiteralPath $out).Length; sha256=$copyHash}
    }
    $null = @(Assert-Offline)
    return $entries
}
if ($IncludeAvd -and $avdFiles.Count) { $artifacts += @(Copy-OfflineTree $AvdDirectory 'android-avd' $avdFiles 'android-avd-file') }
if ($IncludeRawLdVms) { $artifacts += @(Copy-OfflineTree $vmPath 'ldplayer-vms' $vmFiles 'ldplayer-vms-file') }
$versionPath = Join-Path (Split-Path -Parent $console) 'dnplayer.exe'
$version = if (Test-Path -LiteralPath $versionPath -PathType Leaf) { (Get-Item -LiteralPath $versionPath).VersionInfo.FileVersion } else { (Get-Item -LiteralPath $console).VersionInfo.FileVersion }
$manifest = [pscustomobject]@{version=1; created_utc=[DateTime]::UtcNow.ToString('o'); console_version=$version; avd_included=[bool]$IncludeAvd; raw_ld_vms_included=[bool]$IncludeRawLdVms; artifacts=$artifacts; note='Backup files hashed; full restore and guest identity verification still required.'}
$manifestPath = Join-Path $target 'manifest.json'
if (Test-Path -LiteralPath $manifestPath) { throw 'Manifest already exists.' }
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
Write-Output 'Export and hashes completed. Protect this backup and test restoration before reinstalling Windows.'
