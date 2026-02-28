#!/bin/bash
# entrypoint.sh — запуск autossh туннеля к Serveo
# Перезапускается автоматически при разрыве. restart: always в compose держит
# контейнер живым даже если Serveo временно недоступен.

set -e

SUBDOMAIN="${TUNNEL_SUBDOMAIN:-sphere}"
LOCAL_HOST="${TUNNEL_LOCAL_HOST:-nginx}"
LOCAL_PORT="${TUNNEL_LOCAL_PORT:-80}"
REMOTE_HOST="${TUNNEL_REMOTE_HOST:-serveo.net}"
REMOTE_PORT="${TUNNEL_REMOTE_PORT:-443}"

echo "================================================"
echo " Sphere Platform — SSH Tunnel Service"
echo " Subdomain : ${SUBDOMAIN}.serveousercontent.com"
echo " Forward   : ${SUBDOMAIN}:80 -> ${LOCAL_HOST}:${LOCAL_PORT}"
echo " Remote    : ${REMOTE_HOST}"
echo "================================================"

# Загружаем приватный ключ из base64-переменной окружения (если задан)
if [ -n "${SSH_PRIVATE_KEY}" ]; then
    echo "Загружаю SSH ключ из переменной окружения..."
    echo "${SSH_PRIVATE_KEY}" | base64 -d > /tmp/id_rsa_decoded
    cp /tmp/id_rsa_decoded /root/.ssh/id_rsa
    chmod 600 /root/.ssh/id_rsa
    rm /tmp/id_rsa_decoded
fi

# Добавляем serveo.net в known_hosts чтобы не было интерактивного подтверждения
ssh-keyscan -T 10 "${REMOTE_HOST}" >> /root/.ssh/known_hosts 2>/dev/null || true

# Если ключ смонтирован как read-only — копируем в tmp с правильными правами
if [ -f /root/.ssh/id_rsa ]; then
    cp /root/.ssh/id_rsa /tmp/id_rsa_work
    chmod 600 /tmp/id_rsa_work
    SSH_KEY_FILE=/tmp/id_rsa_work
else
    echo "ОШИБКА: SSH ключ не найден (/root/.ssh/id_rsa)."
    echo "Сгенерируй ключ командой: make tunnel-keygen"
    exit 1
fi

echo "Запускаю autossh туннель..."

# AUTOSSH_POLL — интервал проверки соединения (секунды)
# -M 0 — отключить monitoring port (autossh использует ServerAlive* вместо)
exec autossh -M 0 -N \
    -i /tmp/id_rsa_work \
    -o "ServerAliveInterval=30" \
    -o "ServerAliveCountMax=3" \
    -o "ExitOnForwardFailure=yes" \
    -o "StrictHostKeyChecking=no" \
    -o "BatchMode=yes" \
    -o "ConnectTimeout=15" \
    -R "${SUBDOMAIN}:80:${LOCAL_HOST}:${LOCAL_PORT}" \
    "${REMOTE_HOST}"
