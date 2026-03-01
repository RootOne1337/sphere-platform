#!/bin/sh
# scripts/sync-tunnel-url.sh
# После старта cloudflared-туннеля: извлекает URL → обновляет .env и agent-config → рестартит бэкенд.
# Использование: make tunnel-up (вызывает автоматически)

set -e

MAX_WAIT=15
WAITED=0
TUNNEL_URL=""

echo "⏳ Ожидаю URL от Cloudflare..."
while [ $WAITED -lt $MAX_WAIT ]; do
  TUNNEL_URL=$(docker logs sphere-tunnel 2>&1 | grep -o 'https://[^ ]*trycloudflare[^ ]*' | tail -1 || true)
  if [ -n "$TUNNEL_URL" ]; then
    break
  fi
  sleep 2
  WAITED=$((WAITED + 2))
done

if [ -z "$TUNNEL_URL" ]; then
  echo "❌ Не удалось получить URL туннеля за ${MAX_WAIT}s"
  exit 1
fi

echo "🌐 Tunnel URL: $TUNNEL_URL"

# 1. Обновить .env (SERVER_PUBLIC_URL)
if [ -f .env ]; then
  if grep -q '^SERVER_PUBLIC_URL=' .env; then
    sed -i "s|^SERVER_PUBLIC_URL=.*|SERVER_PUBLIC_URL=$TUNNEL_URL|" .env
  else
    echo "SERVER_PUBLIC_URL=$TUNNEL_URL" >> .env
  fi
  echo "✅ .env → SERVER_PUBLIC_URL=$TUNNEL_URL"
fi

# 2. Обновить agent-config/environments/development.json (server_url)
CONFIG_FILE="agent-config/environments/development.json"
if [ -f "$CONFIG_FILE" ]; then
  # Используем sed для замены server_url (работает без jq)
  sed -i "s|\"server_url\":.*|\"server_url\": \"$TUNNEL_URL\",|" "$CONFIG_FILE"
  echo "✅ $CONFIG_FILE → server_url=$TUNNEL_URL"
fi

# 3. Сохранить URL в .tunnel-url для быстрого доступа
echo "$TUNNEL_URL" > .tunnel-url
echo "✅ .tunnel-url сохранён"

# 4. Очистить Redis-кэш agent-config (чтобы бэкенд подхватил новый URL)
REDIS_PASS=$(grep '^REDIS_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)
if [ -n "$REDIS_PASS" ]; then
  docker exec sphere-platform-redis-1 redis-cli -a "$REDIS_PASS" DEL "agent_config:development" 2>/dev/null || true
else
  docker exec sphere-platform-redis-1 redis-cli DEL "agent_config:development" 2>/dev/null || true
fi
echo "✅ Redis-кэш agent-config очищен"

# 5. Рестартнуть бэкенд (подхватит новый SERVER_PUBLIC_URL из .env)
docker restart sphere-platform-backend-1 2>/dev/null || true
echo "✅ Backend перезапущен → подхватит новый URL"

echo ""
echo "════════════════════════════════════════"
echo " TUNNEL READY: $TUNNEL_URL"
echo "════════════════════════════════════════"
