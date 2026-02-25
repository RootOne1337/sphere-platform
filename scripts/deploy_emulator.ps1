<#
.SYNOPSIS
    deploy_emulator.ps1 — автоматический деплой Sphere Agent на Android-эмулятор.

.DESCRIPTION
    Полный цикл:
      1. Проверка что эмулятор запущен (adb devices)
      2. Сборка devDebug APK
      3. Установка APK на эмулятор (adb install)
      4. Создание + push конфиг-файла zero-touch provisioning
      5. Запуск SphereAgent activity
      6. Хвост logcat в фильтре Sphere-тегов

.PARAMETER ApiKey
    API-ключ устройства (из панели управления Sphere).
    Если не задан — используется пустая строка (manual enroll via UI).

.PARAMETER ServerUrl
    URL бэкенда. По умолчанию: http://10.0.2.2  (эмулятор → localhost хоста).

.PARAMETER DeviceId
    Опциональный стабильный идентификатор устройства. По умолчанию: auto-generated.

.PARAMETER SkipBuild
    Пропустить сборку (использовать уже собранный APK).

.PARAMETER NoLogcat
    Не запускать хвост logcat после установки.

.EXAMPLE
    .\deploy_emulator.ps1
    .\deploy_emulator.ps1 -ApiKey "sk-xyz" -ServerUrl "http://10.0.2.2"
    .\deploy_emulator.ps1 -SkipBuild -NoLogcat
#>

[CmdletBinding()]
param(
    [string]$ApiKey    = "",
    [string]$ServerUrl = "http://10.0.2.2",
    [string]$DeviceId  = "",
    [switch]$SkipBuild,
    [switch]$NoLogcat
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── ANSI colors ───────────────────────────────────────────────────────────────

function Write-Step([string]$msg)  { Write-Host "[>] $msg"  -ForegroundColor Cyan }
function Write-Ok([string]$msg)    { Write-Host "[✓] $msg"  -ForegroundColor Green }
function Write-Warn([string]$msg)  { Write-Host "[!] $msg"  -ForegroundColor Yellow }
function Write-Fail([string]$msg)  { Write-Host "[✗] $msg"  -ForegroundColor Red }

# ── Paths ─────────────────────────────────────────────────────────────────────

$ScriptDir   = $PSScriptRoot
$RepoRoot    = Split-Path $ScriptDir -Parent
$AndroidDir  = Join-Path $RepoRoot "android"
$GradlePath  = Join-Path $AndroidDir "gradlew.bat"
$ApkPath     = Join-Path $AndroidDir "app\build\outputs\apk\dev\debug\app-dev-debug.apk"
$ConfigFile  = Join-Path $env:TEMP "sphere-agent-config.json"

$AdbPath = $null
$SdkRoot = $env:ANDROID_HOME ?? $env:ANDROID_SDK_ROOT ?? "$env:LOCALAPPDATA\Android\Sdk"
if (Test-Path "$SdkRoot\platform-tools\adb.exe") {
    $AdbPath = "$SdkRoot\platform-tools\adb.exe"
} elseif (Get-Command adb -ErrorAction SilentlyContinue) {
    $AdbPath = "adb"
} else {
    Write-Fail "adb not found. Install Android SDK Platform Tools and add to PATH."
    exit 1
}

$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"

# ── Step 1: Check emulator ────────────────────────────────────────────────────

Write-Step "Checking for running Android emulator..."
$devices = & $AdbPath devices 2>&1 | Select-String "emulator-"
if (-not $devices) {
    Write-Fail "No Android emulator detected. Start an AVD first:"
    Write-Host "  Android Studio → Device Manager → ▶ Run" -ForegroundColor Gray
    Write-Host "  or: `$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe -avd <AVD_NAME>" -ForegroundColor Gray
    exit 1
}
$emulatorSerial = ($devices | Select-Object -First 1).ToString().Split("`t")[0].Trim()
Write-Ok "Emulator found: $emulatorSerial"

# ── Step 2: Build APK ─────────────────────────────────────────────────────────

if (-not $SkipBuild) {
    Write-Step "Building app-dev-debug APK..."
    Push-Location $AndroidDir
    try {
        & $GradlePath assembleDevDebug --no-configuration-cache --quiet
        if ($LASTEXITCODE -ne 0) { throw "Gradle build failed (exit code $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    Write-Ok "Build successful"
} else {
    Write-Warn "Skipping build (--SkipBuild)"
}

if (-not (Test-Path $ApkPath)) {
    Write-Fail "APK not found at $ApkPath"
    exit 1
}

$apkSize = [math]::Round((Get-Item $ApkPath).Length / 1MB, 1)
Write-Ok "APK ready: $ApkPath ($apkSize MB)"

# ── Step 3: Install APK ───────────────────────────────────────────────────────

Write-Step "Installing APK on $emulatorSerial..."
& $AdbPath -s $emulatorSerial install -r -t $ApkPath
if ($LASTEXITCODE -ne 0) { Write-Fail "adb install failed"; exit 1 }
Write-Ok "APK installed"

# ── Step 4: Push zero-touch config ────────────────────────────────────────────

Write-Step "Pushing zero-touch config to /sdcard/sphere-agent-config.json..."

$configObj = @{
    server_url = $ServerUrl
    api_key    = $ApiKey
}
if ($DeviceId -ne "") { $configObj.device_id = $DeviceId }

$configJson = $configObj | ConvertTo-Json -Compress
$configJson | Out-File -FilePath $ConfigFile -Encoding utf8 -NoNewline

& $AdbPath -s $emulatorSerial push $ConfigFile /sdcard/sphere-agent-config.json
if ($LASTEXITCODE -ne 0) {
    Write-Warn "adb push failed — zero-touch via /sdcard not available. App will show manual form."
} else {
    Write-Ok "Config pushed: $configJson"
}

# Grant READ_LOGS permission (best-effort — needed for full logcat capture)
Write-Step "Granting READ_LOGS permission (best-effort)..."
& $AdbPath -s $emulatorSerial shell pm grant com.sphereplatform.agent.dev android.permission.READ_LOGS 2>&1 | Out-Null
Write-Ok "Permission grant attempted"

# ── Step 5: Launch app ────────────────────────────────────────────────────────

Write-Step "Launching SphereAgent SetupActivity..."
& $AdbPath -s $emulatorSerial shell am start -n "com.sphereplatform.agent.dev/.ui.SetupActivity" `
    --activity-clear-top --activity-single-top
if ($LASTEXITCODE -ne 0) {
    Write-Warn "am start returned $LASTEXITCODE — app may already be running"
}
Write-Ok "Activity launched"

Write-Host ""
Write-Host "══════════════════════════════════════════════════════" -ForegroundColor Magenta
Write-Host "  Sphere Agent deployed to emulator $emulatorSerial"  -ForegroundColor Magenta
Write-Host "  Server: $ServerUrl"                                  -ForegroundColor Magenta
if ($ApiKey) {
    Write-Host "  Zero-touch: ENABLED (config pushed to /sdcard)"  -ForegroundColor Green
} else {
    Write-Host "  Zero-touch: MANUAL (no API key — will show form)" -ForegroundColor Yellow
}
Write-Host "══════════════════════════════════════════════════════" -ForegroundColor Magenta
Write-Host ""

# ── Step 6: Logcat tail ───────────────────────────────────────────────────────

if (-not $NoLogcat) {
    Write-Step "Starting logcat (Sphere tags only) — Ctrl+C to stop..."
    Write-Host "  Tags: SphereAgent SphereWS DagRunner OtaUpdate VpnManager ZeroTouch LogUploadW UpdateCheckW" -ForegroundColor Gray
    Write-Host ""

    # Clear existing logcat buffer first
    & $AdbPath -s $emulatorSerial logcat -c 2>&1 | Out-Null
    Start-Sleep -Milliseconds 500

    # Tail sphere-specific logs
    & $AdbPath -s $emulatorSerial logcat `
        "*:S" `
        "SphereAgent:V" `
        "SphereWS:V" `
        "DagRunner:V" `
        "OtaUpdate:V" `
        "VpnManager:V" `
        "ZeroTouch:V" `
        "LogUploadW:V" `
        "UpdateCheckW:V" `
        "NetChange:V" `
        "CmdHandler:V"
}
