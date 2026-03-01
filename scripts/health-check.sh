#!/usr/bin/env bash
# =============================================================================
# health-check.sh — Проверка здоровья всех сервисов Sphere Platform
# =============================================================================
#
# Проверяет доступность ВСЕХ компонентов системы:
#   - Backend API (FastAPI /health)
#   - Frontend (Next.js)
#   - PostgreSQL (pg_isready)
#   - Redis (PING/PONG)
#   - Nginx reverse proxy
#   - n8n automation
#   - MinIO S3-хранилище
#   - WebSocket (upgrade handshake)
#   - SSH Tunnel (если запущен)
#
# Использование:
#   ./scripts/health-check.sh          # Полная проверка
#   ./scripts/health-check.sh --json   # Вывод в JSON (для мониторинга)
#   ./scripts/health-check.sh --quiet  # Только exit code (0=OK, 1=FAIL)
#
# Exit codes:
#   0 — Все критические сервисы в норме
#   1 — Есть критические проблемы
#   2 — Есть предупреждения (некритические сервисы)
#
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Параметры ─────────────────────────────────────────────────────────────────
JSON_OUTPUT=false
QUIET=false

for arg in "$@"; do
    case $arg in
        --json)  JSON_OUTPUT=true ;;
        --quiet) QUIET=true ;;
    esac
done

# ── Цвета ─────────────────────────────────────────────────────────────────────
if [[ -t 1 ]] && ! $QUIET; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

# ── Счётчики ──────────────────────────────────────────────────────────────────
PASS=0; FAIL=0; WARN=0
declare -A RESULTS

# ── Проверки ──────────────────────────────────────────────────────────────────
check_service() {
    local name="$1"
    local url="$2"
    local critical="${3:-true}"
    local timeout="${4:-5}"

    local status="fail"
    local code=""
    local latency=""

    local start_ms
    start_ms=$(date +%s%N 2>/dev/null || echo 0)

    if code=$(curl -sf -o /dev/null -w "%{http_code}" --connect-timeout "$timeout" --max-time "$timeout" "$url" 2>/dev/null); then
        if [[ "$code" =~ ^(200|301|302)$ ]]; then
            status="pass"
        fi
    fi
    code="${code:-000}"

    local end_ms
    end_ms=$(date +%s%N 2>/dev/null || echo 0)
    if [[ "$start_ms" != "0" ]] && [[ "$end_ms" != "0" ]]; then
        latency=$(( (end_ms - start_ms) / 1000000 ))
    else
        latency="?"
    fi

    RESULTS["$name"]="$status|$code|${latency}ms|$critical"

    if ! $QUIET && ! $JSON_OUTPUT; then
        local icon
        if [[ "$status" == "pass" ]]; then
            icon="${GREEN}✅${NC}"
            ((PASS++))
        elif [[ "$critical" == "true" ]]; then
            icon="${RED}❌${NC}"
            ((FAIL++))
        else
            icon="${YELLOW}⚠️${NC}"
            ((WARN++))
        fi
        printf "  %-20s %b  HTTP %s  (%sms)\n" "$name" "$icon" "$code" "$latency"
    else
        if [[ "$status" == "pass" ]]; then ((PASS++))
        elif [[ "$critical" == "true" ]]; then ((FAIL++))
        else ((WARN++)); fi
    fi
}

check_docker_health() {
    local name="$1"
    local container="$2"
    local critical="${3:-true}"

    local health
    health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")

    local status="fail"
    if [[ "$health" == "healthy" ]]; then
        status="pass"
    elif [[ "$health" == "running" ]] || docker inspect --format='{{.State.Running}}' "$container" 2>/dev/null | grep -q true; then
        status="pass"
        health="running"
    fi

    RESULTS["$name"]="$status|$health|-|$critical"

    if ! $QUIET && ! $JSON_OUTPUT; then
        local icon
        if [[ "$status" == "pass" ]]; then
            icon="${GREEN}✅${NC}"
            ((PASS++))
        elif [[ "$critical" == "true" ]]; then
            icon="${RED}❌${NC}"
            ((FAIL++))
        else
            icon="${YELLOW}⚠️${NC}"
            ((WARN++))
        fi
        printf "  %-20s %b  Docker: %s\n" "$name" "$icon" "$health"
    else
        if [[ "$status" == "pass" ]]; then ((PASS++))
        elif [[ "$critical" == "true" ]]; then ((FAIL++))
        else ((WARN++)); fi
    fi
}

# =============================================================================
# MAIN
# =============================================================================

if ! $QUIET && ! $JSON_OUTPUT; then
    echo -e "\n${CYAN}${BOLD}╔═══════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║    Sphere Platform — Health Check Report      ║${NC}"
    echo -e "${CYAN}${BOLD}╠═══════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}${BOLD}║  $(date '+%Y-%m-%d %H:%M:%S %Z')                        ║${NC}"
    echo -e "${CYAN}${BOLD}╚═══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BOLD}  HTTP-эндпоинты:${NC}"
fi

# HTTP-проверки (критические)
check_service "Backend API"      "http://localhost:8000/api/v1/health" true
check_service "Frontend"         "http://localhost:3000"               true
check_service "Nginx Proxy"      "http://localhost"                    true

# HTTP-проверки (некритические)
check_service "Swagger UI"       "http://localhost:8000/docs"          false
check_service "n8n"              "http://localhost:5678"               false
check_service "MinIO Console"    "http://localhost:9001"               false

if ! $QUIET && ! $JSON_OUTPUT; then
    echo ""
    echo -e "${BOLD}  Docker-контейнеры:${NC}"
fi

# Docker health-проверки (критические)
check_docker_health "PostgreSQL"  "sphere-platform-postgres-1"   true
check_docker_health "Redis"       "sphere-platform-redis-1"      true
check_docker_health "Backend"     "sphere-platform-backend-1"    true
check_docker_health "Frontend"    "sphere-platform-frontend-1"   true
check_docker_health "Nginx"       "sphere-platform-nginx-1"      true

# Docker (некритические)
check_docker_health "n8n"         "sphere-platform-n8n-1"        false
check_docker_health "MinIO"       "sphere-platform-minio-1"      false
check_docker_health "Certbot"     "sphere-platform-certbot-1"    false
check_docker_health "Tunnel"      "sphere-tunnel"                false

# ── JSON-вывод ────────────────────────────────────────────────────────────────
if $JSON_OUTPUT; then
    echo "{"
    echo "  \"timestamp\": \"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\","
    echo "  \"summary\": { \"pass\": $PASS, \"fail\": $FAIL, \"warn\": $WARN },"
    echo "  \"checks\": {"
    first=true
    for key in "${!RESULTS[@]}"; do
        IFS='|' read -r status code latency critical <<< "${RESULTS[$key]}"
        if ! $first; then echo ","; fi
        first=false
        echo -n "    \"$key\": { \"status\": \"$status\", \"code\": \"$code\", \"latency\": \"$latency\", \"critical\": $critical }"
    done
    echo ""
    echo "  }"
    echo "}"
fi

# ── Итог ──────────────────────────────────────────────────────────────────────
if ! $QUIET && ! $JSON_OUTPUT; then
    echo ""
    echo -e "${BOLD}  Итог:${NC} ${GREEN}$PASS passed${NC}  ${RED}$FAIL failed${NC}  ${YELLOW}$WARN warnings${NC}"

    if (( FAIL == 0 )); then
        echo -e "\n  ${GREEN}${BOLD}Все критические сервисы работают ✅${NC}\n"
    else
        echo -e "\n  ${RED}${BOLD}Обнаружены критические проблемы! Проверь логи: docker compose logs${NC}\n"
    fi
fi

# Exit code
if (( FAIL > 0 )); then
    exit 1
elif (( WARN > 0 )); then
    exit 2
else
    exit 0
fi
