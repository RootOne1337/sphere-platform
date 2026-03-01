#!/usr/bin/env pwsh
# =============================================================================
# full-deploy.ps1 — Полное развёртывание Sphere Platform (Windows PowerShell)
# =============================================================================
#
# Скрипт автоматизирует ВСЕ шаги от нуля до работающей системы:
#   1. Проверка зависимостей (Docker Desktop, Python, Git)
#   2. Генерация криптографических секретов
#   3. Сборка и запуск Docker-контейнеров
#   4. Ожидание готовности PostgreSQL и Redis
#   5. Применение Alembic-миграций
#   6. Создание суперадминистратора
#   7. Health-check всех сервисов
#
# Использование:
#   .\scripts\full-deploy.ps1              # Интерактивный
#   .\scripts\full-deploy.ps1 -Headless    # CI/CD (без вопросов)
#   .\scripts\full-deploy.ps1 -Production  # Production-режим
#   .\scripts\full-deploy.ps1 -Down        # Остановить всё
#
# =============================================================================

param(
    [switch]$Headless,
    [switch]$Production,
    [switch]$SkipSecrets,
    [switch]$Down,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogFile = Join-Path $ProjectDir ".deploy.log"
$StopWatch = [System.Diagnostics.Stopwatch]::StartNew()

if ($Production) {
    $ComposeFiles = @("-f", "docker-compose.yml", "-f", "docker-compose.production.yml")
} else {
    $ComposeFiles = @("-f", "docker-compose.yml", "-f", "docker-compose.full.yml")
}

# ── Справка ───────────────────────────────────────────────────────────────────
if ($Help) {
    Write-Host @"

  Sphere Platform — Скрипт полного развёртывания (Windows)

  ИСПОЛЬЗОВАНИЕ:
    .\scripts\full-deploy.ps1              # Интерактивный
    .\scripts\full-deploy.ps1 -Headless    # CI/CD
    .\scripts\full-deploy.ps1 -Production  # Production
    .\scripts\full-deploy.ps1 -Down        # Остановить

  ПАРАМЕТРЫ:
    -Headless      Без интерактивных вопросов
    -Production    Production docker-compose
    -SkipSecrets   Не перегенерировать .env.local
    -Down          Остановить все контейнеры
    -Help          Показать справку

  ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:
    SPHERE_ADMIN_EMAIL     Email администратора
    SPHERE_ADMIN_PASSWORD  Пароль (генерируется если пуст)

"@
    exit 0
}

# ── Логирование ───────────────────────────────────────────────────────────────
function Write-Log {
    param([string]$Level, [string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] [$Level] $Message" | Out-File -Append -Encoding utf8 $LogFile

    switch ($Level) {
        "INFO"  { Write-Host "[✓] $Message" -ForegroundColor Green }
        "WARN"  { Write-Host "[!] $Message" -ForegroundColor Yellow }
        "ERROR" { Write-Host "[✗] $Message" -ForegroundColor Red }
        "STEP"  { Write-Host "`n═══ $Message ═══" -ForegroundColor Cyan }
        default { Write-Host "    $Message" }
    }
}

# ── Баннер ────────────────────────────────────────────────────────────────────
function Show-Banner {
    $version = if (Test-Path "$ProjectDir\VERSION") { Get-Content "$ProjectDir\VERSION" -Raw } else { "unknown" }
    $mode = if ($Production) { "PRODUCTION" } else { "DEVELOPMENT" }

    Write-Host ""
    Write-Host "  ╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║                                                           ║" -ForegroundColor Cyan
    Write-Host "  ║         ● SPHERE PLATFORM — Full Deployment ●             ║" -ForegroundColor Cyan
    Write-Host "  ║                                                           ║" -ForegroundColor Cyan
    Write-Host "  ║   Enterprise Android Device Management & Automation       ║" -ForegroundColor Cyan
    Write-Host "  ║                                                           ║" -ForegroundColor Cyan
    Write-Host "  ╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Версия:   $($version.Trim())"
    Write-Host "  Режим:    $mode"
    Write-Host "  Дата:     $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host ""
}

# ── Docker Compose обёртка ────────────────────────────────────────────────────
function Invoke-Compose {
    param([string[]]$Arguments)
    $allArgs = $ComposeFiles + $Arguments
    & docker compose @allArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($Arguments -join ' ') провалился (exit code: $LASTEXITCODE)"
    }
}

# =============================================================================
# Остановка
# =============================================================================
if ($Down) {
    Write-Host "`n[1/1] Остановка всех контейнеров..." -ForegroundColor Yellow
    Set-Location $ProjectDir
    Invoke-Compose @("down")
    Write-Host "Все контейнеры остановлены." -ForegroundColor Green
    exit 0
}

# =============================================================================
# ШАГ 1: Проверка зависимостей
# =============================================================================
function Step-CheckDependencies {
    Write-Log "STEP" "Шаг 1/8 — Проверка зависимостей"

    # Docker
    try {
        $dockerVersion = (docker version --format '{{.Server.Version}}' 2>$null)
        Write-Log "INFO" "Docker: v$dockerVersion"
    } catch {
        Write-Log "ERROR" "Docker не установлен или не запущен. Скачай: https://www.docker.com/products/docker-desktop"
        exit 1
    }

    # Docker Compose
    try {
        $composeVersion = (docker compose version --short 2>$null)
        Write-Log "INFO" "Docker Compose: v$composeVersion"
    } catch {
        Write-Log "ERROR" "Docker Compose V2 не найден"
        exit 1
    }

    # Python
    try {
        $pyVersion = (python --version 2>&1) -replace 'Python ', ''
        Write-Log "INFO" "Python: v$pyVersion"
    } catch {
        Write-Log "WARN" "Python не найден — секреты нужно сгенерировать вручную"
    }

    # Git
    try {
        $gitVersion = (git --version) -replace 'git version ', ''
        Write-Log "INFO" "Git: v$gitVersion"
    } catch {
        Write-Log "WARN" "Git не найден"
    }

    Write-Log "INFO" "Все зависимости проверены"
}

# =============================================================================
# ШАГ 2: Генерация секретов
# =============================================================================
function Step-GenerateSecrets {
    Write-Log "STEP" "Шаг 2/8 — Генерация секретов"

    $envFile = Join-Path $ProjectDir ".env.local"

    if ((Test-Path $envFile) -and $SkipSecrets) {
        Write-Log "INFO" "Секреты уже существуют (.env.local) — пропуск"
        return
    }

    if (Test-Path $envFile) {
        if ($Headless) {
            Write-Log "INFO" "Секреты уже существуют (.env.local) — пропуск (headless)"
            return
        }
        $answer = Read-Host "[!] .env.local уже существует. Перезаписать? [y/N]"
        if ($answer -notin @("y", "Y")) {
            Write-Log "INFO" "Секреты сохранены без изменений"
            return
        }
        Copy-Item $envFile "$envFile.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Write-Log "INFO" "Бэкап создан"
    }

    & python scripts/generate_secrets.py --output .env.local
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR" "Не удалось сгенерировать секреты"
        exit 1
    }

    # Установить окружение
    $envValue = if ($Production) { "production" } else { "development" }
    $content = Get-Content $envFile -Raw
    $content = $content -replace 'ENVIRONMENT=\w+', "ENVIRONMENT=$envValue"
    Set-Content -Path $envFile -Value $content -Encoding utf8

    Write-Log "INFO" "Секреты сгенерированы (.env.local)"
    Write-Log "INFO" "Окружение: $envValue"
}

# =============================================================================
# ШАГ 3: Сборка Docker-образов
# =============================================================================
function Step-BuildImages {
    Write-Log "STEP" "Шаг 3/8 — Сборка Docker-образов"

    Write-Log "INFO" "Сборка образов (первый раз может занять 3-5 минут)..."
    Invoke-Compose @("build", "--parallel")

    Write-Log "INFO" "Docker-образы готовы"
}

# =============================================================================
# ШАГ 4: Запуск контейнеров
# =============================================================================
function Step-StartContainers {
    Write-Log "STEP" "Шаг 4/8 — Запуск контейнеров"

    Invoke-Compose @("up", "-d")

    Write-Log "INFO" "Контейнеры запущены"
    docker ps --format "table {{.Names}}\t{{.Status}}" 2>$null
}

# =============================================================================
# ШАГ 5: Ожидание готовности сервисов
# =============================================================================
function Step-WaitForServices {
    Write-Log "STEP" "Шаг 5/8 — Ожидание готовности сервисов"

    $maxWait = 120

    # PostgreSQL
    Write-Log "INFO" "Ожидание PostgreSQL..."
    $waited = 0
    while ($waited -lt $maxWait) {
        $health = docker inspect --format='{{.State.Health.Status}}' sphere-platform-postgres-1 2>$null
        if ($health -eq "healthy") {
            Write-Log "INFO" "PostgreSQL: ready (${waited}s)"
            break
        }
        Start-Sleep -Seconds 3
        $waited += 3
        Write-Host "    PostgreSQL... ${waited}s / ${maxWait}s" -ForegroundColor Gray -NoNewline
        Write-Host "`r" -NoNewline
    }
    if ($waited -ge $maxWait) {
        Write-Log "ERROR" "PostgreSQL не стал ready за ${maxWait}s"
        exit 1
    }

    # Redis
    Write-Log "INFO" "Ожидание Redis..."
    $waited = 0
    while ($waited -lt $maxWait) {
        $health = docker inspect --format='{{.State.Health.Status}}' sphere-platform-redis-1 2>$null
        if ($health -eq "healthy") {
            Write-Log "INFO" "Redis: ready (${waited}s)"
            break
        }
        Start-Sleep -Seconds 3
        $waited += 3
    }
    if ($waited -ge $maxWait) {
        Write-Log "ERROR" "Redis не стал ready за ${maxWait}s"
        exit 1
    }

    # Backend (HTTP health)
    Write-Log "INFO" "Ожидание Backend..."
    $waited = 0
    while ($waited -lt $maxWait) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
            if ($r.StatusCode -eq 200) {
                Write-Log "INFO" "Backend: ready (${waited}s)"
                break
            }
        } catch { }
        Start-Sleep -Seconds 3
        $waited += 3
    }
    if ($waited -ge $maxWait) {
        Write-Log "WARN" "Backend не ответил за ${maxWait}s — продолжаем"
    }
}

# =============================================================================
# ШАГ 6: Миграции
# =============================================================================
function Step-RunMigrations {
    Write-Log "STEP" "Шаг 6/8 — Миграции базы данных (Alembic)"

    try {
        Invoke-Compose @("exec", "-T", "backend", "alembic", "-c", "alembic/alembic.ini", "upgrade", "head")
        Write-Log "INFO" "Миграции применены"
    } catch {
        Write-Log "WARN" "Миграции через контейнер не прошли — пробуем с хоста..."
        $env:PYTHONPATH = $ProjectDir
        & python -m alembic -c alembic/alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) {
            Write-Log "ERROR" "Миграции провалились"
            exit 1
        }
        Write-Log "INFO" "Миграции применены (с хоста)"
    }
}

# =============================================================================
# ШАГ 7: Инициализация данных
# =============================================================================
function Step-SeedData {
    Write-Log "STEP" "Шаг 7/8 — Инициализация данных"

    $adminEmail = if ($env:SPHERE_ADMIN_EMAIL) { $env:SPHERE_ADMIN_EMAIL } else { "admin@sphere.local" }
    $adminPassword = if ($env:SPHERE_ADMIN_PASSWORD) { $env:SPHERE_ADMIN_PASSWORD } else {
        & python -c "import secrets; print(secrets.token_urlsafe(16))" 2>$null
    }

    Write-Log "INFO" "Создание администратора ($adminEmail)..."

    try {
        Invoke-Compose @("exec", "-T", "backend", "python", "scripts/create_admin.py")
    } catch {
        Write-Log "WARN" "Администратор может уже существовать"
    }

    # Enrollment ключ
    Write-Log "INFO" "Генерация enrollment-ключа..."
    try {
        Invoke-Compose @("exec", "-T", "-e", "AGENT_CONFIG_ENV=development", "backend", "python", "-m", "scripts.seed_enrollment_key")
    } catch {
        Write-Log "WARN" "Enrollment-ключ не сгенерирован"
    }

    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║           УЧЁТНЫЕ ДАННЫЕ АДМИНИСТРАТОРА          ║" -ForegroundColor Green
    Write-Host "  ╠══════════════════════════════════════════════════╣" -ForegroundColor Green
    Write-Host "  ║  Email:    $adminEmail" -ForegroundColor Green
    Write-Host "  ║  Пароль:   $adminPassword" -ForegroundColor Green
    Write-Host "  ╠══════════════════════════════════════════════════╣" -ForegroundColor Green
    Write-Host "  ║  ⚠  СОХРАНИ — пароль не хранится в системе!     ║" -ForegroundColor Yellow
    Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
}

# =============================================================================
# ШАГ 8: Финальная проверка
# =============================================================================
function Step-FinalHealthcheck {
    Write-Log "STEP" "Шаг 8/8 — Финальная проверка"

    $allOk = $true

    # Backend
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -TimeoutSec 5 -UseBasicParsing
        Write-Log "INFO" "Backend API:    ✅ $($r.Content)"
    } catch {
        Write-Log "ERROR" "Backend API:    ❌ Не отвечает"
        $allOk = $false
    }

    # Frontend
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 5 -UseBasicParsing
        Write-Log "INFO" "Frontend:       ✅ Доступен на :3000"
    } catch {
        Write-Log "ERROR" "Frontend:       ❌ Не отвечает"
        $allOk = $false
    }

    # Nginx
    try {
        $null = Invoke-WebRequest -Uri "http://localhost" -TimeoutSec 5 -UseBasicParsing
        Write-Log "INFO" "Nginx Proxy:    ✅ Доступен на :80"
    } catch {
        Write-Log "WARN" "Nginx Proxy:    ⚠  Может ждать SSL"
    }

    # n8n
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:5678" -TimeoutSec 5 -UseBasicParsing
        Write-Log "INFO" "n8n:            ✅ Доступен"
    } catch {
        Write-Log "WARN" "n8n:            ⚠  Не критично"
    }

    # Docker containers
    Write-Host "`n  Контейнеры:" -ForegroundColor Cyan
    docker ps --format "    {{.Names}}: {{.Status}}" 2>$null

    Write-Host ""
    if ($allOk) {
        Write-Host "  ╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Green
        Write-Host "  ║                                                           ║" -ForegroundColor Green
        Write-Host "  ║         🚀 SPHERE PLATFORM РАЗВЁРНУТА УСПЕШНО 🚀          ║" -ForegroundColor Green
        Write-Host "  ║                                                           ║" -ForegroundColor Green
        Write-Host "  ╠═══════════════════════════════════════════════════════════╣" -ForegroundColor Green
        Write-Host "  ║   Web UI:     http://localhost                            ║" -ForegroundColor White
        Write-Host "  ║   API:        http://localhost:8000/api/v1                ║" -ForegroundColor White
        Write-Host "  ║   Swagger:    http://localhost:8000/docs                  ║" -ForegroundColor White
        Write-Host "  ║   n8n:        http://localhost:5678                       ║" -ForegroundColor White
        Write-Host "  ║   MinIO:      http://localhost:9001                       ║" -ForegroundColor White
        Write-Host "  ╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Green
    } else {
        Write-Host "  ⚠  Некоторые сервисы не прошли проверку." -ForegroundColor Yellow
        Write-Host "  Проверь: docker compose logs <service>" -ForegroundColor Yellow
    }

    $elapsed = $StopWatch.Elapsed
    Write-Host "`n  Развёртывание завершено за $($elapsed.Minutes)m $($elapsed.Seconds)s" -ForegroundColor Cyan
}

# =============================================================================
# MAIN
# =============================================================================
Set-Location $ProjectDir

"=== Sphere Platform Deploy — $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ') ===" | Out-File $LogFile -Encoding utf8

Show-Banner

Step-CheckDependencies
Step-GenerateSecrets
Step-BuildImages
Step-StartContainers
Step-WaitForServices
Step-RunMigrations
Step-SeedData
Step-FinalHealthcheck
