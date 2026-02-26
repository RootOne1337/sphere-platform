#!/bin/bash
# =============================================================================
# Sphere Platform — Первичное получение Let's Encrypt сертификата
# =============================================================================
# Использование:  bash scripts/init_ssl.sh
# Или через make: make ssl-init
#
# Что делает:
#   1. Читает SERVER_HOSTNAME и ACME_EMAIL из .env
#   2. Останавливает nginx (освобождает порт 80 для certbot standalone)
#   3. Certbot получает сертификат через HTTP-01 challenge (standalone mode)
#   4. Перезапускает nginx — он найдёт реальный сертификат от LE
#
# Требования:
#   - DNS A-запись для SERVER_HOSTNAME должна указывать на IP этого сервера
#   - Порт 80 должен быть открыт в firewall
#   - Docker и docker compose должны быть установлены
# =============================================================================
set -euo pipefail

# ── Загрузка переменных окружения ─────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "[ssl-init] ОШИБКА: файл .env не найден. Запусти из корня проекта." >&2
    exit 1
fi
# shellcheck source=/dev/null
source .env

DOMAIN="${SERVER_HOSTNAME:?Не задана переменная SERVER_HOSTNAME в .env}"
EMAIL="${ACME_EMAIL:?Не задана переменная ACME_EMAIL в .env}"
COMPOSE_FILES="-f docker-compose.yml"

echo "============================================================"
echo " Sphere Platform — получение SSL сертификата"
echo " Домен : ${DOMAIN}"
echo " Email  : ${EMAIL}"
echo "============================================================"

# ── Проверка DNS ──────────────────────────────────────────────────────────────
echo "[ssl-init] Проверяем DNS для ${DOMAIN}..."
if ! nslookup "${DOMAIN}" 1.1.1.1 >/dev/null 2>&1; then
    echo "[ssl-init] ПРЕДУПРЕЖДЕНИЕ: DNS-разрешение для ${DOMAIN} не прошло."
    echo "           Убедись что A-запись настроена и propagated."
fi

# ── Остановка nginx (standalone mode занимает порт 80) ────────────────────────
echo "[ssl-init] Останавливаем nginx..."
docker compose ${COMPOSE_FILES} stop nginx 2>/dev/null || true

# ── Получение сертификата через certbot standalone ───────────────────────────
echo "[ssl-init] Запускаем certbot для получения сертификата..."
docker run --rm \
    -v certbot-data:/etc/letsencrypt \
    -p 80:80 \
    certbot/certbot:latest certonly \
        --standalone \
        --non-interactive \
        --agree-tos \
        --email "${EMAIL}" \
        --domains "${DOMAIN}" \
        --rsa-key-size 4096

echo "[ssl-init] Сертификат успешно получен!"
echo "[ssl-init] Файлы сохранены в Docker volume certbot-data"

# ── Перезапуск nginx с реальным сертификатом ─────────────────────────────────
echo "[ssl-init] Перезапускаем nginx с реальным Let's Encrypt сертификатом..."
docker compose ${COMPOSE_FILES} up -d nginx

echo ""
echo "============================================================"
echo " Готово! HTTPS работает на https://${DOMAIN}"
echo " Автообновление: certbot service делает renew каждые 12 ч."
echo " Ручное обновление: make ssl-renew"
echo "============================================================"
