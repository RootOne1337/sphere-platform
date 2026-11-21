<# Manage an existing installation created by new-install.ps1. No volumes are
   deleted, no images are built, and no absent container is recreated. A partial
   bootstrap needs investigation rather than an automatic retry against data. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallDirectory,
    [ValidateSet('Status','Start','Stop')][string]$Action = 'Status'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$base = (Resolve-Path -LiteralPath (Join-Path $root '.local-pilot/new-installs')).Path
$dir = (Resolve-Path -LiteralPath $InstallDirectory).Path
if (-not [string]::Equals((Split-Path -Parent $dir),$base,[StringComparison]::OrdinalIgnoreCase)) { throw 'Installation directory must be a direct child of this checkout private new-installs directory.' }
$project = Split-Path -Leaf $dir
if ($project -match '^sphere-new-[0-9a-f]{12}$') { $restore = $false }
elseif ($project -match '^migration-[0-9a-f]{12}$') { $restore = $true }
else { throw 'Invalid installation project name.' }
$envPath = Join-Path $dir 'install.env'
$overlay = Join-Path $dir 'private-overlay.yml'
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf) -or -not (Test-Path -LiteralPath $overlay -PathType Leaf)) { throw 'Installation private configuration is incomplete.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker is required.' }
$raw = @(& docker ps -a --filter "label=com.docker.compose.project=$project" --format '{{.Names}}')
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect project containers.' }
$services = @('postgres','redis','minio','backend','frontend','nginx')
if (-not $restore) { $services += 'n8n' }
$seen = @{}
foreach ($container in $raw) {
    $labelJson = & docker inspect --format '{{json .Config.Labels}}' $container
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect project labels.' }
    $labels = $labelJson | ConvertFrom-Json
    $service = $labels.'com.docker.compose.service'
    if ($labels.'com.docker.compose.project' -ne $project -or $container -ne "${project}-${service}-1" -or $services -notcontains $service -or $seen.ContainsKey($service)) { throw 'Unexpected project container or service; refusing to manage it.' }
    $seen[$service] = $true
}
if ($Action -ne 'Status' -and $seen.Count -eq 0) { throw 'No existing project containers; refusing to create or adopt anything.' }
if ($Action -eq 'Start') {
    foreach ($service in $services) { if (-not $seen.ContainsKey($service)) { throw "Missing existing container $service. Bootstrap is incomplete; inspect it before recovery." } }
    $volumes = @(& docker volume ls -q --filter "label=com.docker.compose.project=$project")
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect project volumes.' }
    $required = @('postgres_data','redis_data','minio_data','ota_data','device_logs')
    if (-not $restore) { $required += 'n8n_data' }
    foreach ($suffix in $required) { if ($volumes -notcontains "${project}_${suffix}") { throw "Missing project volume $suffix; refusing to start." } }
}
$files = @('docker-compose.yml','docker-compose.full.yml','docker-compose.local-pilot.yml') | ForEach-Object { Join-Path $root $_ }
$baseArgs = @('compose','--project-directory',$root,'--env-file',$envPath,'-p',$project,'-f',$files[0],'-f',$files[1],'-f',$files[2],'-f',$overlay)
$names = @($files | ForEach-Object { [regex]::Matches((Get-Content -Raw -LiteralPath $_), '\$\{([A-Za-z_][A-Za-z_0-9]*)') | ForEach-Object { $_.Groups[1].Value } } | Select-Object -Unique)
$names += @('COMPOSE_FILE','COMPOSE_PROJECT_NAME','COMPOSE_PROFILES','COMPOSE_ENV_FILES')
$saved = @{}
foreach ($name in ($names | Select-Object -Unique)) { $saved[$name] = [Environment]::GetEnvironmentVariable($name,'Process'); [Environment]::SetEnvironmentVariable($name,$null,'Process') }
try {
    Write-Output "Project: $project; action: $Action"
    if ($Action -eq 'Status') { $cmd = @('ps','--all') }
    elseif ($Action -eq 'Start') { $cmd = @('start','--wait','--wait-timeout','300') + $services }
    else { $cmd = @('stop') + @($services | Where-Object { $seen.ContainsKey($_) }) }
    & docker @baseArgs @cmd
    if ($LASTEXITCODE -ne 0) { throw "Compose $Action failed. Existing volumes were retained." }
    if ($Action -eq 'Start') { Write-Output 'Existing containers started; verify the local login and integrations you need.' }
    elseif ($Action -eq 'Stop') { Write-Output 'Existing containers stopped; volumes, images and private settings retained.' }
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
}
