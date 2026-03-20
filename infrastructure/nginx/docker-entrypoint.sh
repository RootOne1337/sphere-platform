#!/bin/sh
# =============================================================================
# Sphere Platform -- Nginx entrypoint
# Runs on nginx:alpine container start.
# 1. If Let's Encrypt cert missing -- creates temporary self-signed.
# 2. Substitutes domain via envsubst (ONLY ${SERVER_HOSTNAME}).
# 3. Starts nginx.
# =============================================================================
set -e

HOSTNAME="${SERVER_HOSTNAME:-localhost}"
CERT_DIR="/etc/letsencrypt/live/${HOSTNAME}"

if [ ! -f "${CERT_DIR}/fullchain.pem" ]; then
    echo "[nginx-init] Certificate not found for ${HOSTNAME}. Creating temp self-signed..."
    mkdir -p "${CERT_DIR}"
    apk add --no-cache openssl >/dev/null 2>&1
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout "${CERT_DIR}/privkey.pem" \
        -out  "${CERT_DIR}/fullchain.pem" \
        -subj "/CN=${HOSTNAME}" 2>/dev/null
    echo "[nginx-init] WARNING: temp self-signed cert (dev only)."
    echo "[nginx-init] For prod run 'make ssl-init' to get real Let's Encrypt."
fi

# Substitute ONLY ${SERVER_HOSTNAME} -- nginx variables ($host etc.) untouched
envsubst '${SERVER_HOSTNAME}' < /tmp/nginx.conf.template > /tmp/nginx.generated.conf

echo "[nginx-init] Starting nginx | domain=${HOSTNAME}"
exec nginx -c /tmp/nginx.generated.conf -g 'daemon off;'