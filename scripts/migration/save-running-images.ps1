<# Export the exact currently running pilot images to a NEW private directory.
   No container is changed. Archives can contain sensitive information.
   This is not a database or volume backup. Requires substantial free disk space. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [int64]$MinimumFreeGiB = 12
)
$ErrorActionPreference = 'Stop'
if ($MinimumFreeGiB -lt 12) { throw 'MinimumFreeGiB must be at least 12.' }
$target = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $target) { throw 'Output directory already exists; refusing to overwrite.' }
$parent = Split-Path -Parent $target
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'Parent directory does not exist.' }
$drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($parent).Substring(0,1))
if ($drive.Free -lt (($MinimumFreeGiB + 10) * 1GB)) { throw 'Need 10 GiB working headroom in addition to minimum free space.' }
$names = @('sphere-pilot-20260911-postgres-1','sphere-pilot-20260911-redis-1',
 'sphere-pilot-20260911-minio-1','sphere-pilot-20260911-n8n-1',
 'sphere-pilot-20260911-backend-1','sphere-pilot-20260911-frontend-1',
 'sphere-pilot-20260911-nginx-1','sphere-pilot-20260911-public-gateway-1',
 'sphere-review-20261002-review-ui-1','sphere-review-20261002-review-gateway-1',
 'sphere-observability-20260930-prometheus-1','sphere-observability-20260930-grafana-1',
 'sphere-tuna-canary','sphere-tunnel')
$inventory = @()
foreach ($name in $names) {
    $raw = & docker inspect --format '{{.State.Status}}|{{.Image}}|{{.Config.Image}}' $name 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { throw "Cannot inspect $name" }
    $fields = $raw -split '\|',3
    if ($fields[0] -ne 'running') { throw "Not running: $name" }
    $reference = $fields[2]
    if ($reference.Contains('@sha256:')) {
        $reference = & docker image inspect --format '{{index .RepoTags 0}}' $fields[1] 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $reference -or $reference -eq '<none>:<none>') { throw "No saved tag for $name" }
    }
    $tagId = & docker image inspect --format '{{.Id}}' $reference 2>$null
    if ($LASTEXITCODE -ne 0 -or $tagId -ne $fields[1]) { throw "Image reference no longer matches container: $name" }
    $inventory += [pscustomobject]@{ container=$name; image_id=$fields[1]; reference=$reference; runtime_reference=$fields[2] }
}
New-Item -ItemType Directory -Path $target | Out-Null
$archive = Join-Path $target 'running-images.tar'
$refs = @($inventory | ForEach-Object { $_.reference } | Select-Object -Unique)
& docker image save --output $archive @refs
if ($LASTEXITCODE -ne 0) { throw 'Image export failed; incomplete directory must not be treated as a backup.' }
if ((Get-PSDrive -Name $drive.Name).Free -lt ($MinimumFreeGiB * 1GB)) { throw 'Disk free space fell below minimum; export needs operator review.' }
foreach ($entry in $inventory) {
    $actual = & docker inspect --format '{{.Image}}' $entry.container 2>$null
    if ($LASTEXITCODE -ne 0 -or $actual -ne $entry.image_id) { throw "Container image changed during export: $($entry.container)" }
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
$record = [pscustomobject]@{version=1; created_utc=[DateTime]::UtcNow.ToString('o'); archive='running-images.tar'; sha256=$hash; size=(Get-Item -LiteralPath $archive).Length; containers=$inventory}
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $target 'manifest.json') -Encoding UTF8
Write-Output "Export complete. Private directory: $target"
Write-Output "SHA256: $hash"
