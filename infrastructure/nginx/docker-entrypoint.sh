#!/bin/sh
# =============================================================================
# Sphere Platform вЂ” Nginx entrypoint
# Р’С‹РїРѕР»РЅСЏРµС‚СЃСЏ РїСЂРё СЃС‚Р°СЂС‚Рµ РєРѕРЅС‚РµР№РЅРµСЂР° nginx:alpine.
# 1. Р•СЃР»Рё Let's Encrypt СЃРµСЂС‚РёС„РёРєР°С‚Р° РЅРµС‚ вЂ” СЃРѕР·РґР°С‘С‚ РІСЂРµРјРµРЅРЅС‹Р№ self-signed (nginx
#    РЅРµ СЃС‚Р°СЂС‚СѓРµС‚ Р±РµР· SSL-С„Р°Р№Р»РѕРІ). Certbot Р·Р°РјРµРЅРёС‚ РµРіРѕ РїСЂРё `make ssl-init`.
# 2. РџРѕРґСЃС‚Р°РІР»СЏРµС‚ РґРѕРјРµРЅ С‡РµСЂРµР· envsubst (РўРћР›Р¬РљРћ ${SERVER_HOSTNAME}).
# 3. Р—Р°РїСѓСЃРєР°РµС‚ nginx.
# =============================================================================
set -e

HOSTNAME="${SERVER_HOSTNAME:-localhost}"
CERT_DIR="/etc/letsencrypt/live/${HOSTNAME}"

if [ ! -f "${CERT_DIR}/fullchain.pem" ]; then
    echo "[nginx-init] РЎРµСЂС‚РёС„РёРєР°С‚ РЅРµ РЅР°Р№РґРµРЅ РґР»СЏ ${HOSTNAME}. РЎРѕР·РґР°С‘Рј РІСЂРµРјРµРЅРЅС‹Р№ self-signed..."
    mkdir -p "${CERT_DIR}"
    # nginx:alpine РЅРµ РІРєР»СЋС‡Р°РµС‚ openssl вЂ” СѓСЃС‚Р°РЅР°РІР»РёРІР°РµРј РЅР°Р»РµС‚Сѓ (РєСЌС€РёСЂСѓРµС‚СЃСЏ РІ СЃР»РѕРµ РєРѕРЅС‚РµР№РЅРµСЂР°)
    apk add --no-cache openssl >/dev/null 2>&1
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout "${CERT_DIR}/privkey.pem" \
        -out  "${CERT_DIR}/fullchain.pem" \
        -subj "/CN=${HOSTNAME}" 2>/dev/null
    echo "[nginx-init] Р’РќРРњРђРќРР•: РІСЂРµРјРµРЅРЅС‹Р№ self-signed cert (dev С‚РѕР»СЊРєРѕ)."
    echo "[nginx-init] Р”Р»СЏ РїСЂРѕРґР° Р·Р°РїСѓСЃС‚РёС‚Рµ 'make ssl-init' вЂ” РїРѕР»СѓС‡РёС‚ СЂРµР°Р»СЊРЅС‹Р№ Let's Encrypt."
fi

# РџРѕРґСЃС‚Р°РІР»СЏРµРј РўРћР›Р¬РљРћ ${SERVER_HOSTNAME} вЂ” nginx-РїРµСЂРµРјРµРЅРЅС‹Рµ ($host Рё С‚.Рґ.) РЅРµ С‚СЂРѕРіР°РµРј
envsubst '${SERVER_HOSTNAME}' < /tmp/nginx.conf.template > /tmp/nginx.generated.conf

echo "[nginx-init] Р—Р°РїСѓСЃРє nginx | РґРѕРјРµРЅ=${HOSTNAME}"
exec nginx -c /tmp/nginx.generated.conf -g 'daemon off;'
