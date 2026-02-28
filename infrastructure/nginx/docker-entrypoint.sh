#!/bin/sh
# =============================================================================
# Sphere Platform — Nginx entrypoint
# Выполняется при старте контейнера nginx:alpine.
# 1. Если Let's Encrypt сертификата нет — создаёт временный self-signed (nginx
#    не стартует без SSL-файлов). Certbot заменит его при `make ssl-init`.
# 2. Подставляет домен через envsubst (ТОЛЬКО ${SERVER_HOSTNAME}).
# 3. Запускает nginx.
# =============================================================================
set -e

HOSTNAME="${SERVER_HOSTNAME:-localhost}"
CERT_DIR="/etc/letsencrypt/live/${HOSTNAME}"

if [ ! -f "${CERT_DIR}/fullchain.pem" ]; then
    echo "[nginx-init] Сертификат не найден для ${HOSTNAME}. Создаём временный self-signed..."
    mkdir -p "${CERT_DIR}"
    # nginx:alpine не включает openssl — устанавливаем налету (кэшируется в слое контейнера)
    apk add --no-cache openssl >/dev/null 2>&1
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout "${CERT_DIR}/privkey.pem" \
        -out  "${CERT_DIR}/fullchain.pem" \
        -subj "/CN=${HOSTNAME}" 2>/dev/null
    echo "[nginx-init] ВНИМАНИЕ: временный self-signed cert (dev только)."
    echo "[nginx-init] Для прода запустите 'make ssl-init' — получит реальный Let's Encrypt."
fi

# Подставляем ТОЛЬКО ${SERVER_HOSTNAME} — nginx-переменные ($host и т.д.) не трогаем
envsubst '${SERVER_HOSTNAME}' < /tmp/nginx.conf.template > /tmp/nginx.generated.conf

echo "[nginx-init] Запуск nginx | домен=${HOSTNAME}"
exec nginx -c /tmp/nginx.generated.conf -g 'daemon off;'
