#!/bin/bash
# entrypoint.sh -- SSH tunnel to Serveo with auto-reconnect and exponential backoff.
# restart: always in compose keeps container alive.

set -e

SUBDOMAIN="${TUNNEL_SUBDOMAIN:-sphere}"
LOCAL_HOST="${TUNNEL_LOCAL_HOST:-nginx}"
LOCAL_PORT="${TUNNEL_LOCAL_PORT:-80}"
REMOTE_HOST="${TUNNEL_REMOTE_HOST:-serveo.net}"

# Exponential backoff: 5s -> 10s -> 20s -> 40s -> 80s -> 120s (max)
BACKOFF_INITIAL=5
BACKOFF_MAX=120
BACKOFF_CURRENT=$BACKOFF_INITIAL

echo "================================================"
echo " Sphere Platform -- SSH Tunnel Service"
echo " Forward   : ${SUBDOMAIN}:80 -> ${LOCAL_HOST}:${LOCAL_PORT}"
echo " Remote    : ${REMOTE_HOST}"
echo " Backoff   : ${BACKOFF_INITIAL}s -> ${BACKOFF_MAX}s (exponential)"
echo "================================================"

# Add serveo.net to known_hosts
ssh-keyscan -T 10 "${REMOTE_HOST}" >> /root/.ssh/known_hosts 2>/dev/null || true

# Find SSH key (ed25519 preferred over rsa)
if [ -f /root/.ssh/id_ed25519 ]; then
    cp /root/.ssh/id_ed25519 /tmp/ssh_key
elif [ -f /root/.ssh/id_rsa ]; then
    cp /root/.ssh/id_rsa /tmp/ssh_key
else
    echo "ERROR: SSH key not found."
    exit 1
fi
chmod 600 /tmp/ssh_key

echo "Starting SSH tunnel..."

while true; do
    CONNECT_TIME=$(date +%s)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Connecting to ${REMOTE_HOST}..."
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
    DISCONNECT_TIME=$(date +%s)
    UPTIME=$(( DISCONNECT_TIME - CONNECT_TIME ))

    if [ $EXIT_CODE -eq 0 ] || [ $UPTIME -gt 30 ]; then
        # Connection was alive > 30s or exited normally -- reset backoff
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] SSH exited (code=${EXIT_CODE}, uptime=${UPTIME}s). Reconnecting in ${BACKOFF_INITIAL}s..."
        BACKOFF_CURRENT=$BACKOFF_INITIAL
    else
        # Immediate failure -- increase backoff
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] SSH failed (code=${EXIT_CODE}, uptime=${UPTIME}s). Reconnecting in ${BACKOFF_CURRENT}s..."
        if [ $BACKOFF_CURRENT -lt $BACKOFF_MAX ]; then
            BACKOFF_CURRENT=$(( BACKOFF_CURRENT * 2 ))
            if [ $BACKOFF_CURRENT -gt $BACKOFF_MAX ]; then
                BACKOFF_CURRENT=$BACKOFF_MAX
            fi
        fi
    fi

    sleep $BACKOFF_CURRENT
done