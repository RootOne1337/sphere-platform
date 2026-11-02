[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Destination)

$ErrorActionPreference = 'Stop'
$target = [System.IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $target) { throw 'Use a new private destination directory.' }
New-Item -ItemType Directory -Path $target -Force | Out-Null
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $target '/inheritance:r' '/grant:r' "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict private archive permissions.' }
$issues = [System.Collections.Generic.List[string]]::new()

function Save-PrivateJson([string]$Name, $Data) {
    $Data | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $target $Name) -Encoding utf8
}
function Copy-Private([string]$Source, [string]$Name) {
    if (!(Test-Path -LiteralPath $Source)) { $issues.Add("Absent: $Source"); return }
    try { Copy-Item -LiteralPath $Source -Destination (Join-Path $target $Name) -Recurse -Force }
    catch { $issues.Add("Copy failed: $Source ($($_.Exception.GetType().Name))") }
}

# Values can include credentials. All raw material stays in the restricted directory.
Copy-Private "$env:USERPROFILE\.ssh" 'ssh'
Copy-Private "$env:USERPROFILE\.cloudflared" 'cloudflared'
Copy-Private "$env:USERPROFILE\.wslconfig" 'wslconfig'
Copy-Private "$env:USERPROFILE\.docker\config.json" 'docker-config.json'
Copy-Private "$env:USERPROFILE\.android\debug.keystore" 'android-debug.keystore'
Copy-Private "$env:USERPROFILE\.android\adbkey" 'adbkey'
Copy-Private "$env:USERPROFILE\.android\adbkey.pub" 'adbkey.pub'
Copy-Private "$env:APPDATA\Proxifier4\Profiles" 'proxifier-profiles'
Copy-Private "$env:LOCALAPPDATA\tuna" 'tuna'
Copy-Private "$env:APPDATA\Docker\settings-store.json" 'docker-settings-store.json'
Copy-Private "$env:APPDATA\Docker\settings.json" 'docker-settings-legacy.json'

foreach ($entry in @(
    @{Key='HKCU\Software\AmneziaVPN.ORG'; File='amnezia-user.reg'},
    @{Key='HKLM\SOFTWARE\AmneziaVPN.ORG'; File='amnezia-machine.reg'}
)) {
    & reg.exe export $entry.Key (Join-Path $target $entry.File) /y *> $null
    if ($LASTEXITCODE -ne 0) { $issues.Add("Registry export unavailable: $($entry.Key)") }
}

$servicePattern = 'sphere|amnezia|wireguard|tunnel|proxy|docker|tailscale|ssh|vpn|cloudflare|tuna'
Save-PrivateJson 'services.json' @(Get-CimInstance Win32_Service | Where-Object {
    $_.Name -match $servicePattern -or $_.PathName -match $servicePattern
} | Select-Object Name,State,StartMode,StartName,PathName)
$tasks = @(Get-ScheduledTask | Where-Object { $_.TaskName -match 'sphere|ldplayer|discovery|tunnel|tuna|route|motor|vpn' -and $_.TaskPath -notlike '\Microsoft\*' })
$taskDir = Join-Path $target 'scheduled-tasks'
New-Item -ItemType Directory -Path $taskDir | Out-Null
foreach ($task in $tasks) {
    $safe = $task.TaskName -replace '[^\w.-]', '_'
    Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath |
        Set-Content -LiteralPath (Join-Path $taskDir "$safe.xml") -Encoding utf8
}
Save-PrivateJson 'scheduled-task-info.json' @($tasks | Select-Object TaskName,TaskPath,State,Actions,Principal,Settings)
Save-PrivateJson 'network-adapters.json' @(Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,MacAddress,LinkSpeed)
Save-PrivateJson 'network-routes.json' @(Get-NetRoute | Select-Object DestinationPrefix,NextHop,InterfaceAlias,RouteMetric,PolicyStore)
Save-PrivateJson 'network-dns.json' @(Get-DnsClientServerAddress | Select-Object InterfaceAlias,AddressFamily,ServerAddresses)
Save-PrivateJson 'firewall-sphere.json' @(Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match $servicePattern } | Select-Object DisplayName,Enabled,Direction,Action,Profile)
Save-PrivateJson 'wsl-distros.json' @(& wsl.exe --list --verbose)
Save-PrivateJson 'tools.json' @(Get-Command git,python,node,npm,docker,gh,pwsh,adb,java,ffmpeg -ErrorAction SilentlyContinue | Select-Object Name,Source,Version)
Save-PrivateJson 'host-environment.json' @{
    UserPath=[Environment]::GetEnvironmentVariable('PATH','User')
    MachinePath=[Environment]::GetEnvironmentVariable('PATH','Machine')
    AndroidHome=$env:ANDROID_HOME; AndroidSdkRoot=$env:ANDROID_SDK_ROOT; JavaHome=$env:JAVA_HOME
    UserProfile=$env:USERPROFILE; ComputerName=$env:COMPUTERNAME
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoSecrets = Join-Path $target 'repository-private'
New-Item -ItemType Directory -Path $repoSecrets | Out-Null
foreach ($relative in @('.env','.env.local','.env.production','.admin-credentials','android\local.properties')) {
    $source = Join-Path $repo $relative
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $repoSecrets ($relative -replace '[\\/]', '__')) -Force
    }
}
# Preserve private launcher definitions and every SMALL running bind file. Large
# data trees are captured separately by data/routes tools, never silently copied.
$privateConfig = Join-Path $target 'runtime-bind-config'
New-Item -ItemType Directory -Path $privateConfig | Out-Null
$mapping = @()
$runningIds = @(& docker ps -q)
if ($LASTEXITCODE -eq 0 -and $runningIds.Count -gt 0) {
    $containers = @((& docker inspect @runningIds) | ConvertFrom-Json)
    $containers | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath (Join-Path $target 'running-container-inspect.private.json') -Encoding utf8
    $index = 0
    foreach ($container in $containers) {
        $composeFiles = [string]$container.Config.Labels.'com.docker.compose.project.config_files'
        foreach ($compose in ($composeFiles -split ',')) {
            if ($compose -and (Test-Path -LiteralPath $compose -PathType Leaf)) {
                $file = Get-Item -LiteralPath $compose
                if ($file.Length -le 2MB) {
                    $index++
                    $name = "compose-$index-" + $file.Name
                    Copy-Item -LiteralPath $compose -Destination (Join-Path $privateConfig $name)
                    $mapping += @{Container=$container.Name; Source=$compose; Captured=$true; SavedAs=$name; Kind='compose-definition'}
                    $baseline = Join-Path $file.DirectoryName 'baseline.json'
                    if (Test-Path -LiteralPath $baseline -PathType Leaf) {
                        $index++
                        $baseName = "baseline-$index.json"
                        Copy-Item -LiteralPath $baseline -Destination (Join-Path $privateConfig $baseName)
                        $mapping += @{Container=$container.Name; Source=$baseline; Captured=$true; SavedAs=$baseName; Kind='private-install-baseline'}
                    }
                }
            }
        }
        foreach ($mount in @($container.Mounts | Where-Object { $_.Type -eq 'bind' })) {
            $source = [string]$mount.Source
            if ($source -match '^/run/desktop/mnt/host/([a-z])/(.*)$') {
                $source = $Matches[1].ToUpperInvariant() + ':\' + ($Matches[2] -replace '/', '\')
            }
            $entry = @{Container=$container.Name; Source=$source; Destination=$mount.Destination; Captured=$false}
            if (Test-Path -LiteralPath $source -PathType Leaf) {
                $file = Get-Item -LiteralPath $source
                if ($file.Length -le 2MB) {
                    $index++
                    $name = "bind-$index-" + $file.Name
                    Copy-Item -LiteralPath $source -Destination (Join-Path $privateConfig $name)
                    $entry.Captured=$true; $entry.SavedAs=$name
                }
            }
            $mapping += $entry
        }
    }
    Save-PrivateJson 'runtime-bind-mapping.json' $mapping
}
foreach ($relative in @('.local-pilot\pilot.env','.local-pilot\tuna-pilot\tuna.yml','.local-pilot\remote\private.env')) {
    $source = Join-Path $repo $relative
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $repoSecrets ($relative -replace '[\\/]', '__')) -Force
    }
}
Save-PrivateJson 'issues.json' @($issues)
$files = @(Get-ChildItem -LiteralPath $target -File -Recurse | ForEach-Object {
    @{Path=$_.FullName.Substring($target.TrimEnd('\','/').Length + 1); Bytes=$_.Length; SHA256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
Save-PrivateJson 'manifest.json' @{
    SchemaVersion=1; Private=$true; IndependentBackup=$false
    CreatedAtUtc=[DateTime]::UtcNow.ToString('o'); Files=$files
    Limitations=@('Windows registry secrets may be DPAPI-bound to the old user and need application export/re-entry.',
      'This captures configuration only: no emulator disks, Ubuntu filesystem, Docker VHDX or external VPS/router backup.',
      'Task credentials are not exported by Windows; re-register tasks with the new account.',
      'Network/firewall files are evidence, not an automatic import policy.')
}
Write-Output "Private host configuration saved: $($files.Count) files; $($issues.Count) unavailable/absent inputs. Same-disk staging only."
