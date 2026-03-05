#!/bin/bash
# entrypoint.sh вЂ” SSH С‚СѓРЅРЅРµР»СЊ Рє Serveo СЃ Р°РІС‚РѕРїРµСЂРµРїРѕРґРєР»СЋС‡РµРЅРёРµРј
# restart: always РІ compose РґРµСЂР¶РёС‚ РєРѕРЅС‚РµР№РЅРµСЂ Р¶РёРІС‹Рј

set -e

SUBDOMAIN="${TUNNEL_SUBDOMAIN:-sphere}"
LOCAL_HOST="${TUNNEL_LOCAL_HOST:-nginx}"
LOCAL_PORT="${TUNNEL_LOCAL_PORT:-80}"
REMOTE_HOST="${TUNNEL_REMOTE_HOST:-serveo.net}"

echo "================================================"
echo " Sphere Platform вЂ” SSH Tunnel Service"
echo " Forward   : ${SUBDOMAIN}:80 -> ${LOCAL_HOST}:${LOCAL_PORT}"
echo " Remote    : ${REMOTE_HOST}"
echo "================================================"

# Р”РѕР±Р°РІР»СЏРµРј serveo.net РІ known_hosts
ssh-keyscan -T 10 "${REMOTE_HOST}" >> /root/.ssh/known_hosts 2>/dev/null || true

# РќР°С…РѕРґРёРј SSH РєР»СЋС‡ (ed25519 РїСЂРёРѕСЂРёС‚РµС‚РЅРµРµ rsa)
if [ -f /root/.ssh/id_ed25519 ]; then
    cp /root/.ssh/id_ed25519 /tmp/ssh_key
elif [ -f /root/.ssh/id_rsa ]; then
    cp /root/.ssh/id_rsa /tmp/ssh_key
else
    echo "РћРЁРР‘РљРђ: SSH РєР»СЋС‡ РЅРµ РЅР°Р№РґРµРЅ."
    exit 1
fi
chmod 600 /tmp/ssh_key

echo "Р—Р°РїСѓСЃРєР°СЋ SSH С‚СѓРЅРЅРµР»СЊ..."

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] РџРѕРґРєР»СЋС‡Р°СЋСЃСЊ Рє ${REMOTE_HOST}..."
    ssh -N \
        -i /tmp/ssh_key \
        -o "ServerAliveInterval=30" \
        -o "ServerAliveCountMax=3" \
        -o "ExitOnForwardFailure=yes" \
        -o "StrictHostKeyChecking=no" \
        -o "ConnectTimeout=15" \
        -R "${SUBDOMAIN}:80:${LOCAL_HOST}:${LOCAL_PORT}" \
        "${REMOTE_HOST}"
    EXIT_CODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SSH Р·Р°РІРµСЂС€РёР»СЃСЏ СЃ РєРѕРґРѕРј ${EXIT_CODE}. РџРµСЂРµРїРѕРґРєР»СЋС‡РµРЅРёРµ С‡РµСЂРµР· 5 СЃРµРє..."
    sleep 5
done
    sleep 5
done
