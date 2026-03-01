#!/bin/bash
# entrypoint.sh — SSH туннель к Serveo с автопереподключением
# restart: always в compose держит контейнер живым

set -e

SUBDOMAIN="${TUNNEL_SUBDOMAIN:-sphere}"
LOCAL_HOST="${TUNNEL_LOCAL_HOST:-nginx}"
LOCAL_PORT="${TUNNEL_LOCAL_PORT:-80}"
REMOTE_HOST="${TUNNEL_REMOTE_HOST:-serveo.net}"

echo "================================================"
echo " Sphere Platform — SSH Tunnel Service"
echo " Forward   : ${SUBDOMAIN}:80 -> ${LOCAL_HOST}:${LOCAL_PORT}"
echo " Remote    : ${REMOTE_HOST}"
echo "================================================"

# Добавляем serveo.net в known_hosts
ssh-keyscan -T 10 "${REMOTE_HOST}" >> /root/.ssh/known_hosts 2>/dev/null || true

# Находим SSH ключ (ed25519 приоритетнее rsa)
if [ -f /root/.ssh/id_ed25519 ]; then
    cp /root/.ssh/id_ed25519 /tmp/ssh_key
elif [ -f /root/.ssh/id_rsa ]; then
    cp /root/.ssh/id_rsa /tmp/ssh_key
else
    echo "ОШИБКА: SSH ключ не найден."
    exit 1
fi
chmod 600 /tmp/ssh_key

echo "Запускаю SSH туннель..."

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Подключаюсь к ${REMOTE_HOST}..."
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
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SSH завершился с кодом ${EXIT_CODE}. Переподключение через 5 сек..."
    sleep 5
done
    sleep 5
done
