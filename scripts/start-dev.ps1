#!/usr/bin/env pwsh
# scripts/start-dev.ps1
# =============================================================================
# Sphere Platform — Enterprise Dev Starter
# =============================================================================
# Запуск всего стека одной командой: .\scripts\start-dev.ps1
# Флаги:
#   -Tunnel     — также поднять SSH туннель к Serveo
#   -Rebuild    — пересобрать образы backend/frontend перед запуском
#   -Down       — остановить весь стек
#   -Status     — показать статус всех сервисов
# =============================================================================

param(
    [switch]$Tunnel,
    [switch]$Rebuild,
    [switch]$Down,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path $PSScriptRoot -Parent

# ── Цвета ────────────────────────────────────────────────────────────────────
function Write-Header {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║          Sphere Platform — Dev Starter v1.0             ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step([string]$msg) {
    Write-Host "  ▶ $msg" -ForegroundColor Yellow
}

function Write-Ok([string]$msg) {
    Write-Host "  ✓ $msg" -ForegroundColor Green
}

function Write-Err([string]$msg) {
    Write-Host "  ✗ $msg" -ForegroundColor Red
}

function Write-Info([string]$msg) {
    Write-Host "  · $msg" -ForegroundColor DarkGray
}

# ── Проверка Docker ───────────────────────────────────────────────────────────
function Assert-DockerRunning {
    Write-Step "Проверяю Docker Desktop..."
    try {
        docker info 2>&1 | Out-Null
        Write-Ok "Docker запущен"
    } catch {
        Write-Err "Docker не запущен! Запусти Docker Desktop и повтори."
        exit 1
    }
}

# ── Проверка .env ─────────────────────────────────────────────────────────────
function Assert-EnvFile {
    Write-Step "Проверяю .env файл..."
    $envFile = Join-Path $ROOT ".env"
    if (-not (Test-Path $envFile)) {
        if (Test-Path (Join-Path $ROOT ".env.example")) {
            Copy-Item (Join-Path $ROOT ".env.example") $envFile
            Write-Info ".env создан из .env.example — заполни POSTGRES_PASSWORD и REDIS_PASSWORD!"
        } else {
            Write-Err ".env файл не найден! Создай его из .env.example"
            exit 1
        }
    } else {
        Write-Ok ".env найден"
    }
}

# ── Статус ────────────────────────────────────────────────────────────────────
function Show-Status {
    Write-Header
    Write-Host "  СЕРВИСЫ:" -ForegroundColor Cyan
    Write-Host ""
    docker compose -f (Join-Path $ROOT "docker-compose.yml") `
                   -f (Join-Path $ROOT "docker-compose.full.yml") `
                   ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

    Write-Host ""
    Write-Host "  ТУННЕЛЬ:" -ForegroundColor Cyan
    $tunnelRunning = docker ps --filter "name=sphere-tunnel" --format "{{.Status}}" 2>$null
    if ($tunnelRunning) {
        Write-Host "  ✓ sphere-tunnel: $tunnelRunning" -ForegroundColor Green
        Write-Host "  · URL: https://sphere.serveousercontent.com" -ForegroundColor DarkGray
    } else {
        Write-Host "  · Туннель не запущен. Запусти: .\scripts\start-dev.ps1 -Tunnel" -ForegroundColor DarkGray
    }
    Write-Host ""
}

# ── Остановка ─────────────────────────────────────────────────────────────────
function Stop-AllServices {
    Write-Header
    Write-Step "Останавливаю туннель..."
    docker compose -f (Join-Path $ROOT "docker-compose.tunnel.yml") down 2>$null
    Write-Ok "Туннель остановлен"

    Write-Step "Останавливаю backend + frontend..."
    docker compose -f (Join-Path $ROOT "docker-compose.yml") `
                   -f (Join-Path $ROOT "docker-compose.full.yml") down
    Write-Ok "Весь стек остановлен"
    exit 0
}

# ── Туннель: генерация ключа ──────────────────────────────────────────────────
function Ensure-TunnelKey {
    $keyPath = Join-Path $ROOT "infrastructure\tunnel\keys\id_rsa"
    $keyDir  = Join-Path $ROOT "infrastructure\tunnel\keys"

    if (-not (Test-Path $keyPath)) {
        Write-Step "SSH ключ для туннеля не найден. Генерирую..."
        New-Item -ItemType Directory -Force -Path $keyDir | Out-Null
        
        # Генерируем ключ без пароля
        ssh-keygen -t ed25519 -C "sphere-tunnel@$(hostname)" -f $keyPath -N "" 2>&1 | Out-Null
        
        $pubKey = Get-Content "$keyPath.pub"
        Write-Ok "SSH ключ сгенерирован!"
        Write-Host ""
        Write-Host "  ┌─────────────────────────────────────────────────────────┐" -ForegroundColor Magenta
        Write-Host "  │  ПУБЛИЧНЫЙ КЛЮЧ (добавь на serveo.net для фиксации URL) │" -ForegroundColor Magenta
        Write-Host "  └─────────────────────────────────────────────────────────┘" -ForegroundColor Magenta
        Write-Host "  $pubKey" -ForegroundColor White
        Write-Host ""
        Write-Host "  Команда регистрации:" -ForegroundColor Yellow
        Write-Host "  ssh -R sphere:80:localhost:80 serveo.net" -ForegroundColor White
        Write-Host ""
        Write-Info "Подключись ОДИН РАЗ вручную для записи ключа в Serveo"
        Write-Host ""
    } else {
        Write-Ok "SSH ключ найден"
    }
}

# ── Туннель: cloudflared ─────────────────────────────────────────────────────
function Start-Tunnel {
    Write-Step "Пересобираю образ туннеля (если нужно)..."
    docker build -t sphere-tunnel:latest -f infrastructure/tunnel/Dockerfile infrastructure/tunnel/ 2>&1 | Select-Object -Last 3
    Write-Ok "Образ туннеля готов"

    # Удаляем старый если был
    docker stop sphere-tunnel 2>$null | Out-Null
    docker rm sphere-tunnel 2>$null | Out-Null

    Write-Step "Запускаю Cloudflare Quick Tunnel (restart: always)..."
    docker run -d `
        --name sphere-tunnel `
        --restart always `
        --network sphere-platform_frontend-net `
        sphere-tunnel:latest `
        --url http://nginx:80 | Out-Null
    
    Start-Sleep 8

    # Извлекаем URL из логов
    $logs = docker logs sphere-tunnel 2>&1
    $tunnelUrl = ($logs | Select-String 'https://.*trycloudflare' | Select-Object -First 1).Matches.Value
    
    if ($tunnelUrl) {
        Write-Ok "Туннель запущен!"
        Write-Host ""
        Write-Host "  🌐 URL: $tunnelUrl" -ForegroundColor Cyan
        # Сохраняем URL в файл для удобства
        $tunnelUrl | Set-Content ".tunnel-url" -Encoding UTF8
        Write-Info "URL сохранён в .tunnel-url"
    } else {
        Write-Err "Туннель не запустился. Проверь: docker logs sphere-tunnel"
    }
}

# ── Ожидание healthy ──────────────────────────────────────────────────────────
function Wait-ServiceHealthy([string]$serviceName, [int]$timeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    Write-Host -NoNewline "  ⏳ Жду $serviceName healthy" -ForegroundColor Yellow
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect --format "{{.State.Health.Status}}" $serviceName 2>$null
        if ($status -eq "healthy") {
            Write-Host " ✓" -ForegroundColor Green
            return $true
        }
        Write-Host -NoNewline "." -ForegroundColor DarkGray
        Start-Sleep 2
    }
    Write-Host " timeout" -ForegroundColor Red
    return $false
}

# ── MAIN ──────────────────────────────────────────────────────────────────────
Write-Header

if ($Status) { Show-Status; exit 0 }
if ($Down)   { Stop-AllServices }

Assert-DockerRunning
Assert-EnvFile

# Пересборка образов если запрошена
if ($Rebuild) {
    Write-Step "Пересобираю образы backend + frontend..."
    docker compose -f (Join-Path $ROOT "docker-compose.yml") `
                   -f (Join-Path $ROOT "docker-compose.full.yml") build
    Write-Ok "Образы пересобраны"
}

# Запуск основного стека
Write-Step "Запускаю полный стек (infra + backend + frontend)..."
docker compose -f (Join-Path $ROOT "docker-compose.yml") `
               -f (Join-Path $ROOT "docker-compose.full.yml") up -d
Write-Ok "Стек запущен"

# Ждём критических сервисов
Write-Host ""
Wait-ServiceHealthy "sphere-platform-postgres-1" 60 | Out-Null
Wait-ServiceHealthy "sphere-platform-redis-1" 30 | Out-Null

# Туннель
if ($Tunnel) {
    Write-Host ""
    Ensure-TunnelKey
    Start-Tunnel
}

# Итоговый summary
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║                    СТЕК ЗАПУЩЕН ✓                       ║" -ForegroundColor Green
Write-Host "  ╠══════════════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "  ║  Frontend:   http://localhost:3000                       ║" -ForegroundColor White
Write-Host "  ║  Backend:    http://localhost:8000                       ║" -ForegroundColor White
Write-Host "  ║  API Docs:   http://localhost:8000/docs                  ║" -ForegroundColor White
Write-Host "  ║  n8n:        http://localhost:5678                       ║" -ForegroundColor White
Write-Host "  ║  MinIO:      http://localhost:9001                       ║" -ForegroundColor White
if ($Tunnel) {
    $tunnelUrl = ""
    if (Test-Path ".tunnel-url") { $tunnelUrl = Get-Content ".tunnel-url" -Raw }
    if (-not $tunnelUrl) { $tunnelUrl = "https://<проверь: docker logs sphere-tunnel>" }
Write-Host "  ║  🌐 Public:  $tunnelUrl" -ForegroundColor Cyan
}
Write-Host "  ╠══════════════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "  ║  Перекомпиляция — НЕ нужна при изменении кода:          ║" -ForegroundColor DarkGray
Write-Host "  ║  · Backend: uvicorn --reload (авто-перезагрузка)        ║" -ForegroundColor DarkGray
Write-Host "  ║  · Frontend: Turbopack HMR (hot reload в браузере)      ║" -ForegroundColor DarkGray
Write-Host "  ║  Нужна только при: pip install / npm install             ║" -ForegroundColor DarkGray
Write-Host "  ║  Команда: .\scripts\start-dev.ps1 -Rebuild              ║" -ForegroundColor DarkGray
Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
