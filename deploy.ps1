#!/usr/bin/env pwsh
# deploy.ps1 — запускать в ОБЫЧНОМ PowerShell (не в VS Code!)
# Полный цикл: сборка → запуск → миграции → проверка
#
# Использование:
#   .\deploy.ps1          # dev-режим (docker-compose.override.yml применяется автоматически)
#   .\deploy.ps1 -Full    # production-like (full.yml + override отключён)
#   .\deploy.ps1 -Down    # остановить всё
#   .\deploy.ps1 -Logs    # смотреть логи

param(
    [switch]$Full,
    [switch]$Down,
    [switch]$Logs,
    [switch]$Restart
)

Set-Location $PSScriptRoot

# ─── Docker Compose command ───────────────────────────────────────────────────
# Docker Desktop на Windows: docker compose встроен в cli-plugins, не в PATH.
# Используем docker-compose.exe напрямую.
$dockerCompose = "C:\Program Files\Docker\Docker\resources\cli-plugins\docker-compose.exe"
if (-not (Test-Path $dockerCompose)) {
    # Fallback: попробовать docker compose из PATH
    $dockerCompose = $null
}

function Invoke-Compose {
    param([string[]]$Arguments)
    if ($dockerCompose) {
        & $dockerCompose $Arguments
    } else {
        & docker compose $Arguments
    }
}

$composeFiles = @("-f", "docker-compose.yml", "-f", "docker-compose.full.yml")
$composeArgs = $composeFiles

Write-Host "MODE: Full stack (docker-compose.yml + docker-compose.full.yml)" -ForegroundColor Cyan

# ─── Down ─────────────────────────────────────────────────────────────────────
if ($Down) {
    Write-Host "`n[1/1] Stopping all services..." -ForegroundColor Yellow
    & $dockerExe @composeArgs down
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

# ─── Logs ─────────────────────────────────────────────────────────────────────
if ($Logs) {
    & $dockerExe @composeArgs logs -f --tail=100
    exit 0
}

# ─── Restart individual service ───────────────────────────────────────────────
if ($Restart) {
    $svc = Read-Host "Service name to restart"
    & $dockerExe @composeArgs restart $svc
    exit 0
}

# ─── Full deploy ──────────────────────────────────────────────────────────────
Write-Host "`n[1/4] Building images (only changed layers)..." -ForegroundColor Yellow
# --no-deps — только фронтенд/бэкенд, инфра (postgres/redis) не пересобирается
& $dockerExe @composeArgs build --parallel
if ($LASTEXITCODE -ne 0) {
    Write-Host "BUILD FAILED" -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/4] Starting all services..." -ForegroundColor Yellow
& $dockerExe @composeArgs up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "UP FAILED" -ForegroundColor Red
    exit 1
}

# ─── Wait for postgres ────────────────────────────────────────────────────────
Write-Host "`n[3/4] Waiting for postgres to be healthy..." -ForegroundColor Yellow
$maxWait = 60
$waited = 0
do {
    Start-Sleep -Seconds 2
    $waited += 2
    $health = & $dockerExe @composeArgs ps postgres --format "{{.Health}}" 2>$null
    Write-Host "  postgres health: $health ($waited s)" -ForegroundColor Gray
} while ($health -ne "healthy" -and $waited -lt $maxWait)

if ($health -ne "healthy") {
    Write-Host "Postgres did not become healthy in ${maxWait}s — check logs:" -ForegroundColor Red
    & $dockerExe @composeArgs logs postgres --tail=20
    exit 1
}
Write-Host "  postgres: healthy" -ForegroundColor Green

# ─── Alembic migrations ───────────────────────────────────────────────────────
# Запускаем с ХОСТА (не внутри контейнера): alembic/ монтируется только в override-режиме.
# Postgres должен быть доступен на localhost:5432 (порт проброшен в docker-compose.yml).
Write-Host "`n[4/4] Running Alembic migrations..." -ForegroundColor Yellow

# Активируем venv если нужно
$venvAlembic = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pythonAlembic = if (Test-Path $venvAlembic) { $venvAlembic } else { "python" }

& $pythonAlembic -m alembic -c alembic/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Migrations FAILED — check .env POSTGRES_URL and DB connectivity" -ForegroundColor Red
    exit 1
}
Write-Host "  Migrations done" -ForegroundColor Green

# ─── Status ───────────────────────────────────────────────────────────────────
Write-Host "`n=== Service Status ===" -ForegroundColor Cyan
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | Select-String "sphere"

Write-Host "`n=== Done! ===" -ForegroundColor Green
Write-Host "Frontend:  http://localhost (dev server on :3002 via nginx)" -ForegroundColor White
Write-Host "Backend:   http://localhost:8000/docs" -ForegroundColor White
Write-Host "n8n:       http://localhost:5678" -ForegroundColor White
Write-Host "MinIO:     http://localhost:9001" -ForegroundColor White
Write-Host "`nLogs: .\deploy.ps1 -Logs" -ForegroundColor Gray
Write-Host "Stop: .\deploy.ps1 -Down" -ForegroundColor Gray
