<#$
.SYNOPSIS
Read-only migration preflight. Does not start, stop, import, or restore anything.
.DESCRIPTION
Reports tool versions, selected container states and image IDs, and HTTP status of
loopback endpoints. It deliberately does not inspect environment variables, bind
sources, logs, compose configuration, database contents, or secrets. A successful
run is not proof that backups exist or can be restored.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$failed = $false
function Check-Command([string]$name, [string[]]$arguments) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Output "MISSING: $name"
        $script:failed = $true
        return
    }
    & $name @arguments
    if ($LASTEXITCODE -ne 0) { Write-Output "FAILED: $name"; $script:failed = $true }
}
Write-Output '=== Tool versions ==='
Check-Command 'git' @('--version')
Check-Command 'docker' @('version', '--format', 'Client {{.Client.Version}}; Server {{.Server.Version}}')
Check-Command 'docker' @('compose', 'version', '--short')
if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Output '=== Source revision ==='
    & git -C (Join-Path $PSScriptRoot '../..') rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { $failed = $true }
}
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Output '=== Selected containers (absence is reported) ==='
    $names = @('sphere-pilot-20260911-postgres-1','sphere-pilot-20260911-redis-1',
        'sphere-pilot-20260911-minio-1','sphere-pilot-20260911-n8n-1',
        'sphere-pilot-20260911-backend-1','sphere-pilot-20260911-frontend-1',
        'sphere-pilot-20260911-nginx-1','sphere-pilot-20260911-public-gateway-1',
        'sphere-review-20261002-review-ui-1','sphere-review-20261002-review-gateway-1',
        'sphere-observability-20260930-prometheus-1','sphere-observability-20260930-grafana-1',
        'sphere-tuna-canary','sphere-tunnel')
    foreach ($name in $names) {
        $out = & docker inspect --format '{{.Name}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} image={{.Image}}' $name 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Output $out } else { Write-Output "ABSENT OR UNAVAILABLE: $name" }
    }
}
Write-Output '=== Local HTTP status (no response bodies) ==='
foreach ($url in @('http://127.0.0.1:18080/api/v1/health/readyz','http://127.0.0.1:3015/api/v1/health/readyz','http://127.0.0.1:3015/login')) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4 -MaximumRedirection 0 -ErrorAction Stop
        Write-Output "$url HTTP $($response.StatusCode)"
    } catch { Write-Output "$url unavailable or non-2xx" }
}
Write-Output 'Preflight is observational only; verify backups and a separate restore before reinstalling.'
if ($failed) { exit 1 }
