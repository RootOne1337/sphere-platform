<# Create an isolated NEW local pilot. Plan is the default and does not modify
   files or Docker. New never adopts an existing project, config or volume.
   This creates fresh identity/data; it does not restore an old installation. #>
[CmdletBinding()]
param(
    [ValidateSet('Plan','New','Restore')][string]$Mode = 'Plan',
    [string]$Snapshot = '',
    [ValidateRange(1024,65535)][int]$GatewayPort = 28080,
    [ValidateRange(1024,65535)][int]$N8nPort = 25678,
    [ValidateRange(1024,65535)][int]$S3Port = 29000,
    [ValidateRange(1024,65535)][int]$S3ConsolePort = 29001,
    [string]$AdminEmail = 'admin@example.com',
    [string]$BackendImage = '',
    [string]$FrontendImage = ''
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$prefix = if ($Mode -eq 'Restore') { 'migration-' } else { 'sphere-new-' }
$project = $prefix + [guid]::NewGuid().ToString('N').Substring(0,12)
$dir = Join-Path $root ".local-pilot/new-installs/$project"
$ports = @($GatewayPort,$N8nPort,$S3Port,$S3ConsolePort)
if (@($ports | Select-Object -Unique).Count -ne 4) { throw 'Ports must be distinct.' }
if ([bool]$BackendImage -ne [bool]$FrontendImage) { throw 'Specify both BackendImage and FrontendImage, or neither.' }
try { $null = [System.Net.Mail.MailAddress]::new($AdminEmail) } catch { throw 'Invalid administrator email.' }
if ($Mode -eq 'Plan') { Write-Output 'Plan only: New will choose a different random project and private directory.' }
else { Write-Output "Mode: $Mode; isolated project: $project"; Write-Output "Private configuration: $dir" }
Write-Output "Loopback ports: gateway=$GatewayPort n8n=$N8nPort S3=$S3Port console=$S3ConsolePort"
if ($Mode -eq 'Plan') { Write-Output 'No changes made. Use -Mode New to create a new empty local pilot.'; return }
if ($Mode -eq 'Restore' -and (-not $Snapshot -or -not (Test-Path -LiteralPath $Snapshot -PathType Container))) { throw 'Restore requires -Snapshot pointing to a verified data snapshot directory.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker is required.' }
$composeVersion = $null
try { $composeLines = @(& docker compose version --short 2>$null) } catch { throw 'Docker Compose 2.24.4 or newer is required; install or update Docker Desktop.' }
if ($LASTEXITCODE -ne 0) { throw 'Cannot determine Docker Compose version; version 2.24.4 or newer is required.' }
if ($composeLines.Count -ne 1) { throw 'Cannot determine Docker Compose version; version 2.24.4 or newer is required.' }
$composeVersion = $composeLines[0]
if (-not ($composeVersion -match '^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$')) { throw 'Cannot determine Docker Compose version; version 2.24.4 or newer is required.' }
$version = [version]::new([int]$Matches[1],[int]$Matches[2],[int]$Matches[3])
if ($version -lt [version]'2.24.4') { throw 'Docker Compose 2.24.4 or newer is required for !override; update Docker Desktop.' }
if ($Mode -eq 'Restore') {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Restore requires Python 3.12 or newer available as python on PATH.' }
    try { $pythonLines = @(& python -c 'import sys; print(sys.version_info.major,sys.version_info.minor)' 2>$null) } catch { throw 'Restore requires a working Python 3.12 or newer available as python on PATH.' }
    if ($LASTEXITCODE -ne 0) { throw 'Restore requires Python 3.12 or newer available as python on PATH.' }
    if ($pythonLines.Count -ne 1) { throw 'Restore requires Python 3.12 or newer available as python on PATH.' }
    $pythonVersion = $pythonLines[0]
    if (-not ($pythonVersion -match '^(\d+)\s+(\d+)$')) { throw 'Restore requires Python 3.12 or newer available as python on PATH.' }
    if ([version]::new([int]$Matches[1],[int]$Matches[2]) -lt [version]'3.12') { throw 'Restore requires Python 3.12 or newer available as python on PATH.' }
}
& docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is unavailable.' }
$drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($root).Substring(0,1))
$minimumStart = if ($BackendImage) { 14GB } else { 20GB }
if ($drive.Free -lt $minimumStart) { throw 'Insufficient free workspace above the 12 GiB reserve.' }
if ($BackendImage) {
    foreach ($reference in @($BackendImage,$FrontendImage)) {
        $imageId = & docker image inspect --format '{{.Id}}' $reference
        if ($LASTEXITCODE -ne 0 -or $imageId -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Cannot verify a requested local image.' }
    }
}
foreach ($p in $ports) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$p)
    try { $listener.Start() } catch { throw "Loopback port $p is unavailable." } finally { $listener.Stop() }
}
$existing = & docker ps -aq --filter "label=com.docker.compose.project=$project"
if ($LASTEXITCODE -ne 0 -or $existing) { throw 'Cannot prove selected Docker project is unused.' }
$volumes = & docker volume ls -q --filter "label=com.docker.compose.project=$project"
if ($LASTEXITCODE -ne 0 -or $volumes) { throw 'Cannot prove selected Docker volumes are unused.' }
$allVolumes = @(& docker volume ls -q)
if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate existing volumes.' }
foreach ($suffix in @('postgres_data','redis_data','minio_data','n8n_data','ota_data','device_logs','certbot-data','certbot-www')) {
    $volumeName = "${project}_${suffix}"
    if ($allVolumes -contains $volumeName) { throw "Volume name already exists: $volumeName" }
}
$allNetworks = @(& docker network ls --format '{{.Name}}')
if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate existing networks.' }
foreach ($suffix in @('frontend-net','backend-net')) {
    $networkName = "${project}_${suffix}"
    if ($allNetworks -contains $networkName) { throw "Network name already exists: $networkName" }
}
if (Test-Path -LiteralPath $dir) { throw 'Private destination already exists.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required to identify the source revision; run from a Git clone.' }
$revisionLines = @(& git -C $root rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $revisionLines.Count -ne 1 -or $revisionLines[0] -notmatch '^[0-9a-f]{40,64}$') { throw 'Cannot identify Git source revision.' }
$sourceRevision = $revisionLines[0]
New-Item -ItemType Directory -Path $dir -ErrorAction Stop | Out-Null
$acl = Get-Acl -LiteralPath $dir
$acl.SetAccessRuleProtection($true,$false)
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $dir -AclObject $acl
function New-Secret([int]$length = 32) {
    $bytes = New-Object byte[] $length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}
function Write-NewFile([string]$path, [string]$content) {
    $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false)); try { $writer.Write($content) } finally { $writer.Dispose() } } finally { $stream.Dispose() }
}
$agentDir = Join-Path $dir 'agent-config'
Copy-Item -LiteralPath (Join-Path $root 'agent-config') -Destination $agentDir -Recurse
$agentFile = Join-Path $agentDir 'environments/development.json'
$agent = Get-Content -LiteralPath $agentFile -Raw -Encoding UTF8 | ConvertFrom-Json
$agent.enrollment_api_key = 'sphr_' + (New-Secret 32)
$agent.server_url = "http://127.0.0.1:$GatewayPort"
[IO.File]::WriteAllText($agentFile, ($agent | ConvertTo-Json -Depth 30), [Text.UTF8Encoding]::new($false))
$adminPassword = New-Secret
$envPath = Join-Path $dir 'install.env'
$vars = [ordered]@{
 POSTGRES_USER='sphere'; POSTGRES_PASSWORD=(New-Secret); REDIS_PASSWORD=(New-Secret);
 JWT_SECRET_KEY=(New-Secret 64); N8N_ENCRYPTION_KEY=(New-Secret);
 MINIO_ROOT_USER=('sphere' + (New-Secret 8)); MINIO_ROOT_PASSWORD=(New-Secret);
 PILOT_IMAGE_PREFIX=$project; PILOT_REVISION=$sourceRevision.Substring(0,12); PILOT_GATEWAY_PORT=$GatewayPort;
 PILOT_N8N_PORT=$N8nPort; PILOT_S3_PORT=$S3Port; PILOT_S3_CONSOLE_PORT=$S3ConsolePort;
 PILOT_AGENT_URL="http://127.0.0.1:$GatewayPort"; PILOT_BROWSER_URL="http://127.0.0.1:$GatewayPort";
 WG_ROUTER_URL='http://127.0.0.1:8001'; WG_ROUTER_API_KEY='';
 AWG_H1='2545529037'; AWG_H2='1767770215'; AWG_H3='2031675751'; AWG_H4='3699611814';
 SPHERE_BOOTSTRAP_ORG_SLUG='default'; ENVIRONMENT='development'
}
if ($Mode -eq 'Restore') {
    $snapshotPath = (Resolve-Path -LiteralPath $Snapshot).Path
    $manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $snapshotPath 'manifest.json') | ConvertFrom-Json
    $configEntry = @($manifest.artifacts | Where-Object { $_.path -eq 'container-configs-sensitive.json' -and $_.kind -eq 'sensitive-container-config' })
    $configPath = Join-Path $snapshotPath 'container-configs-sensitive.json'
    if ($configEntry.Count -ne 1 -or -not (Test-Path -LiteralPath $configPath -PathType Leaf)) { throw 'Missing unique sensitive container config in snapshot manifest.' }
    if ((Get-Item -LiteralPath $configPath).Length -ne $configEntry[0].size -or (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -ne $configEntry[0].sha256) { throw 'Sensitive container config hash or size mismatch.' }
    $configs = @(Get-Content -Raw -Encoding UTF8 -LiteralPath $configPath | ConvertFrom-Json)
    function Read-OldEnvironment([string]$container) {
        $selected = @($configs | Where-Object { $_.Name -eq "/$container" })
        if ($selected.Count -ne 1) { throw "Snapshot must contain exactly one config for $container." }
        $result = @{}
        foreach ($pair in $selected[0].Config.Env) {
            $parts = $pair -split '=',2
            if ($parts.Count -eq 2) { $result[$parts[0]] = $parts[1] }
        }
        return $result
    }
    $pg = Read-OldEnvironment 'sphere-pilot-20260911-postgres-1'
    $redis = Read-OldEnvironment 'sphere-pilot-20260911-redis-1'
    $minio = Read-OldEnvironment 'sphere-pilot-20260911-minio-1'
    $n8n = Read-OldEnvironment 'sphere-pilot-20260911-n8n-1'
    $backend = Read-OldEnvironment 'sphere-pilot-20260911-backend-1'
    foreach ($item in @(@($pg,'POSTGRES_USER'),@($pg,'POSTGRES_PASSWORD'),@($redis,'REDIS_PASSWORD'),@($minio,'MINIO_ROOT_USER'),@($minio,'MINIO_ROOT_PASSWORD'),@($n8n,'N8N_ENCRYPTION_KEY'),@($backend,'JWT_SECRET_KEY'))) {
        if (-not $item[0].ContainsKey($item[1]) -or -not $item[0][$item[1]]) { throw "Required old setting absent: $($item[1])" }
        $vars[$item[1]] = $item[0][$item[1]]
    }
    foreach ($key in @('ACCOUNT_CREDENTIAL_KEYS','VPN_PROFILE_ENCRYPTION_KEYS','VPN_PROFILE_POSTGRES_URL','SCREENSHOT_STORAGE_ENDPOINT','SCREENSHOT_STORAGE_ACCESS_KEY','SCREENSHOT_STORAGE_SECRET_KEY','SCREENSHOT_STORAGE_SECURE','SCREENSHOT_STORAGE_REGION')) {
        if ($backend.ContainsKey($key)) { $vars[$key] = $backend[$key] }
    }
    # A profile DSN to this restored PostgreSQL is safe inside the isolated
    # backend network; another host/database needs a separate verified backup.
    if ($vars['VPN_PROFILE_POSTGRES_URL']) {
        try { $profileDsn = [uri]$vars['VPN_PROFILE_POSTGRES_URL'] } catch { throw 'Cannot parse profile database address.' }
        if ($profileDsn.Host -ne 'postgres' -or $profileDsn.AbsolutePath -ne '/sphereplatform') { throw 'VPN profile database is external to the captured application database; restore it separately.' }
    }
    $restorePasswordPath = Join-Path $dir 'restore-postgres-password.txt'
    Write-NewFile $restorePasswordPath ((New-Secret) + "`n")
}
$envText = (($vars.GetEnumerator() | ForEach-Object {
    $value = [string]$_.Value
    if ($value.Contains("`n") -or $value.Contains("`r")) { throw "Multiline dotenv value rejected: $($_.Key)" }
    "$($_.Key)='" + ($value -replace "'", "\'") + "'"
}) -join "`n") + "`n"
Write-NewFile $envPath $envText
if ($Mode -eq 'New') { Write-NewFile (Join-Path $dir 'admin.env') "ADMIN_EMAIL=$AdminEmail`nADMIN_PASSWORD=$adminPassword`n" }
$agentComposePath = ($agentDir -replace '\\','/')
$overlay = "services:`n  backend:`n    volumes: !override`n      - '${agentComposePath}:/app/agent-config:ro'`n      - ota_data:/app/backend/updates`n      - device_logs:/var/lib/sphere/device-logs`n"
if ($Mode -eq 'Restore') {
    # Only the reverse proxy also joins an ordinary bridge so Docker Desktop can
    # publish its loopback port. Backend and data stay on internal-only networks.
    $overlay += "    environment:`n      AGENT_CONFIG_ENV: restore`n  nginx:`n    networks:`n      - frontend-net`n      - restore-entry`nnetworks:`n  frontend-net:`n    internal: true`n  backend-net:`n    internal: true`n  restore-entry: {} `n"
}
$overlayPath = Join-Path $dir 'private-overlay.yml'
Write-NewFile $overlayPath $overlay
$files = @('docker-compose.yml','docker-compose.full.yml','docker-compose.local-pilot.yml') | ForEach-Object { Join-Path $root $_ }
$argsBase = @('compose','--project-directory',$root,'--env-file',$envPath,'-p',$project,'-f',$files[0],'-f',$files[1],'-f',$files[2],'-f',$overlayPath)
# Shell environment takes precedence over --env-file. Remove all interpolation
# variables and Compose overrides for this process, then restore them on exit.
$saved = @{}
$names = @($files | ForEach-Object { [regex]::Matches((Get-Content -Raw -LiteralPath $_), '\$\{([A-Za-z_][A-Za-z_0-9]*)') | ForEach-Object { $_.Groups[1].Value } } | Select-Object -Unique)
$names += @('COMPOSE_FILE','COMPOSE_PROJECT_NAME','COMPOSE_PROFILES','COMPOSE_ENV_FILES','ADMIN_EMAIL','ADMIN_PASSWORD')
foreach ($name in ($names | Select-Object -Unique)) { $saved[$name] = [Environment]::GetEnvironmentVariable($name,'Process'); [Environment]::SetEnvironmentVariable($name,$null,'Process') }
function Invoke-Compose([string[]]$cmd) {
    & docker @argsBase @cmd
    if ($LASTEXITCODE -ne 0) { throw "Compose stage failed: $($cmd[0]); files and project retained for investigation." }
}
function Invoke-BuildWithReserve {
    # Start-Process joins arguments on Windows; quote each argv item explicitly.
    # Paths produced here never contain a quote; reject them instead of guessing.
    $all = @($argsBase) + @('build','backend','frontend')
    if (@($all | Where-Object { $_.Contains('"') }).Count) { throw 'A build argument contains a quote.' }
    $quoted = @($all | ForEach-Object { '"' + $_ + '"' })
    $stdout = Join-Path $dir 'build.stdout.log'
    $stderr = Join-Path $dir 'build.stderr.log'
    if ((Test-Path -LiteralPath $stdout) -or (Test-Path -LiteralPath $stderr)) { throw 'Build logs already exist.' }
    $dockerPath = (Get-Command docker -CommandType Application | Select-Object -First 1).Source
    $process = Start-Process -FilePath $dockerPath -ArgumentList $quoted -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    # Retain the native handle; Windows PowerShell 5 can otherwise lose ExitCode
    # for a process that exits while polling HasExited.
    $null = $process.Handle
    while (-not $process.HasExited) {
        Start-Sleep -Seconds 2
        $process.Refresh()
        if ((Get-PSDrive -Name $drive.Name).Free -lt 12GB) {
            if (-not $process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
            throw 'Build cancelled: free space fell below 12 GiB. Docker may need time to stop its build; private logs were retained.'
        }
    }
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Build failed; inspect private logs in $dir." }
}
try {
    Invoke-Compose @('config','--quiet')
    if ($BackendImage) {
        Write-Output 'Reusing the explicitly selected local images; source equivalence is not established by this option.'
        & docker image tag $BackendImage "${project}-backend:fresh"
        if ($LASTEXITCODE -ne 0) { throw 'Cannot tag selected backend image.' }
        & docker image tag $FrontendImage "${project}-frontend:fresh"
        if ($LASTEXITCODE -ne 0) { throw 'Cannot tag selected frontend image.' }
    } else {
        Write-Output 'Building new images; progress is in the private build logs.'
        Invoke-BuildWithReserve
    }
    if ($Mode -eq 'Restore') {
        & python (Join-Path $root 'scripts/migration/restore_data.py') $snapshotPath --project $project --compose-volumes --preserve-roles --database sphereplatform --database n8n --volume minio_data --volume n8n_data --volume redis_data --volume ota_data --volume device_logs --volume identity --volume pilot_ssh_identity --volume certbot-data --volume certbot-www --pg-password-file $restorePasswordPath
        if ($LASTEXITCODE -ne 0) { throw 'Snapshot import failed; project and volumes retained for investigation.' }
        Invoke-Compose @('up','-d','--wait','--wait-timeout','180','postgres','redis','minio')
        Invoke-Compose @('up','-d','--wait','--wait-timeout','300','backend','frontend','nginx')
        $ready = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "http://127.0.0.1:$GatewayPort/api/v1/health/readyz"
        if ($ready.StatusCode -ne 200) { throw 'Restored backend readiness did not return HTTP 200.' }
        Write-Output "Restored isolated local pilot: http://127.0.0.1:$GatewayPort/login"
        Write-Output "Private settings: $dir. Sign in with the ORIGINAL account credentials."
        Write-Output 'Application and data networks are internal; nginx has a separate ingress bridge. n8n, VPN, tunnels and devices were not started. No schema migrations were applied.'
        return
    }
    Invoke-Compose @('up','-d','--wait','--wait-timeout','180','postgres','redis','minio')
    Invoke-Compose @('run','--rm','--no-deps','-T','backend','alembic','-c','alembic/alembic.ini','upgrade','head')
    [Environment]::SetEnvironmentVariable('ADMIN_EMAIL',$AdminEmail,'Process')
    [Environment]::SetEnvironmentVariable('ADMIN_PASSWORD',$adminPassword,'Process')
    $out = @(& docker @argsBase run --rm --no-deps -T -e ADMIN_EMAIL -e ADMIN_PASSWORD backend python scripts/create_admin.py --create-only)
    if ($LASTEXITCODE -ne 0 -or @($out | Where-Object { $_ -eq 'SPHERE_ADMIN_BOOTSTRAP=created' }).Count -ne 1) { throw 'Admin creation was not confirmed. Do not assume admin.env is valid.' }
    [Environment]::SetEnvironmentVariable('ADMIN_PASSWORD',$null,'Process')
    Invoke-Compose @('run','--rm','--no-deps','-T','backend','python','-m','scripts.seed_enrollment_key')
    Invoke-Compose @('up','-d','--wait','--wait-timeout','300','backend','frontend','nginx','n8n')
    $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "http://127.0.0.1:$GatewayPort/api/v1/health/readyz"
    if ($response.StatusCode -ne 200) { throw 'Readiness did not return HTTP 200.' }
    try {
        $body = @{email=$AdminEmail; password=$adminPassword} | ConvertTo-Json -Compress
        $login = Invoke-RestMethod -Method Post -ContentType 'application/json' -TimeoutSec 10 -Uri "http://127.0.0.1:$GatewayPort/api/v1/auth/login" -Body $body
        if (-not $login.access_token) { throw 'Missing access token.' }
    } catch { throw 'Admin API login verification failed; inspect the isolated installation.' }
    Write-Output "New local pilot ready: http://127.0.0.1:$GatewayPort/login"
    Write-Output "Private admin credentials and environment: $dir"
    Write-Output 'Local development only. Device access, VPN, external tunnels and old data are not configured.'
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
}
