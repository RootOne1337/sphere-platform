#!/usr/bin/env pwsh
# =============================================================================
# full-deploy.ps1 — Полное развёртывание Sphere Platform (Windows PowerShell)
# =============================================================================
#
# Скрипт выполняет подготовку и запуск выбранного Compose project:
#   1. Проверка зависимостей (Docker Desktop, Python, Git)
#   2. Генерация криптографических секретов
#   3. Сборка Docker-образов
#   4. Запуск PostgreSQL/Redis и ожидание readiness
#   5. Alembic-миграции в one-off backend container
#   6. Администратор и enrollment key в one-off containers
#   7. Запуск приложений и ожидание Compose running/healthy
#   8. Статус выбранного project (APK/VPN проверяются отдельно)
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
    $ComposeFiles = @("-f", (Join-Path $ProjectDir "docker-compose.yml"), "-f", (Join-Path $ProjectDir "docker-compose.production.yml"))
} else {
    $ComposeFiles = @("-f", (Join-Path $ProjectDir "docker-compose.yml"), "-f", (Join-Path $ProjectDir "docker-compose.full.yml"))
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
    # Match make setup: generated .env.local takes precedence over .env.
    # Let Compose parse dotenv; never execute it or print resolved secrets.
    $selectedEnvFile = @('.env.local', '.env') | ForEach-Object {
        $candidate = Join-Path $ProjectDir $_
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidate }
    } | Select-Object -First 1
    if (-not $selectedEnvFile) {
        throw "No .env.local or .env in the installation directory. Prepare configuration before Compose."
    }
    $allArgs = @('--env-file', $selectedEnvFile) + $ComposeFiles + $Arguments
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

    # The Compose wrapper also accepts .env. Do not shadow an existing
    # installation with new credentials for already initialized volumes.
    if (-not (Test-Path -LiteralPath $envFile) -and
        (Test-Path -LiteralPath (Join-Path $ProjectDir ".env") -PathType Leaf)) {
        Write-Log "INFO" "Используется существующий .env — новые секреты не генерируются"
        return
    }

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
# ШАГ 7: Запуск приложений после bootstrap
# =============================================================================
function Step-StartContainers {
    Write-Log "STEP" "Шаг 7/8 — Запуск приложений после bootstrap"
    Invoke-Compose @("up", "-d", "--wait", "--wait-timeout", "300")
    Write-Log "INFO" "Compose running/healthy достигнуты"
}

# =============================================================================
# ШАГ 4: PostgreSQL и Redis до миграций
# =============================================================================
function Step-WaitForServices {
    Write-Log "STEP" "Шаг 4/8 — PostgreSQL и Redis до миграций"
    Invoke-Compose @("up", "-d", "--wait", "--wait-timeout", "180", "postgres", "redis")
    Write-Log "INFO" "Зависимости готовы в выбранном Compose project"
}

# =============================================================================
# ШАГ 5: Миграции
# =============================================================================
function Step-RunMigrations {
    Write-Log "STEP" "Шаг 5/8 — Миграции до запуска API"
    Invoke-Compose @("run", "--rm", "--no-deps", "-T", "backend", "alembic", "-c", "alembic/alembic.ini", "upgrade", "head")
    Write-Log "INFO" "Миграции применены выбранным backend image/configuration"
}

# =============================================================================
# ШАГ 6: Инициализация данных
# =============================================================================
function Step-SeedData {
    Write-Log "STEP" "Шаг 6/8 — Инициализация данных"

    $adminEmail = if ($env:SPHERE_ADMIN_EMAIL) { $env:SPHERE_ADMIN_EMAIL } else { "admin@example.com" }
    $adminPassword = if ($env:SPHERE_ADMIN_PASSWORD) { $env:SPHERE_ADMIN_PASSWORD } else {
        & python -c "import secrets; print(secrets.token_urlsafe(16))" 2>$null
    }

    Write-Log "INFO" "Создание администратора ($adminEmail)..."

    $previousAdminEmail = $env:ADMIN_EMAIL
    $previousAdminPassword = $env:ADMIN_PASSWORD
    $bootstrapOrgEnv = @()
    if ($env:SPHERE_BOOTSTRAP_ORG_SLUG) { $bootstrapOrgEnv = @('-e', 'SPHERE_BOOTSTRAP_ORG_SLUG') }
    try {
        $env:ADMIN_EMAIL = $adminEmail
        $env:ADMIN_PASSWORD = $adminPassword
        $adminOutput = @(Invoke-Compose (@("run", "--rm", "--no-deps", "-T", "-e", "ADMIN_EMAIL", "-e", "ADMIN_PASSWORD") + $bootstrapOrgEnv + @("backend", "python", "scripts/create_admin.py", "--create-only")))
    } finally {
        $env:ADMIN_EMAIL = $previousAdminEmail
        $env:ADMIN_PASSWORD = $previousAdminPassword
    }

    $adminOutput | ForEach-Object { Write-Host $_ }
    $outcomes = @($adminOutput | Where-Object {
        $_ -in @('SPHERE_ADMIN_BOOTSTRAP=created', 'SPHERE_ADMIN_BOOTSTRAP=existing')
    })
    if ($outcomes.Count -ne 1) {
        throw "Admin bootstrap returned no unambiguous committed outcome; candidate credentials are not confirmed"
    }
    if ($outcomes[0] -eq 'SPHERE_ADMIN_BOOTSTRAP=created') {
        Write-Log "INFO" "Новый администратор сохранён; остальные этапы bootstrap ещё выполняются"
        Write-Host ""
        Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
        Write-Host "  ║           УЧЁТНЫЕ ДАННЫЕ АДМИНИСТРАТОРА          ║" -ForegroundColor Green
        Write-Host "  ╠══════════════════════════════════════════════════╣" -ForegroundColor Green
        Write-Host "  ║  Email:    $adminEmail" -ForegroundColor Green
        Write-Host "  ║  Пароль:   $adminPassword" -ForegroundColor Green
        Write-Host "  ╠══════════════════════════════════════════════════╣" -ForegroundColor Green
        Write-Host "  ║  Сохраните пароль нового администратора         ║" -ForegroundColor Yellow
        Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
        Write-Host ""
    } else {
        Write-Log "INFO" "Администратор уже существует — пароль и настройки сохранены; используйте прежние учётные данные"
    }

    # Enrollment ключ
    Write-Log "INFO" "Генерация enrollment-ключа..."
    Invoke-Compose (@("run", "--rm", "--no-deps", "-T") + $bootstrapOrgEnv + @("backend", "python", "-m", "scripts.seed_enrollment_key"))
}

# =============================================================================
# ШАГ 8: Финальная проверка
# =============================================================================
function Step-FinalHealthcheck {
    Write-Log "STEP" "Шаг 8/8 — Статус выбранного Compose project"
    Invoke-Compose @("ps", "--all")
    Write-Log "INFO" "Schema/bootstrap завершены; Compose readiness пройдена"
    Write-Host "  Следующая проверка: вход в веб, регистрация APK и задание с результатом."
    Write-Host "  Адреса и ограничения: docs/operations/STARTUP.md"
    $elapsed = $StopWatch.Elapsed
    Write-Host "  Подготовка и запуск завершены за $($elapsed.Minutes)m $($elapsed.Seconds)s"
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
Step-WaitForServices
Step-RunMigrations
Step-SeedData
Step-StartContainers
Step-FinalHealthcheck
