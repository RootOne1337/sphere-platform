# SPLIT-3 — Redis конфигурация + Nginx SSL Reverse Proxy

**ТЗ-родитель:** TZ-00-Constitution  
**Ветка:** `stage/0-constitution`  
**Задача:** `SPHERE-003`  
**Исполнитель:** DevOps  
**Оценка:** 0.5 рабочего дня  
**Блокирует:** TZ-00 SPLIT-4, SPLIT-5 (внутри этапа)
**Обеспечивает:** Redis + Nginx инфраструктуру для всех потоков

---

## Цель Сплита

Настроить Redis с тремя ролями (кэш/Pub/Sub/rate-limiting) и Nginx как SSL-терминатор с поддержкой WebSocket проксирования. После выполнения — backend может использовать Redis, а все соединения защищены TLS.

---

## Предусловия

- [ ] SPLIT-1 выполнен (Redis контейнер запущен)
- [ ] SSL сертификат получен (Let's Encrypt / self-signed для dev)
- [ ] `REDIS_PASSWORD` заполнен в `.env.local`

---

## Шаг 1 — Redis клиент в Python

```python
# backend/database/redis_client.py
import redis.asyncio as aioredis
from backend.core.config import settings

redis: aioredis.Redis | None = None

# FIX: отдельный клиент без decode_responses для бинарных каналов (H.264 NAL units).
# Канал stream:{agent_id} передаёт бинарные данные — decode_responses=True вызовет UnicodeDecodeError.
# Используй redis_binary для Pub/Sub видеострима (TZ-05 SPLIT-2, TZ-14).
# Используй redis (с decode_responses=True) для всего остального (JWT blacklist, rate-limit, статусы).
redis_binary: aioredis.Redis | None = None

async def get_redis() -> aioredis.Redis:
    """FastAPI dependency для Redis (строки: JWT blacklist, rate-limit, статусы устройств)."""
    return redis

async def get_redis_binary() -> aioredis.Redis:
    """FastAPI dependency для бинарного Redis (Pub/Sub H.264 NAL units, video stream)."""
    return redis_binary

async def connect_redis():
    global redis, redis_binary
    redis = aioredis.from_url(
        settings.REDIS_URL,
        password=settings.REDIS_PASSWORD,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    # FIX: бинарный клиент — decode_responses=False (по умолчанию)
    redis_binary = aioredis.from_url(
        settings.REDIS_URL,
        password=settings.REDIS_PASSWORD,
        decode_responses=False,
        max_connections=20,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    # Проверяем соединение
    await redis.ping()
    await redis_binary.ping()

async def disconnect_redis():
    global redis, redis_binary
    if redis:
        await redis.close()
    if redis_binary:
        await redis_binary.close()
```

---

## Шаг 2 — Redis три роли / паттерны ключей

> **ВАЖНО:** Redis настроен с `appendonly yes` (см. TZ-00 SPLIT-1 docker-compose.yml).
> **Реальная причина AOF:** JWT-blacklist хранится в Redis. Без AOF при внезапном рестарте
> отозванные токены становятся снова валидными до истечения TTL (max ~15 минут).
> `appendfsync everysec` минимизирует этот риск потерей не более ~1 сек операций.
>
> **Что в Redis НЕ нуждается в AOF:** device status cache (агент переотправит при reconnect),
> rate-limit счётчики (сброс при рестарте приемлем), Pub/Sub каналы (эфемерны по природе).
> **Задачи TZ-04 хранятся в PostgreSQL, не в Redis** — AOF для них не нужен.
>
> **Production-рекомендация (high-load / 500+ устройств):**
> Разделить на два контейнера:
>
> - `redis-cache` — `appendonly no`, `maxmemory-policy allkeys-lru` (статусы, rate-limit, Pub/Sub)
> - `redis-auth` — `appendonly yes`, `maxmemory-policy noeviction` (JWT blacklist, persist данные)
>
> Для dev/staging одного инстанса с `appendfsync everysec` достаточно.

**Роль 1: Device Status Cache (TTL)**

```
Ключ:   device:{id}:status
Тип:    String (JSON)
TTL:    60 секунд
Запись: Каждые 30 сек от агента (heartbeat)
Чтение: GET endpoint /devices/{id}/status (мгновенно, без DB)

Пример:
device:ld:0:status = {
  "online": true,
  "battery": 85,
  "cpu_percent": 23,
  "ram_mb": 1024,
  "vpn_active": true,
  "vpn_ip": "10.8.0.1",
  "last_seen": "2026-02-21T10:00:00Z"
}
```

**Роль 2: WebSocket Pub/Sub каналы**

```
agent:{id}:cmd      — команды от сервера → агенту
agent:{id}:event    — события от агента → серверу
operator:{session}:data  — данные от агента → браузеру
stream:{agent_id}   — H.264 NAL units (binary)
```

**Роль 3: Rate Limiting**

```
ratelimit:login:{ip}        — TTL 60 сек, max 5
ratelimit:api:{api_key_id}  — TTL 60 сек, max 1000
ratelimit:ws:{agent_id}     — TTL 1 сек, max 100 (commands/sec)
```

**Роль 4: JWT Blacklist**

```
blacklist:jti:{jti}    — value "1", TTL = время до истечения токена
```

---

## Шаг 3 — Redis хелперы

```python
# backend/services/cache_service.py
import json
from typing import Any
from datetime import timedelta

class CacheService:
    def __init__(self, redis):
        self.redis = redis
    
    async def set_device_status(self, device_id: str, status: dict, ttl: int = 60):
        await self.redis.setex(
            f"device:{device_id}:status",
            ttl,
            json.dumps(status, default=str)
        )
    
    async def get_device_status(self, device_id: str) -> dict | None:
        data = await self.redis.get(f"device:{device_id}:status")
        return json.loads(data) if data else None
    
    async def get_all_device_statuses(self, device_ids: list[str]) -> dict[str, dict | None]:
        """Batch получение статусов всех устройств — одна команда MGET."""
        keys = [f"device:{did}:status" for did in device_ids]
        values = await self.redis.mget(*keys)
        return {
            did: json.loads(val) if val else None
            for did, val in zip(device_ids, values)
        }
    
    async def blacklist_token(self, jti: str, expires_in: timedelta):
        await self.redis.setex(f"blacklist:jti:{jti}", int(expires_in.total_seconds()), "1")
    
    async def is_token_blacklisted(self, jti: str) -> bool:
        return bool(await self.redis.exists(f"blacklist:jti:{jti}"))
    
    async def check_rate_limit(self, key: str, limit: int, window_sec: int) -> bool:
        """Возвращает True если запрос разрешён. False = лимит превышен."""
        full_key = f"ratelimit:{key}"
        count = await self.redis.incr(full_key)
        if count == 1:
            await self.redis.expire(full_key, window_sec)
        return count <= limit
```

---

## Шаг 4 — Nginx конфигурация

```nginx
# infrastructure/nginx/nginx.conf

worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 4096;
    multi_accept on;
    use epoll;
}

http {
    # Базовые настройки
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;  # не показывать версию

    # Размеры буферов для WebSocket
    proxy_buffer_size          128k;
    proxy_buffers              4 256k;
    proxy_busy_buffers_size    256k;
    
    # TLS настройки
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Security headers (для всех)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # ── HTTP → HTTPS редирект ────────────────────────────────────────────────
    server {
        listen 80;
        server_name _;
        return 301 https://$host$request_uri;
    }

    # ── Основной HTTPS сервер ───────────────────────────────────────────────
    server {
        listen 443 ssl http2;
        server_name sphere.example.com;

        ssl_certificate     /etc/nginx/ssl/fullchain.pem;
        ssl_certificate_key /etc/nginx/ssl/privkey.pem;

        # ── REST API ──────────────────────────────────────────────────────
        location /api/ {
            proxy_pass http://backend:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Request ID для трейсинга
            proxy_set_header X-Request-ID $request_id;
            add_header X-Request-ID $request_id;

            # Таймауты для долгих API вызовов
            proxy_connect_timeout 30s;
            proxy_read_timeout 120s;
            proxy_send_timeout 30s;
        }

        # ── WebSocket (агенты + операторы) ───────────────────────────────
        location /ws/ {
            proxy_pass http://backend:8000;
            proxy_http_version 1.1;
            
            # КРИТИЧНО для WebSocket upgrade
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            
            # Увеличенные таймауты для long-lived соединений
            proxy_read_timeout 3600s;   # 1 час — агент держит соединение
            proxy_send_timeout 3600s;
            
            # Отключаем буферизацию для real-time данных
            proxy_buffering off;
        }

        # ── Frontend (Next.js) ───────────────────────────────────────────
        location / {
            proxy_pass http://frontend:3002;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # ── Prometheus metrics (только внутри сети) ──────────────────────
        location /metrics {
            # FIX: 172.0.0.0/8 покрывало 16M адресов включая внешние.
            # 172.16.0.0/12 — RFC-1918 приватный диапазон, покрывает все Docker-подсети (172.16-172.31.x.x).
            allow 172.16.0.0/12;   # Docker сети (RFC-1918)
            allow 127.0.0.1;
            deny all;
            proxy_pass http://backend:8000/metrics;
        }
    }
}
```

---

## Шаг 5 — SSL для разработки (self-signed)

```bash
# Создать self-signed сертификат для dev
mkdir -p infrastructure/nginx/ssl

openssl req -x509 -newkey rsa:4096 -keyout infrastructure/nginx/ssl/privkey.pem \
  -out infrastructure/nginx/ssl/fullchain.pem -days 365 -nodes \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=SpherePlatform/CN=localhost"

# Для production — Let's Encrypt:
# docker run -it --rm -p 80:80 \
#   -v $(pwd)/infrastructure/nginx/ssl:/etc/letsencrypt \
#   certbot/certbot certonly --standalone -d sphere.example.com
```

---

## Критерии готовности

- [ ] `redis-cli -a $REDIS_PASSWORD ping` → PONG
- [ ] `redis-cli -a $REDIS_PASSWORD info memory` → maxmemory=512mb, policy=allkeys-lru
- [ ] `redis-cli -a $REDIS_PASSWORD config get appendonly` → "yes"
- [ ] `curl -k https://localhost/api/v1/health` → 200 OK
- [ ] WebSocket соединение через Nginx работает (wscat тест)
- [ ] HTTP → HTTPS редирект работает
- [ ] Security headers присутствуют в ответах
- [ ] CORS заголовки корректны для frontend origin

---

## Шаг 6 — CORS конфигурация (FastAPI)

```python
# backend/core/cors.py
from fastapi.middleware.cors import CORSMiddleware

def setup_cors(app):
    """Настроить CORS. Вызвать при старте приложения."""
    origins = [
        "http://localhost:3002",           # Next.js dev
        "https://sphere.example.com",          # Production
    ]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,            # для HTTPOnly cookie (refresh token)
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=3600,                      # Preflight cache 1 час
    )
```

```python
# backend/main.py (добавить):
from backend.core.cors import setup_cors

app = FastAPI(title="SpherePlatform API", version="4.0.0")
setup_cors(app)
```

> **ВАЖНО:** `allow_credentials=True` обязательно для передачи HTTPOnly cookie
> с refresh token через cross-origin запросы frontend → backend.
