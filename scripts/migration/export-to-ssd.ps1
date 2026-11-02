<# Capture this machine's existing pilot directly to a new private SSD folder.
   No app/daemon is stopped. See DATA-RECOVERY.md for live consistency limits. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Destination,
    [switch]$IncludeImages,
    [switch]$SkipCodex,
    [switch]$SkipBrowserData,
    [string]$BrowserProfile = (Join-Path $env:LOCALAPPDATA 'Yandex\YandexBrowser\User Data\Default'),
    [string]$BrowserBucket = '616',
    [switch]$IncludeModelsAndOldApks,
    [switch]$AllowSameVolume,
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$target = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $target) { throw 'Destination must be a new private directory.' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $target) -PathType Container)) { throw 'Destination parent/SSD must already exist.' }
if ($target.StartsWith($root.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Choose a destination outside the checkout.' }
$sameVolume = [IO.Path]::GetPathRoot($target) -eq [IO.Path]::GetPathRoot($root)
if ($sameVolume -and -not $AllowSameVolume) { throw 'Only C: staging was selected. Choose the attached SSD, or explicitly -AllowSameVolume for a rehearsal.' }
if ($Plan) {
    Write-Output "Plan: capture source, host settings, pilot databases/volumes, route inputs/SQLite and essential private configuration into $target"
    Write-Output "Include Codex: $(-not $SkipCodex); include browser origin data: $(-not $SkipBrowserData); include images: $($IncludeImages.IsPresent); include models/old APKs: $($IncludeModelsAndOldApks.IsPresent)"
    Write-Output 'No files or Docker resources were changed.'
    return
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3.12+ is required.' }
& python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
New-Item -ItemType Directory -Path $target | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $target '/inheritance:r' '/grant:r' "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect destination. Use NTFS or a private encrypted destination.' }
function Invoke-Python([string]$Script, [string[]]$Arguments) {
    & python (Join-Path $PSScriptRoot $Script) @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Capture failed at $Script; incomplete output retained, no success receipt written." }
}
Push-Location $root
try {
    & (Join-Path $PSScriptRoot 'capture-host.ps1') -Destination (Join-Path $target 'host')
    $hostIssues = @(Get-Content -LiteralPath (Join-Path $target 'host/issues.json') -Raw | ConvertFrom-Json)
    $hostFailed = @($hostIssues | Where-Object { $_ -like 'Copy failed:*' -or $_ -like 'Registry export unavailable:*' })
    if ($hostFailed.Count -gt 0) { throw 'Some host configuration captures failed. Inspect host/issues.json before continuing.' }
    Invoke-Python -Script 'capture_workspace.py' -Arguments @((Join-Path $target 'source'))
    Invoke-Python -Script 'backup_data.py' -Arguments @((Join-Path $target 'data'))
    Invoke-Python -Script 'backup_verify.py' -Arguments @((Join-Path $target 'data'))
    Invoke-Python -Script 'backup_routes_essential.py' -Arguments @((Join-Path $target 'routes-essential'))
    Invoke-Python -Script 'backup_verify_selected.py' -Arguments @((Join-Path $target 'routes-essential'))
    Invoke-Python -Script 'backup_routes_sqlite.py' -Arguments @((Join-Path $target 'routes-sqlite'))
    $sqlite = Get-Content -LiteralPath (Join-Path $target 'routes-sqlite/manifest.json') -Raw | ConvertFrom-Json
    if (@($sqlite.entries | Where-Object { $_.error }).Count -gt 0) { throw 'Some route SQLite backups failed. Inspect their private manifest.' }
    $profile = if ($IncludeModelsAndOldApks) { 'all' } else { 'essential' }
    Invoke-Python -Script 'backup_selected_files.py' -Arguments @((Join-Path $target 'private-config'), '--profile', $profile)
    Invoke-Python -Script 'backup_verify_selected.py' -Arguments @((Join-Path $target 'private-config'))
    Invoke-Python -Script 'backup_development_records.py' -Arguments @((Join-Path $target 'development-records'))
    Invoke-Python -Script 'backup_verify_selected.py' -Arguments @((Join-Path $target 'development-records'))
    $browserCaptured = $false
    if (-not $SkipBrowserData) {
        if (Test-Path -LiteralPath (Join-Path $BrowserProfile 'File System') -PathType Container) {
            Invoke-Python -Script 'backup_browser_origin.py' -Arguments @('--profile', $BrowserProfile, '--bucket', $BrowserBucket, (Join-Path $target 'browser-origin'))
            $browserCaptured = $true
        } else { Write-Warning 'Original browser File System profile unavailable. Browser-only recordings have not been captured.' }
    }
    $codexWarnings = $false
    if (-not $SkipCodex) {
        Invoke-Python -Script 'backup_codex.py' -Arguments @((Join-Path $target 'codex'))
        $codexState = Get-Content -LiteralPath (Join-Path $target 'codex/verification.json') -Raw | ConvertFrom-Json
        $codexWarnings = -not $codexState.allSqliteHealthy
        if ($codexWarnings) { Write-Warning 'Codex database integrity warning: journals and damaged source were preserved; inspect the manifest before restore.' }
    }
    if ($IncludeImages) { & (Join-Path $PSScriptRoot 'save-running-images.ps1') -OutputDirectory (Join-Path $target 'images') }
    # This receipt records scope, not a claim of a coordinated cutover snapshot.
    @{
        SchemaVersion=1; CreatedAtUtc=[DateTime]::UtcNow.ToString('o'); Private=$true
        DifferentLogicalVolume=(-not $sameVolume); IncludeCodex=(-not $SkipCodex)
        IncludeImages=$IncludeImages.IsPresent; LocalProfile=$profile
        BrowserOriginCaptured=$browserCaptured
        CodexIntegrityWarnings=$codexWarnings
        ApplicationConsistentCutover=$false
        Limits='Live per-component snapshots. Review manifests/errors and Codex integrity status before erasing the source.'
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target 'CAPTURE-RECEIPT.json') -Encoding utf8
    Write-Output "Capture stages finished: $target. Review manifests and restore checks; retain original until acceptance."
} finally { Pop-Location }
