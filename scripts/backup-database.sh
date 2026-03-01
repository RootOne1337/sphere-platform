#!/usr/bin/env bash
# =============================================================================
# backup-database.sh — Резервное копирование PostgreSQL + Redis
# =============================================================================
#
# Создаёт полный бэкап базы данных и Redis-снэпшот.
# Поддерживает ротацию бэкапов (по умолчанию хранит 7 последних).
#
# Использование:
#   ./scripts/backup-database.sh              # Полный бэкап в ./backups/
#   ./scripts/backup-database.sh --dir /mnt   # Указать директорию
#   ./scripts/backup-database.sh --keep 14    # Хранить 14 бэкапов
#   ./scripts/backup-database.sh --redis-only # Только Redis
#   ./scripts/backup-database.sh --pg-only    # Только PostgreSQL
#
# Cron-пример (ежедневно в 03:00):
#   0 3 * * * /opt/sphere-platform/scripts/backup-database.sh >> /var/log/sphere-backup.log 2>&1
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Параметры по умолчанию ────────────────────────────────────────────────────
BACKUP_DIR="$PROJECT_DIR/backups"
KEEP_DAYS=7
PG_ONLY=false
REDIS_ONLY=false
PG_CONTAINER="sphere-platform-postgres-1"
REDIS_CONTAINER="sphere-platform-redis-1"
PG_USER="${POSTGRES_USER:-sphere}"
PG_DB="sphereplatform"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

for arg in "$@"; do
    case $arg in
        --dir=*)     BACKUP_DIR="${arg#*=}" ;;
        --keep=*)    KEEP_DAYS="${arg#*=}" ;;
        --pg-only)   PG_ONLY=true ;;
        --redis-only) REDIS_ONLY=true ;;
    esac
done

mkdir -p "$BACKUP_DIR"

echo "═══ Sphere Platform Backup — $TIMESTAMP ═══"

# ── PostgreSQL ────────────────────────────────────────────────────────────────
if ! $REDIS_ONLY; then
    PG_FILE="$BACKUP_DIR/pg_${PG_DB}_${TIMESTAMP}.sql.gz"
    echo "[1] PostgreSQL: dumping $PG_DB..."

    docker exec "$PG_CONTAINER" pg_dump \
        -U "$PG_USER" \
        -d "$PG_DB" \
        --format=plain \
        --no-owner \
        --no-privileges \
        --verbose 2>/dev/null \
    | gzip > "$PG_FILE"

    PG_SIZE=$(du -h "$PG_FILE" | cut -f1)
    echo "    ✅ PostgreSQL: $PG_FILE ($PG_SIZE)"
fi

# ── Redis ─────────────────────────────────────────────────────────────────────
if ! $PG_ONLY; then
    REDIS_FILE="$BACKUP_DIR/redis_snapshot_${TIMESTAMP}.rdb"
    echo "[2] Redis: creating snapshot..."

    # Вызвать BGSAVE и дождаться завершения
    docker exec "$REDIS_CONTAINER" redis-cli -a "${REDIS_PASSWORD:-}" BGSAVE 2>/dev/null || true
    sleep 3

    # Скопировать RDB из контейнера
    docker cp "$REDIS_CONTAINER:/data/dump.rdb" "$REDIS_FILE" 2>/dev/null || \
        docker cp "$REDIS_CONTAINER:/data/appendonly.aof" "${REDIS_FILE%.rdb}.aof" 2>/dev/null || \
        echo "    ⚠  Redis snapshot не скопирован"

    if [[ -f "$REDIS_FILE" ]]; then
        REDIS_SIZE=$(du -h "$REDIS_FILE" | cut -f1)
        echo "    ✅ Redis: $REDIS_FILE ($REDIS_SIZE)"
    fi
fi

# ── Ротация ───────────────────────────────────────────────────────────────────
echo "[3] Ротация: удаление бэкапов старше $KEEP_DAYS дней..."
DELETED=$(find "$BACKUP_DIR" -name "pg_*.sql.gz" -o -name "redis_*" -mtime +"$KEEP_DAYS" -delete -print 2>/dev/null | wc -l)
echo "    Удалено: $DELETED файлов"

# ── Итог ──────────────────────────────────────────────────────────────────────
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
echo ""
echo "═══ Бэкап завершён ═══"
echo "  Директория: $BACKUP_DIR"
echo "  Размер:     $TOTAL_SIZE"
echo "  Ротация:    $KEEP_DAYS дней"
ls -lh "$BACKUP_DIR"/ 2>/dev/null | tail -5
