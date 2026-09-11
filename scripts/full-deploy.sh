#!/usr/bin/env bash
# =============================================================================
# full-deploy.sh — Полное развёртывание Sphere Platform с нуля
# =============================================================================
#
# Скрипт выполняет подготовку и запуск выбранного Compose project:
#   1. Проверка зависимостей (Docker, Python, Git)
#   2. Генерация криптографических секретов
#   3. Сборка Docker-образов
#   4. Запуск PostgreSQL/Redis и ожидание readiness
#   5. Alembic-миграции в one-off backend container
#   6. Администратор и enrollment key в one-off containers
#   7. Запуск приложений и ожидание Compose running/healthy
#   8. Статус выбранного project (APK/VPN проверяются отдельно)
#
# Использование:
#   chmod +x scripts/full-deploy.sh
#   ./scripts/full-deploy.sh              # Интерактивный режим
#   ./scripts/full-deploy.sh --headless   # Автоматический (CI/CD)
#   ./scripts/full-deploy.sh --production # Production-режим
#
# Окружение:
#   SPHERE_ADMIN_EMAIL    — Email администратора (по умолчанию: admin@example.com)
#   SPHERE_ADMIN_PASSWORD — Пароль администратора (генерируется автоматически)
#   SPHERE_ENV            — Окружение: development|staging|production
#
# Автор: Sphere Platform Team
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ── Цвета и форматирование ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Константы ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/.deploy.log"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.full.yml)

# ── Режимы ────────────────────────────────────────────────────────────────────
HEADLESS=false
PRODUCTION=false
SKIP_SECRETS=false

for arg in "$@"; do
    case $arg in
        --headless)    HEADLESS=true ;;
        --production)  PRODUCTION=true ;;
        --skip-secrets) SKIP_SECRETS=true ;;
        --help|-h)
            echo "Использование: $0 [--headless] [--production] [--skip-secrets]"
            echo ""
            echo "  --headless      Автоматический режим без интерактивных запросов"
            echo "  --production    Production-режим (resource limits, no debug)"
            echo "  --skip-secrets  Не генерировать секреты (использовать существующие)"
            exit 0 ;;
        *) echo "Неизвестный аргумент: $arg"; exit 1 ;;
    esac
done

if $PRODUCTION; then
    COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.production.yml)
fi

# ── Логирование ───────────────────────────────────────────────────────────────
log() {
    local level="$1"; shift
    local msg="$*"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] [$level] $msg" >> "$LOG_FILE"
    case $level in
        INFO)  echo -e "${GREEN}[✓]${NC} $msg" ;;
        WARN)  echo -e "${YELLOW}[!]${NC} $msg" ;;
        ERROR) echo -e "${RED}[✗]${NC} $msg" ;;
        STEP)  echo -e "\n${CYAN}${BOLD}═══ $msg ═══${NC}" ;;
        *)     echo -e "    $msg" ;;
    esac
}

die() {
    log ERROR "$1"
    echo -e "${RED}Подробности в: $LOG_FILE${NC}"
    exit 1
}

# ── Баннер ────────────────────────────────────────────────────────────────────
banner() {
    echo -e "${CYAN}"
    echo "  ╔═══════════════════════════════════════════════════════════╗"
    echo "  ║                                                           ║"
    echo "  ║         ● SPHERE PLATFORM — Full Deployment ●             ║"
    echo "  ║                                                           ║"
    echo "  ║   Enterprise Android Device Management & Automation       ║"
    echo "  ║                                                           ║"
    echo "  ╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  Версия:   $(cat "$PROJECT_DIR/VERSION" 2>/dev/null || echo 'unknown')"
    echo -e "  Режим:    $(if $PRODUCTION; then echo 'PRODUCTION'; else echo 'DEVELOPMENT'; fi)"
    echo -e "  Дата:     $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo ""
}

# =============================================================================
# ШАГ 1: Проверка зависимостей
# =============================================================================
check_dependencies() {
    log STEP "Шаг 1/8 — Проверка зависимостей"

    # Docker
    if ! command -v docker &>/dev/null; then
        die "Docker не установлен. Установи: https://docs.docker.com/get-docker/"
    fi
    local docker_version
    docker_version=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "not running")
    if [[ "$docker_version" == "not running" ]]; then
        die "Docker daemon не запущен. Запусти Docker Desktop / systemctl start docker"
    fi
    log INFO "Docker: v$docker_version"

    # Docker Compose V2
    if docker compose version &>/dev/null; then
        local compose_version
        compose_version=$(docker compose version --short 2>/dev/null)
        log INFO "Docker Compose: v$compose_version"
    else
        die "Docker Compose V2 не найден. Обнови Docker Desktop или установи docker-compose-plugin"
    fi

    # Python 3.11+
    if command -v python3 &>/dev/null; then
        local py_version
        py_version=$(python3 --version 2>&1 | cut -d' ' -f2)
        log INFO "Python: v$py_version"
    elif command -v python &>/dev/null; then
        local py_version
        py_version=$(python --version 2>&1 | cut -d' ' -f2)
        log INFO "Python: v$py_version"
    else
        log WARN "Python не найден — скрипты секретов нужно запустить вручную"
    fi

    # Git
    if command -v git &>/dev/null; then
        log INFO "Git: $(git --version | cut -d' ' -f3)"
    fi

    # Свободное место
    local free_gb
    free_gb=$(df -BG "$PROJECT_DIR" 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G')
    if [[ -n "$free_gb" ]] && (( free_gb < 10 )); then
        log WARN "Мало места на диске: ${free_gb}GB (рекомендуется 20+ GB)"
    fi

    # Docker socket
    if ! docker info &>/dev/null; then
        die "Нет доступа к Docker socket. Проверь права: sudo usermod -aG docker \$USER"
    fi
    log INFO "Docker daemon: доступен"
}

# =============================================================================
# ШАГ 2: Генерация секретов
# =============================================================================
generate_secrets() {
    log STEP "Шаг 2/8 — Генерация секретов"

    cd "$PROJECT_DIR"

    # Compose already accepts .env; a new .env.local would shadow credentials
    # belonging to initialized PostgreSQL/Redis and other persistent services.
    if [[ ! -e .env.local && -f .env ]]; then
        log INFO "Используется существующий .env — новые секреты не генерируются"
        return
    fi

    if [[ -f .env.local ]] && $SKIP_SECRETS; then
        log INFO "Секреты уже существуют (.env.local) — пропускаем"
        return
    fi

    if [[ -f .env.local ]]; then
        if $HEADLESS; then
            log INFO "Секреты уже существуют (.env.local) — пропускаем (headless)"
            return
        fi
        echo -en "${YELLOW}[!] .env.local уже существует. Перезаписать? [y/N]: ${NC}"
        read -r answer
        if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
            log INFO "Секреты сохранены без изменений"
            return
        fi
        cp .env.local ".env.local.backup.$(date +%s)"
        log INFO "Бэкап создан: .env.local.backup.*"
    fi

    local python_cmd="python3"
    command -v python3 &>/dev/null || python_cmd="python"

    $python_cmd scripts/generate_secrets.py --output .env.local 2>&1 | tee -a "$LOG_FILE"
    if [[ $? -ne 0 ]]; then
        die "Не удалось сгенерировать секреты"
    fi

    # Установить окружение
    local env_value="${SPHERE_ENV:-development}"
    if $PRODUCTION; then
        env_value="production"
    fi
    sed -i.bak "s/^ENVIRONMENT=.*/ENVIRONMENT=$env_value/" .env.local 2>/dev/null || true
    rm -f .env.local.bak

    log INFO "Секреты сгенерированы в .env.local ($(wc -l < .env.local) строк)"
    log INFO "Окружение: $env_value"
}

# =============================================================================
# ШАГ 3: Сборка Docker-образов
# =============================================================================
build_images() {
    log STEP "Шаг 3/8 — Сборка Docker-образов"

    cd "$PROJECT_DIR"

    # Загрузить .env.local для docker compose
    if [[ -f .env.local ]]; then
        set -a
        # shellcheck disable=SC1091
        source .env.local
        set +a
    fi

    log INFO "Сборка образов (первый раз может занять 3-5 минут)..."

    docker compose "${COMPOSE_FILES[@]}" build --parallel 2>&1 | tee -a "$LOG_FILE"
    if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
        die "Сборка Docker-образов провалилась. Проверь Dockerfile-ы и логи"
    fi

    log INFO "Docker-образы готовы"
}

# =============================================================================
# ШАГ 7: Запуск приложений после bootstrap
# =============================================================================
start_containers() {
    log STEP "Шаг 7/8 — Запуск приложений после bootstrap"
    cd "$PROJECT_DIR"
    docker compose "${COMPOSE_FILES[@]}" up -d --wait --wait-timeout 300 2>&1 | tee -a "$LOG_FILE" || return 1
    log INFO "Compose running/healthy достигнуты"
}

# =============================================================================
# ШАГ 4: PostgreSQL и Redis до миграций
# =============================================================================
wait_for_services() {
    log STEP "Шаг 4/8 — PostgreSQL и Redis до миграций"
    cd "$PROJECT_DIR"
    docker compose "${COMPOSE_FILES[@]}" up -d --wait --wait-timeout 180 postgres redis 2>&1 | tee -a "$LOG_FILE" || return 1
    log INFO "Зависимости готовы в выбранном Compose project"
}

# =============================================================================
# ШАГ 5: Миграции базы данных
# =============================================================================
run_migrations() {
    log STEP "Шаг 5/8 — Миграции до запуска API"
    cd "$PROJECT_DIR"
    docker compose "${COMPOSE_FILES[@]}" run --rm --no-deps -T backend \
        alembic -c alembic/alembic.ini upgrade head 2>&1 | tee -a "$LOG_FILE" || return 1
    log INFO "Миграции применены выбранным backend image/configuration"
}

# =============================================================================
# ШАГ 6: Инициализация данных
# =============================================================================
seed_data() {
    log STEP "Шаг 6/8 — Инициализация данных"

    cd "$PROJECT_DIR"

    # Создание суперадминистратора
    local admin_email="${SPHERE_ADMIN_EMAIL:-admin@example.com}"
    local admin_password="${SPHERE_ADMIN_PASSWORD:-}"

    if [[ -z "$admin_password" ]]; then
        admin_password=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || \
                         python -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || \
                         openssl rand -base64 16 2>/dev/null || \
                         echo "SphereAdmin$(date +%s)")
    fi

    log INFO "Создание администратора ($admin_email)..."

    # Forward values through the process environment, not inline Python/argv.
    local -a bootstrap_org_env=()
    if [[ -n "${SPHERE_BOOTSTRAP_ORG_SLUG:-}" ]]; then
        bootstrap_org_env=(-e SPHERE_BOOTSTRAP_ORG_SLUG)
    fi
    ADMIN_EMAIL="$admin_email" ADMIN_PASSWORD="$admin_password" \
        docker compose "${COMPOSE_FILES[@]}" run --rm --no-deps -T -e ADMIN_EMAIL -e ADMIN_PASSWORD "${bootstrap_org_env[@]}" backend \
        python scripts/create_admin.py 2>&1 | tee -a "$LOG_FILE" || return 1

    log INFO "Генерация enrollment-ключа..."
    # Use the backend's configured environment; never force a development key.
    docker compose "${COMPOSE_FILES[@]}" run --rm --no-deps -T "${bootstrap_org_env[@]}" backend \
        python -m scripts.seed_enrollment_key 2>&1 | tee -a "$LOG_FILE" || return 1

    # Вывод учётных данных
    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║           УЧЁТНЫЕ ДАННЫЕ АДМИНИСТРАТОРА          ║${NC}"
    echo -e "${GREEN}${BOLD}╠══════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}${BOLD}║  Email:    ${NC}$admin_email"
    echo -e "${GREEN}${BOLD}║  Пароль:   ${NC}$admin_password"
    echo -e "${GREEN}${BOLD}╠══════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}${BOLD}║  ⚠  СОХРАНИ ПАРОЛЬ — он не хранится в системе!  ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
    echo ""

    # Сохранить в файл (gitignored)
    cat > "$PROJECT_DIR/.admin-credentials" <<EOF
# Sphere Platform — Admin Credentials
# Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
# NEVER COMMIT THIS FILE
ADMIN_EMAIL=$admin_email
ADMIN_PASSWORD=$admin_password
EOF
    chmod 600 "$PROJECT_DIR/.admin-credentials"
    log INFO "Учётные данные сохранены в .admin-credentials"
}

# =============================================================================
# ШАГ 8: Финальная проверка
# =============================================================================
final_healthcheck() {
    log STEP "Шаг 8/8 — Статус выбранного Compose project"
    docker compose "${COMPOSE_FILES[@]}" ps --all 2>&1 | tee -a "$LOG_FILE" || return 1
    log INFO "Schema/bootstrap завершены; Compose readiness пройдена"
    echo "  Следующая проверка: вход в веб, регистрация APK и задание с результатом."
    echo "  Адреса и ограничения: docs/operations/STARTUP.md"
    echo "  Лог подготовки и запуска: $LOG_FILE"
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    cd "$PROJECT_DIR"

    # Инициализация лога
    echo "=== Sphere Platform Deploy — $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" > "$LOG_FILE"

    banner

    check_dependencies
    generate_secrets
    build_images
    wait_for_services
    run_migrations
    seed_data
    start_containers
    final_healthcheck

    echo -e "${CYAN}Развёртывание завершено за $SECONDS секунд.${NC}"
}

main "$@"
