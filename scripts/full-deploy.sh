#!/usr/bin/env bash
# =============================================================================
# full-deploy.sh — Полное развёртывание Sphere Platform с нуля
# =============================================================================
#
# Скрипт автоматизирует ВСЕ шаги от клонирования до работающей системы:
#   1. Проверка зависимостей (Docker, Python, Git)
#   2. Генерация криптографических секретов
#   3. Сборка и запуск Docker-контейнеров
#   4. Ожидание готовности PostgreSQL и Redis
#   5. Применение миграций базы данных (Alembic)
#   6. Создание суперадминистратора
#   7. Генерация enrollment-ключа для агентов
#   8. Health-check всех сервисов
#
# Использование:
#   chmod +x scripts/full-deploy.sh
#   ./scripts/full-deploy.sh              # Интерактивный режим
#   ./scripts/full-deploy.sh --headless   # Автоматический (CI/CD)
#   ./scripts/full-deploy.sh --production # Production-режим
#
# Окружение:
#   SPHERE_ADMIN_EMAIL    — Email администратора (по умолчанию: admin@sphere.local)
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
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.full.yml"
MAX_WAIT=120          # Максимальное ожидание готовности сервисов (секунды)
HEALTH_RETRIES=30     # Количество попыток health-check

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
    COMPOSE_FILES="-f docker-compose.yml -f docker-compose.production.yml"
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

    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES build --parallel 2>&1 | tee -a "$LOG_FILE"
    if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
        die "Сборка Docker-образов провалилась. Проверь Dockerfile-ы и логи"
    fi

    log INFO "Docker-образы готовы"
}

# =============================================================================
# ШАГ 4: Запуск контейнеров
# =============================================================================
start_containers() {
    log STEP "Шаг 4/8 — Запуск контейнеров"

    cd "$PROJECT_DIR"

    # Загрузить .env.local
    if [[ -f .env.local ]]; then
        set -a
        # shellcheck disable=SC1091
        source .env.local
        set +a
    fi

    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES up -d 2>&1 | tee -a "$LOG_FILE"
    if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
        die "Не удалось запустить контейнеры"
    fi

    log INFO "Контейнеры запущены"
    docker compose $COMPOSE_FILES ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || true
}

# =============================================================================
# ШАГ 5: Ожидание готовности сервисов
# =============================================================================
wait_for_services() {
    log STEP "Шаг 5/8 — Ожидание готовности сервисов"

    # PostgreSQL
    log INFO "Ожидание PostgreSQL..."
    local waited=0
    while (( waited < MAX_WAIT )); do
        if docker compose $COMPOSE_FILES exec -T postgres pg_isready -U "${POSTGRES_USER:-sphere}" &>/dev/null; then
            log INFO "PostgreSQL: ready (${waited}s)"
            break
        fi
        sleep 2
        waited=$((waited + 2))
        echo -ne "\r    Ожидание PostgreSQL... ${waited}s / ${MAX_WAIT}s"
    done
    echo ""
    if (( waited >= MAX_WAIT )); then
        die "PostgreSQL не стал ready за ${MAX_WAIT}s"
    fi

    # Redis
    log INFO "Ожидание Redis..."
    waited=0
    while (( waited < MAX_WAIT )); do
        if docker compose $COMPOSE_FILES exec -T redis redis-cli -a "${REDIS_PASSWORD:-}" ping 2>/dev/null | grep -q PONG; then
            log INFO "Redis: ready (${waited}s)"
            break
        fi
        sleep 2
        waited=$((waited + 2))
        echo -ne "\r    Ожидание Redis... ${waited}s / ${MAX_WAIT}s"
    done
    echo ""
    if (( waited >= MAX_WAIT )); then
        die "Redis не стал ready за ${MAX_WAIT}s"
    fi

    # Backend
    log INFO "Ожидание Backend..."
    waited=0
    while (( waited < MAX_WAIT )); do
        if curl -sf http://localhost:8000/api/v1/health &>/dev/null; then
            log INFO "Backend: ready (${waited}s)"
            break
        fi
        sleep 3
        waited=$((waited + 3))
        echo -ne "\r    Ожидание Backend... ${waited}s / ${MAX_WAIT}s"
    done
    echo ""
    if (( waited >= MAX_WAIT )); then
        log WARN "Backend не отвечает на /health за ${MAX_WAIT}s — продолжаем (возможно первый запуск)"
    fi
}

# =============================================================================
# ШАГ 6: Миграции базы данных
# =============================================================================
run_migrations() {
    log STEP "Шаг 6/8 — Миграции базы данных (Alembic)"

    cd "$PROJECT_DIR"

    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES exec -T backend \
        alembic -c alembic/alembic.ini upgrade head 2>&1 | tee -a "$LOG_FILE"

    if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
        log WARN "Миграции через контейнер не прошли — пробуем с хоста..."
        local python_cmd="python3"
        command -v python3 &>/dev/null || python_cmd="python"
        PYTHONPATH="$PROJECT_DIR" $python_cmd -m alembic -c alembic/alembic.ini upgrade head 2>&1 | tee -a "$LOG_FILE"
        if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
            die "Миграции провалились. Проверь POSTGRES_URL и подключение к БД"
        fi
    fi

    log INFO "Миграции применены успешно"
}

# =============================================================================
# ШАГ 7: Инициализация данных
# =============================================================================
seed_data() {
    log STEP "Шаг 7/8 — Инициализация данных"

    cd "$PROJECT_DIR"

    # Создание суперадминистратора
    local admin_email="${SPHERE_ADMIN_EMAIL:-admin@sphere.local}"
    local admin_password="${SPHERE_ADMIN_PASSWORD:-}"

    if [[ -z "$admin_password" ]]; then
        admin_password=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || \
                         python -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || \
                         openssl rand -base64 16 2>/dev/null || \
                         echo "SphereAdmin$(date +%s)")
    fi

    log INFO "Создание администратора ($admin_email)..."

    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES exec -T backend python -c "
import asyncio, sys, os
sys.path.insert(0, '/app')
os.environ.setdefault('ENVIRONMENT', 'development')

async def create():
    from backend.database.engine import async_session_factory
    from backend.models.user import User
    from backend.core.security import get_password_hash
    from sqlalchemy import select
    
    async with async_session_factory() as session:
        existing = await session.execute(select(User).where(User.email == '$admin_email'))
        if existing.scalar_one_or_none():
            print('Администратор уже существует — пропускаем')
            return
        
        user = User(
            email='$admin_email',
            username='admin',
            hashed_password=get_password_hash('$admin_password'),
            is_active=True,
            is_superuser=True,
            role='super_admin',
        )
        session.add(user)
        await session.commit()
        print(f'Администратор создан: $admin_email')

asyncio.run(create())
" 2>&1 | tee -a "$LOG_FILE" || log WARN "Не удалось создать администратора (возможно, уже существует)"

    # Enrollment-ключ для агентов
    log INFO "Генерация enrollment-ключа..."
    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES exec -T -e AGENT_CONFIG_ENV="${SPHERE_ENV:-development}" backend \
        python -m scripts.seed_enrollment_key 2>&1 | tee -a "$LOG_FILE" || \
        log WARN "Enrollment-ключ не сгенерирован (может уже существовать)"

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
    log STEP "Шаг 8/8 — Финальная проверка"

    local all_ok=true

    # Backend API
    if curl -sf http://localhost:8000/api/v1/health -o /dev/null; then
        local health_json
        health_json=$(curl -sf http://localhost:8000/api/v1/health)
        log INFO "Backend API:    ✅ $health_json"
    else
        log ERROR "Backend API:    ❌ Не отвечает на /api/v1/health"
        all_ok=false
    fi

    # Frontend
    if curl -sf http://localhost:3000 -o /dev/null; then
        log INFO "Frontend:       ✅ Доступен на :3000"
    else
        log ERROR "Frontend:       ❌ Не отвечает на :3000"
        all_ok=false
    fi

    # Nginx (proxy)
    if curl -sf http://localhost -o /dev/null; then
        log INFO "Nginx Proxy:    ✅ Доступен на :80"
    else
        log WARN "Nginx Proxy:    ⚠  Не отвечает (может ждать SSL)"
    fi

    # PostgreSQL
    # shellcheck disable=SC2086
    if docker compose $COMPOSE_FILES exec -T postgres pg_isready -U "${POSTGRES_USER:-sphere}" &>/dev/null; then
        log INFO "PostgreSQL:     ✅ Ready"
    else
        log ERROR "PostgreSQL:     ❌ Не готов"
        all_ok=false
    fi

    # Redis
    # shellcheck disable=SC2086
    if docker compose $COMPOSE_FILES exec -T redis redis-cli -a "${REDIS_PASSWORD:-}" ping 2>/dev/null | grep -q PONG; then
        log INFO "Redis:          ✅ PONG"
    else
        log ERROR "Redis:          ❌ Не отвечает"
        all_ok=false
    fi

    # n8n
    if curl -sf http://localhost:5678 -o /dev/null; then
        log INFO "n8n:            ✅ Доступен на :5678"
    else
        log WARN "n8n:            ⚠  Не отвечает (не критично)"
    fi

    # MinIO
    if curl -sf http://localhost:9001 -o /dev/null; then
        log INFO "MinIO Console:  ✅ Доступен на :9001"
    else
        log WARN "MinIO Console:  ⚠  Не отвечает (не критично)"
    fi

    # Swagger
    if curl -sf http://localhost:8000/docs -o /dev/null; then
        log INFO "Swagger UI:     ✅ Доступен на /docs"
    fi

    echo ""
    if $all_ok; then
        echo -e "${GREEN}${BOLD}"
        echo "  ╔═══════════════════════════════════════════════════════════╗"
        echo "  ║                                                           ║"
        echo "  ║          🚀 SPHERE PLATFORM РАЗВЁРНУТА УСПЕШНО 🚀          ║"
        echo "  ║                                                           ║"
        echo "  ╠═══════════════════════════════════════════════════════════╣"
        echo "  ║                                                           ║"
        echo "  ║   🖥  Web UI:     http://localhost                         ║"
        echo "  ║   📡 API:        http://localhost:8000/api/v1             ║"
        echo "  ║   📖 Swagger:    http://localhost:8000/docs               ║"
        echo "  ║   📊 Grafana:    http://localhost:3001                    ║"
        echo "  ║   🔗 n8n:        http://localhost:5678                    ║"
        echo "  ║   💾 MinIO:      http://localhost:9001                    ║"
        echo "  ║                                                           ║"
        echo "  ╚═══════════════════════════════════════════════════════════╝"
        echo -e "${NC}"
    else
        echo -e "${YELLOW}${BOLD}"
        echo "  ══════════════════════════════════════════════════════════"
        echo "  ⚠  Некоторые сервисы не прошли проверку."
        echo "  Проверь логи: docker compose logs <service>"
        echo "  Или посмотри: $LOG_FILE"
        echo "  ══════════════════════════════════════════════════════════"
        echo -e "${NC}"
    fi

    echo "  Лог развёртывания: $LOG_FILE"
    echo ""
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
    start_containers
    wait_for_services
    run_migrations
    seed_data
    final_healthcheck

    echo -e "${CYAN}Развёртывание завершено за $SECONDS секунд.${NC}"
}

main "$@"
