# Sphere Platform — Полный гайд развёртывания

> **Статус на 11 сентября 2026: production readiness не подтверждена.**
>
> Это справочник настройки; полный runtime и ёмкость 10–64 эмулятора ещё проверяются.
> Текущий общий PostgreSQL owner/superuser отклоняется production startup guard.
> До rollout нужно завершить auth/job tenant context и разделение runtime/migration
> ролей: [RLS runbook](docs/security/postgresql-rls.md). Политики устанавливает Alembic,
> ручной SQL setup и автоматический downgrade `20260908_tenant_policies` запрещены.
> Migration `20260909_user_auth_bootstrap` добавляет две user-функции к двум device-функциям.
> Текущий head — `20260910_device_refresh_retry`; [device retry rollout](docs/security/device-refresh-recovery.md)
> требует обновления всех backend workers перед новым APK, сохраняет прежние grants.
> Их runtime EXECUTE grants и обязательный MFA cutover описаны в
> [user auth runbook](docs/security/user-auth-bootstrap.md) и
> [device credential runbook](docs/security/device-credential-bootstrap.md).
> Фактические результаты и оставшиеся блокеры: [audit report](docs/audits/2026-09-05/AUDIT-REPORT.md).

---

## Содержание

1.  [Обзор архитектуры](#1-обзор-архитектуры)
2.  [Системные требования](#2-системные-требования)
3.  [Быстрый старт (One-Command Deploy)](#3-быстрый-старт-one-command-deploy)
4.  [Пошаговое развёртывание](#4-пошаговое-развёртывание)
    - [4.1 Клонирование](#41-клонирование)
    - [4.2 Генерация секретов](#42-генерация-секретов)
    - [4.3 Запуск Docker-стека](#43-запуск-docker-стека)
    - [4.4 Миграции базы данных](#44-миграции-базы-данных)
    - [4.5 Создание администратора](#45-создание-администратора)
    - [4.6 Проверка здоровья](#46-проверка-здоровья)
5.  [Режимы развёртывания](#5-режимы-развёртывания)
    - [5.1 Development](#51-development)
    - [5.2 Production](#52-production)
    - [5.3 Serveo Tunnel (удалённый доступ)](#53-serveo-tunnel-удалённый-доступ)
6.  [Подключение Android-агентов](#6-подключение-android-агентов)
    - [6.1 LDPlayer (эмуляторы)](#61-ldplayer-эмуляторы)
    - [6.2 Физические устройства](#62-физические-устройства)
    - [6.3 Сборка enterprise APK](#63-сборка-enterprise-apk)
7.  [Настройка SSL/HTTPS](#7-настройка-sslhttps)
8.  [Мониторинг (Prometheus + Grafana)](#8-мониторинг-prometheus--grafana)
9.  [Бэкапы и восстановление](#9-бэкапы-и-восстановление)
10. [Масштабирование](#10-масштабирование)
11. [Структура файлов деплоя](#11-структура-файлов-деплоя)
12. [Переменные окружения](#12-переменные-окружения)
13. [Скрипты автоматизации](#13-скрипты-автоматизации)
14. [Устранение неполадок](#14-устранение-неполадок)
15. [Checklist перед продакшеном](#15-checklist-перед-продакшеном)

---

## 1. Обзор архитектуры

```
┌──────────────────────────────────────────────────────────────────┐
│                        КЛИЕНТЫ                                    │
│  🖥️ Web UI (Next.js)    📱 Android-агенты    🔗 n8n Workflows     │
└──────────────┬──────────────────┬───────────────────┬────────────┘
               │ HTTPS/WSS        │ WSS               │ HTTP
               ▼                  ▼                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                      NGINX Reverse Proxy                         │
│  :80 → redirect :443 │ /api/* → backend:8000                     │
│  /ws/* → backend:8000 │ /* → frontend:3000                       │
│  Rate limiting: 100 req/s │ WebSocket upgrade                    │
└──────────────┬──────────────────┬───────────────────┬────────────┘
               │                  │                   │
    ┌──────────▼──────────┐  ┌───▼───────────┐  ┌───▼────────────┐
    │   Backend (FastAPI)  │  │  Frontend     │  │  n8n           │
    │   Python 3.12        │  │  Next.js 15   │  │  Workflow      │
    │   Port: 8000         │  │  Port: 3000   │  │  Port: 5678    │
    │                      │  │               │  │                │
    │  ● REST API (22 мод) │  │  ● Dashboard  │  │  ● Custom      │
    │  ● WebSocket Hub     │  │  ● Devices    │  │    Nodes       │
    │  ● Script Engine     │  │  ● Scripts    │  │  ● Webhook     │
    │  ● Orchestrator      │  │  ● Streaming  │  │    Triggers    │
    │  ● Scheduler         │  │  ● VPN Mgmt   │  │                │
    │  ● VPN Manager       │  │  ● Monitoring │  │                │
    └──────┬──────┬────────┘  └───────────────┘  └────────────────┘
           │      │
    ┌──────▼──┐ ┌─▼──────────┐
    │ Postgres │ │   Redis    │
    │  15      │ │   7.2      │
    │          │ │            │
    │ 19 табл  │ │ Pub/Sub    │
    │ RLS      │ │ Device     │
    │ Alembic  │ │ Status     │
    │ Audit    │ │ Sessions   │
    └──────────┘ └────────────┘
           │
    ┌──────▼──────────┐
    │  MinIO (S3)      │
    │  Скриншоты,      │
    │  OTA APK файлы   │
    └──────────────────┘
```

**Сервисы в Docker Compose:**

| Сервис | Образ | Порт | Назначение |
|--------|-------|------|------------|
| **postgres** | postgres:15-alpine | 5432 | Основная БД (28 таблиц, RLS, аудит) |
| **redis** | redis:7.2-alpine | 6379 | Кэш, Pub/Sub, статусы устройств |
| **backend** | python:3.12-slim | 8000 | FastAPI REST + WebSocket API |
| **frontend** | node:20 | 3000 | Next.js 15 Web UI |
| **nginx** | nginx:alpine | 80/443 | Reverse proxy, SSL, rate limiting |
| **n8n** | n8nio/n8n:1.32.0 | 5678 | No-code автоматизация |
| **minio** | minio/minio | 9000/9001 | S3-совместимое хранилище |
| **certbot** | certbot/certbot | — | Авто-обновление Let's Encrypt |
| **tunnel** | alpine + autossh | — | SSH-туннель (Serveo) |

---

## 2. Системные требования

### Минимальные требования

| Компонент | Development | Production |
|-----------|-------------|------------|
| **CPU** | 2 cores | 8 cores |
| **RAM** | 4 GB | 16 GB |
| **Диск** | 20 GB SSD | 100 GB SSD |
| **ОС** | Windows 10+, macOS, Linux | Ubuntu 22.04 LTS |
| **Docker** | Docker Desktop 4+ | Docker Engine 24+ |

### Программное обеспечение

```bash
# Обязательно
docker --version          # >= 24.0
docker compose version    # >= 2.20 (V2, не docker-compose)
git --version             # >= 2.30
python --version          # >= 3.11

# Рекомендуется
make --version            # GNU Make (для Makefile-шорткатов)
curl --version            # Для health-check скриптов
```

### Проверка Docker

```bash
# Docker daemon запущен?
docker info

# Compose V2 доступен?
docker compose version

# Достаточно памяти для Docker?
docker system info | grep "Total Memory"
```

---

## 3. Быстрый старт (One-Command Deploy)

### Linux / macOS

```bash
git clone https://github.com/RootOne1337/sphere-platform.git
cd sphere-platform
chmod +x scripts/full-deploy.sh
./scripts/full-deploy.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/RootOne1337/sphere-platform.git
cd sphere-platform
.\scripts\full-deploy.ps1
```

### Что делает скрипт

Порядок после AUD-81/82:

1. Проверка инструментов и подготовка конфигурации.
2. Сборка образов; production backend содержит admin/enrollment CLI.
3. PostgreSQL/Redis → Compose wait (180 s).
4. One-off миграции → администратор → enrollment key; отказ прекращает запуск.
5. Приложения → Compose wait (300 s) → статус выбранного project.

Нет гарантии «5–10 минут»: build/pull/npm не входят в readiness timeout. Сервисам
без healthcheck достаточно running; ingress, пользовательский вход, APK/task и VPN
проверяются отдельно. Разделение runtime/migration ролей и уже работающие workers
требуют отдельного rollout, описанного в начале руководства.

---

## 4. Пошаговое развёртывание

### 4.1 Клонирование

```bash
git clone https://github.com/RootOne1337/sphere-platform.git
cd sphere-platform
```

Структура после клонирования:
```
sphere-platform/
├── backend/           # FastAPI бэкенд
├── frontend/          # Next.js 15 фронтенд
├── android/           # Kotlin Android-агент
├── pc-agent/          # Python PC-агент (LDPlayer)
├── infrastructure/    # Nginx, Postgres, Redis, Traefik конфиги
├── alembic/           # Миграции БД
├── scripts/           # Скрипты развёртывания и утилиты
├── n8n-nodes/         # Custom n8n-ноды для Sphere
├── docker-compose.yml          # Инфраструктура
├── docker-compose.full.yml     # + Backend + Frontend
├── docker-compose.production.yml # Production-режим
├── .env.example                # Шаблон переменных окружения
└── Makefile                    # Шорткаты для всех операций
```

### 4.2 Генерация секретов

```bash
# Автоматическая генерация (рекомендуется)
python scripts/generate_secrets.py --output .env.local
```

Скрипт создаёт `.env.local` с:
- `POSTGRES_PASSWORD` — 32 байта base64url
- `REDIS_PASSWORD` — 32 байта base64url
- `JWT_SECRET_KEY` — 64 байта base64url (512 бит)
- `N8N_ENCRYPTION_KEY` — 32 байта hex
- `AWG_H1..H4` — AmneziaWG obfuscation headers
- `POSTGRES_URL` / `REDIS_URL` — автоматически собранные connection strings

```bash
# Ручная генерация (если Python недоступен)
cp .env.example .env.local
# Заполни CHANGE_ME значения в .env.local
```

> **ВАЖНО:** Файл `.env.local` содержит критические секреты. Он в `.gitignore` и **НИКОГДА** не коммитится.

### 4.3 Запуск Docker-стека

Для новой prepared development установки сначала поднимите только зависимости.
Пример ниже — Bash; выбран `.env.local` из шага 4.2. При использовании `.env`
явно замените имя. Не меняйте Compose project между командами.

```bash
dc() { docker compose --env-file .env.local -f docker-compose.yml -f docker-compose.full.yml "$@"; }
dc build
dc up -d --wait --wait-timeout 180 postgres redis
```

Автоматические альтернативы — `scripts/full-deploy.sh` / `scripts/full-deploy.ps1`.
`start-dev.ps1` запускает уже подготовленный стек; bootstrap он не выполняет.

### 4.4 Миграции базы данных

```bash
dc run --rm --no-deps -T backend alembic -c alembic/alembic.ini upgrade head
```

Команда выполняется до API с явно подготовленными migration credentials. Текущий
head и role/grant requirements указаны в начале документа. При ошибке не переходите
к следующим шагам; host fallback не подтверждает тот же target и не используется.

### 4.5 Создание администратора

```bash
# Интерактивный admin CLI запрашивает email/password.
dc run --rm --no-deps backend python scripts/create_admin.py --create-only
dc run --rm --no-deps -T backend python -m scripts.seed_enrollment_key
```

Оба CLI используют `SPHERE_BOOTSTRAP_ORG_SLUG=default`. Для иной организации
передайте одну и ту же явно заданную переменную через `-e SPHERE_BOOTSTRAP_ORG_SLUG`
обоим one-off containers. Enrollment key берётся из эффективного agent-config.
Повтор admin CLI может обновить пароль; конфликты ключа не исправляются молча.
Для headless задайте `ADMIN_EMAIL/ADMIN_PASSWORD` в process environment и передайте
`-e ADMIN_EMAIL -e ADMIN_PASSWORD`; `SPHERE_ADMIN_*` предназначены для full-deploy.

### 4.6 Проверка здоровья

Только после успешных migrations/admin/key:

```bash
dc up -d --wait --wait-timeout 300
dc ps --all
```

Backend probe требует `/api/v1/health/readyz` → HTTP 200 и `status=ready`;
frontend probe требует `/login` → 200. Production overlay имеет такие же probes
внутри контейнеров. Это проверка Compose running/healthy, не успешного login,
APK/task или VPN. [Полные критерии пилота](docs/operations/PILOT-ACCEPTANCE.md).

### Доступ к сервисам

| Сервис | URL | Описание |
|--------|-----|----------|
| 🖥️ **Web UI** | http://localhost | Дашборд, устройства, скрипты |
| 📡 **REST API** | http://localhost:8000/api/v1 | Все API-эндпоинты |
| 📖 **Swagger** | http://localhost:8000/docs | Интерактивная документация |
| 📘 **ReDoc** | http://localhost:8000/redoc | Альтернативная API-документация |
| 🔗 **n8n** | http://localhost:5678 | No-code воркфлоу |
| 💾 **MinIO** | http://localhost:9001 | S3-консоль (скриншоты, APK) |
| 📊 **Grafana** | http://localhost:3001 | Мониторинг (после `make monitoring`) |

---

## 5. Режимы развёртывания

### 5.1 Development

```bash
# Полный dev-стек с hot-reload
docker compose -f docker-compose.yml \
               -f docker-compose.full.yml \
               -f docker-compose.override.yml up -d

# Или через Makefile
make full
```

Особенности dev-режима:
- **Backend:** uvicorn с `--reload` (перезапуск при изменении кода)
- **Frontend:** Next.js с Turbopack (мгновенный HMR)
- **Порты:** PostgreSQL (:5432) и Redis (:6379) доступны с хоста
- **Volumes:** исходный код монтируется напрямую

Переменные:
```bash
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG
DEV_SKIP_AUTH=true   # Отключить аутентификацию (опционально)
```

### 5.2 Production

```bash
# Production-стек
docker compose -f docker-compose.yml \
               -f docker-compose.production.yml up -d

# Или через Makefile
make deploy-prod
```

Отличия production:
- **Образы:** Pre-built из GHCR (не собираются локально)
- **Порты:** БД и Redis **НЕ** проброшены наружу
- **Resource limits:** CPU/RAM лимиты на каждый контейнер
- **Restart:** `restart: always`
- **Workers:** gunicorn с 4 workers (настраивается через `WEB_CONCURRENCY`)

```bash
# .env.local для production
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
WEB_CONCURRENCY=4
```

### 5.3 Serveo Tunnel (удалённый доступ)

Для доступа к платформе из интернета без статического IP:

```bash
# 1. Генерация SSH-ключа (один раз)
make tunnel-keygen

# 2. Регистрация на https://console.serveo.net
#    → Add SSH Key → вставить содержимое infrastructure/tunnel/keys/id_rsa.pub

# 3. Запуск туннеля
make tunnel-up
# → https://sphere.serveousercontent.com

# 4. Синхронизация URL в .env
make tunnel-sync
```

После этого:
- Web UI: `https://sphere.serveousercontent.com`
- API: `https://sphere.serveousercontent.com/api/v1`
- WebSocket: `wss://sphere.serveousercontent.com/ws/`

> **Почему Serveo, а не Cloudflare?** Cloudflare Quick Tunnel дропает idle WebSocket-соединения через 5-50 секунд. Serveo поддерживает persistent WebSocket с keepalive.

---

## 6. Подключение Android-агентов

### 6.1 LDPlayer (эмуляторы)

PC-агент автоматически обнаруживает и регистрирует LDPlayer-эмуляторы:

```bash
# На Windows-машине с LDPlayer
cd pc-agent
pip install -r requirements.txt

# Настроить подключение к серверу
# В .env или переменных окружения:
SPHERE_SERVER_URL=https://sphere.serveousercontent.com
SPHERE_ENROLLMENT_KEY=<ключ из seed_enrollment_key>

# Запустить PC-агент
python main.py
```

PC-агент выполняет:
1. Сканирование запущенных эмуляторов LDPlayer
2. ADB-подключение к каждому
3. Установку SphereAgent APK
4. Авторегистрацию устройств на сервере

### 6.2 Физические устройства

```bash
# 1. Собрать APK (см. 6.3)
# 2. Установить на устройство через ADB
adb install sphere-agent.apk

# 3. Агент автоматически подключится к серверу через config endpoint
```

### 6.3 Сборка enterprise APK

```bash
# Указать URL конфигурации
SPHERE_CONFIG_URL=https://yourdomain.com/api/v1/config/agent \
  make build-apk

# APK будет в: android/app/build/outputs/apk/enterprise/release/
```

Config endpoint автоматически отдаёт агенту:
- `server_url` — адрес WebSocket-сервера
- `enrollment_key` — ключ для авторегистрации
- Текущую версию и URL обновления (OTA)

---

## 7. Настройка SSL/HTTPS

### Let's Encrypt (рекомендуется для production)

```bash
# 1. Указать домен в .env.local
SERVER_HOSTNAME=yourdomain.com

# 2. Убедиться что DNS A-запись указывает на сервер

# 3. Получить сертификат (один раз)
make ssl-init
# Запускает certbot standalone → получает fullchain.pem + privkey.pem

# 4. Перезапустить nginx
docker restart sphere-platform-nginx-1
```

Автообновление: certbot-контейнер проверяет и обновляет сертификат каждые 12 часов.

### Self-signed (для development)

Nginx автоматически создаёт self-signed сертификат при запуске, если Let's Encrypt сертификат отсутствует. Это поведение скрипта `infrastructure/nginx/docker-entrypoint.sh`.

---

## 8. Мониторинг (Prometheus + Grafana)

```bash
# Запуск стека мониторинга
make monitoring

# Сервисы:
# - Prometheus:      http://localhost:9090
# - Grafana:         http://localhost:3001 (admin/admin)
# - Alertmanager:    http://localhost:9093
```

### Что мониторится

| Метрика | Источник | Алерт (P0) |
|---------|----------|-------------|
| HTTP latency p99 | Backend /metrics | > 5s |
| Active WS connections | Backend /metrics | — |
| DB pool utilization | Backend /metrics | > 90% |
| Task queue depth | Backend /metrics | > 100 |
| Agent offline rate | Backend /metrics | > 30% |
| PostgreSQL connections | postgres-exporter | Pool exhausted |
| Redis memory | redis-exporter | > 80% maxmemory |
| Host CPU/RAM/Disk | node-exporter | > 90% |

### Алертинг

- **P0 (Critical):** Telegram + webhook — Backend down, DB pool exhausted, >30% agents offline
- **P1 (Warning):** Webhook — High latency, deep task queue, VPN pool low

Конфигурация алертов: `infrastructure/monitoring/alert-rules.yml`

---

## 9. Бэкапы и восстановление

### Автоматический бэкап

```bash
# Полный бэкап (PostgreSQL + Redis)
./scripts/backup-database.sh

# Только PostgreSQL
./scripts/backup-database.sh --pg-only

# Указать директорию и ротацию
./scripts/backup-database.sh --dir=/mnt/backups --keep=30
```

### Настройка cron (Linux)

```bash
# /etc/cron.d/sphere-backup
# Ежедневно в 03:00 UTC
0 3 * * * root /opt/sphere-platform/scripts/backup-database.sh \
    --dir=/mnt/backups --keep=30 \
    >> /var/log/sphere-backup.log 2>&1
```

### Восстановление

```bash
# PostgreSQL
gunzip < backups/pg_sphereplatform_20260301.sql.gz | \
  docker exec -i sphere-platform-postgres-1 \
    psql -U sphere sphereplatform

# Redis (скопировать RDB)
docker cp backups/redis_snapshot.rdb sphere-platform-redis-1:/data/dump.rdb
docker restart sphere-platform-redis-1
```

### RTO/RPO

| Метрика | Цель |
|---------|------|
| RTO (восстановление) | < 30 минут |
| RPO (потеря данных) | < 24 часа (daily) / < 1 мин (streaming replication) |

---

## 10. Масштабирование

### Горизонтальное масштабирование Backend

Backend полностью stateless — вся координация через Redis Pub/Sub:

```yaml
# docker-compose.production.yml
services:
  backend:
    deploy:
      replicas: 4       # 4 инстанса
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
```

```bash
# Runtime масштабирование
docker compose up -d --scale backend=4
```

### Connection Pooling (PgBouncer)

Для production с множеством реплик backend:

```yaml
pgbouncer:
  image: bitnami/pgbouncer:latest
  environment:
    PGBOUNCER_POOL_MODE: transaction
    PGBOUNCER_MAX_CLIENT_CONN: 1000
```

### Рекомендации по масштабированию

| Устройств | Backend replicas | DB connections | Redis memory |
|-----------|-----------------|----------------|--------------|
| < 100 | 1 | 30 | 256 MB |
| 100–500 | 2 | 60 | 512 MB |
| 500–1000 | 4 | 120 | 1 GB |
| 1000+ | 8 + PgBouncer | 200 | 2 GB |

---

## 11. Структура файлов деплоя

```
📦 Sphere Platform — Deployment Files
│
├── 🐳 Docker Compose
│   ├── docker-compose.yml             # Базовая инфраструктура (PG, Redis, Nginx, n8n, MinIO)
│   ├── docker-compose.full.yml        # + Backend + Frontend (development)
│   ├── docker-compose.override.yml    # Dev-overrides (hot-reload, открытые порты)
│   ├── docker-compose.production.yml  # Production (лимиты, pre-built images)
│   ├── docker-compose.preview.yml     # PR Preview (Traefik, изоляция)
│   └── docker-compose.tunnel.yml      # SSH-туннель (Serveo)
│
├── 🏗️ Dockerfiles
│   ├── backend/Dockerfile             # Production backend (gunicorn, non-root)
│   ├── backend/Dockerfile.dev         # Development backend (uvicorn --reload)
│   ├── frontend/Dockerfile            # Multi-stage Next.js build
│   └── infrastructure/tunnel/Dockerfile # autossh Alpine
│
├── 🔧 Конфигурации
│   ├── infrastructure/nginx/nginx.conf          # Production Nginx (SSL, rate limit)
│   ├── infrastructure/nginx/nginx.dev.conf      # Development Nginx (HTTP-only)
│   ├── infrastructure/postgres/init.sql         # Инициализация БД + extensions
│   ├── infrastructure/postgres/rls_policies.sql # Row-Level Security
│   ├── infrastructure/monitoring/prometheus.yml # Prometheus scrape configs
│   └── alembic/alembic.ini                      # Миграции БД
│
├── 📜 Скрипты
│   ├── scripts/full-deploy.sh         # 🚀 Полное развёртывание (Linux/macOS)
│   ├── scripts/full-deploy.ps1        # 🚀 Полное развёртывание (Windows)
│   ├── scripts/health-check.sh        # 🏥 Проверка здоровья всех сервисов
│   ├── scripts/backup-database.sh     # 💾 Бэкап PostgreSQL + Redis
│   ├── scripts/generate_secrets.py    # 🔐 Генерация криптографических секретов
│   ├── scripts/create_admin.py        # 👤 Создание суперадминистратора
│   ├── scripts/seed_enrollment_key.py # 🔑 Enrollment-ключ для агентов
│   ├── scripts/init_ssl.sh            # 🔒 Let's Encrypt bootstrap
│   └── scripts/sync-tunnel-url.sh     # 🌐 Синхронизация URL туннеля
│
├── 🌍 Шаблоны окружения
│   ├── .env.example                   # Шаблон всех переменных (50+)
│   └── frontend/.env.example          # Frontend-specific переменные
│
└── 📋 Makefile                        # 30+ шорткатов для всех операций
```

---

## 12. Переменные окружения

### Критические (обязательные)

| Переменная | Описание | Генерация |
|-----------|----------|-----------|
| `POSTGRES_PASSWORD` | Пароль PostgreSQL | `generate_secrets.py` |
| `REDIS_PASSWORD` | Пароль Redis | `generate_secrets.py` |
| `JWT_SECRET_KEY` | Ключ подписи JWT (512 бит) | `generate_secrets.py` |
| `POSTGRES_URL` | Connection string БД | Автоматически |
| `REDIS_URL` | Connection string Redis | Автоматически |

### Сервер и домен

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `SERVER_HOSTNAME` | Домен для Nginx + SSL | `adb.example.com` |
| `SERVER_PUBLIC_URL` | Публичный URL (для агентов) | `https://adb.example.com` |
| `SPHERE_CONFIG_URL` | Config endpoint для APK | `https://adb.example.com/api/v1/config/agent` |
| `CORS_EXTRA_ORIGINS` | Дополнительные CORS-домены | `https://sphere.serveousercontent.com` |

### Приложение

| Переменная | Описание | По умолчанию |
|-----------|----------|-------------|
| `ENVIRONMENT` | `development` / `staging` / `production` | `development` |
| `DEBUG` | Режим отладки | `false` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |
| `WEB_CONCURRENCY` | Количество gunicorn-воркеров | `4` |
| `DEV_SKIP_AUTH` | Пропуск аутентификации (dev) | пусто |

### VPN / WireGuard

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `WG_ROUTER_URL` | URL WireGuard-маршрутизатора | `http://vpn.example.com:8000` |
| `WG_ROUTER_API_KEY` | API-ключ маршрутизатора | `secret-key` |
| `AWG_H1`..`AWG_H4` | AmneziaWG obfuscation headers | Генерируются автоматически |

Полная документация: [docs/configuration.md](docs/configuration.md)

---

## 13. Скрипты автоматизации

### Makefile-шорткаты

```bash
# ── Запуск ──────────────────────────────
make setup          # Первоначальная настройка (секреты + pre-commit)
make dev            # Только инфраструктура (PG, Redis, Nginx)
make full           # Полный стек (+ backend + frontend)
make start          # Полный стек + SSH-туннель
make down           # Остановить всё

# ── База данных ─────────────────────────
make migrate        # Alembic upgrade head
make migrate-new    # Создать новую миграцию (name=описание)

# ── SSL ─────────────────────────────────
make ssl-init       # Получить Let's Encrypt (первый раз)
make ssl-renew      # Принудительное обновление

# ── Туннель ─────────────────────────────
make tunnel-keygen  # Генерация SSH-ключа
make tunnel-up      # Запустить Serveo-туннель
make tunnel-down    # Остановить туннель
make tunnel-sync    # Синхронизировать URL в .env

# ── Сборка ──────────────────────────────
make rebuild-backend   # Пересобрать backend
make rebuild-frontend  # Пересобрать frontend
make build-apk         # Собрать Android APK

# ── Production ──────────────────────────
make deploy-prod       # Полный production-деплой
make seed-enrollment   # Создать enrollment-ключ
make monitoring        # Запустить Prometheus + Grafana

# ── Тестирование ────────────────────────
make test           # pytest с покрытием
make lint           # ruff + mypy
make security       # bandit + pip-audit
make rls-lint       # Проверка RLS-политик
```

### Standalone-скрипты

| Скрипт | Описание | Использование |
|--------|----------|---------------|
| `full-deploy.sh` | Полное развёртывание (Linux) | `./scripts/full-deploy.sh` |
| `full-deploy.ps1` | Полное развёртывание (Windows) | `.\scripts\full-deploy.ps1` |
| `health-check.sh` | Проверка здоровья | `./scripts/health-check.sh [--json]` |
| `backup-database.sh` | Бэкап БД + Redis | `./scripts/backup-database.sh` |
| `generate_secrets.py` | Генерация секретов | `python scripts/generate_secrets.py` |
| `create_admin.py` | Создание админа | Внутри контейнера |
| `seed_enrollment_key.py` | Enrollment-ключ | `make seed-enrollment` |
| `init_ssl.sh` | SSL bootstrap | `make ssl-init` |
| `deploy.ps1` | Quick deploy (Windows) | `.\scripts\deploy.ps1` |

---

## 14. Устранение неполадок

### Backend не запускается

```bash
# Проверить логи
docker logs sphere-platform-backend-1 --tail=50

# Частые причины:
# 1. Нет .env.local → python scripts/generate_secrets.py --output .env.local
# 2. БД не готова  → docker restart sphere-platform-postgres-1; sleep 10
# 3. Миграции      → docker compose exec backend alembic upgrade head
# 4. Порт занят    → lsof -i :8000 (Linux) / netstat -ano | findstr 8000 (Win)
```

### Frontend — белый экран

```bash
docker logs sphere-platform-frontend-1 --tail=30

# Часто: node_modules не установились
docker restart sphere-platform-frontend-1
# → npm install запустится автоматически при старте
```

### WebSocket не подключается

```bash
# Проверить что nginx проксирует WebSocket
grep "upgrade" infrastructure/nginx/nginx.conf

# Проверить Redis PubSub
docker exec sphere-platform-redis-1 redis-cli -a $REDIS_PASSWORD PUBSUB CHANNELS "*"

# Backend WebSocket логи
docker logs sphere-platform-backend-1 | grep -i "websocket\|ws\|upgrade"
```

### 502 Bad Gateway

```bash
# Nginx не может достучаться до backend
# 1. Проверить что backend запущен
docker ps | grep backend

# 2. Проверить сеть
docker network inspect sphere-platform_frontend-net

# 3. Перезапустить
docker restart sphere-platform-backend-1
sleep 5
docker restart sphere-platform-nginx-1
```

### Миграции не проходят

```bash
# Проверить текущую ревизию
docker compose exec backend alembic current

# Посмотреть историю
docker compose exec backend alembic history --verbose

# Множественные heads (после параллельной разработки)
make alembic-merge-heads
make migrate
```

### Туннель отвалился

```bash
# Проверить статус
docker logs sphere-tunnel --tail=20

# Перезапустить
make tunnel-down
make tunnel-up

# Проверить
curl https://sphere.serveousercontent.com/api/v1/health
```

---

## 15. Checklist перед продакшеном

### Безопасность

- [ ] Все секреты уникальны и > 32 символов
- [ ] `JWT_SECRET_KEY` — минимум 64 символа (512 бит)
- [ ] `.env.local` НЕ закоммичен (проверь `.gitignore`)
- [ ] `DEBUG=false` в production
- [ ] `DEV_SKIP_AUTH` пустой или не задан
- [ ] PostgreSQL и Redis порты **НЕ** проброшены наружу
- [ ] SSL-сертификат установлен и автообновляется
- [ ] Firewall: только порты 80, 443 (и 51820 для VPN)

### Инфраструктура

- [ ] Docker-образы собраны (или подтянуты из GHCR)
- [ ] Alembic-миграции применены (`alembic current` совпадает с `alembic heads`)
- [ ] PostgreSQL: healthcheck `healthy`
- [ ] Redis: healthcheck `healthy`, `PING` → `PONG`
- [ ] Nginx: SSL работает, HTTP → HTTPS redirect
- [ ] certbot: автообновление каждые 12ч

### Приложение

- [ ] Суперадминистратор создан
- [ ] Enrollment-ключ сгенерирован (для агентов)
- [ ] Health endpoint отвечает: `GET /api/v1/health → {"status":"ok"}`
- [ ] Web UI загружается на `https://yourdomain.com`
- [ ] WebSocket подключается: `wss://yourdomain.com/ws/`
- [ ] Swagger доступен: `https://yourdomain.com/docs`

### Мониторинг

- [ ] Prometheus собирает метрики
- [ ] Grafana дашборд настроен
- [ ] P0 алерты настроены (Telegram / webhook)
- [ ] Бэкапы автоматизированы (cron)

### Масштабирование

- [ ] `WEB_CONCURRENCY` настроен под CPU (рекомендация: 2 × CPU cores + 1)
- [ ] PostgreSQL: `max_connections` достаточно для реплик
- [ ] Redis: `maxmemory` настроен
- [ ] Resource limits в docker-compose.production.yml

---

> **Готово!** После прохождения этого чеклиста платформа полностью готова к production-эксплуатации.
>
> Следующие шаги:
> - Подключить Android-агенты (Section 6)
> - Создать первый скрипт автоматизации через Web UI
> - Настроить n8n-воркфлоу для внешних интеграций
> - Настроить pipeline-оркестрацию и cron-расписания
>
> Документация: [docs/](docs/) · API: [docs/api-reference.md](docs/api-reference.md) · Web UI: [docs/web-ui-guide.md](docs/web-ui-guide.md)

### Проверенная граница Bash launcher (AUD-79)

Dev/production Compose arguments теперь передаются массивом при штатном `IFS`.
Проверены build и bootstrap с настоящим preamble и процессом вместо Docker;
полный deployment набор — 37 passing cases. Env-file, migrations/API ordering,
готовность сервисов и реальный APK/VPN остаются в [приёмке пилота](docs/operations/PILOT-ACCEPTANCE.md).

### Windows: источник конфигурации (AUD-80)

`full-deploy.ps1` выбирает `.env.local`, затем `.env` в корне установки и передаёт
абсолютный путь через Compose `--env-file`. Оба YAML paths также абсолютные.
Файлы не объединяются; shell/process env сохраняет приоритет. Отсутствие обоих
останавливает wrapper до Docker. Штатный `start-dev.ps1` config/build/up имеет
тот же выбор, а при отсутствии обоих создаёт только template и требует заполнения.
Legacy start-dev Status/Down/Tunnel и остальные этапы full-deploy требуют отдельной
приёмки. [Текущий план](docs/operations/PILOT-ACCEPTANCE.md).

### Bootstrap tools внутри production image (AUD-81)

Два CLI администратора/enrollment теперь входят в backend image. До исправления
dev mount скрывал отсутствие `/app/scripts`, а production exec падал до SQL.
Настоящий container probe проверяет CLI validation, Alembic head и non-root/read-only
режим; четыре cases проходят и включены в отдельный CI job. Полный bootstrap,
порядок миграций/API и установленный APK остаются в [плане приёмки](docs/operations/PILOT-ACCEPTANCE.md).

## Повторный запуск с существующими секретами

`.env.local` имеет приоритет; если его нет, существующий `.env` сохраняется и
используется без создания нового файла с другими паролями (AUD-84). Headless
и skip-secrets учитывают оба пути. Fresh setup создаёт `.env.local`, если нет
обоих файлов. Не считайте ручную перегенерацию ротацией уже инициализированных
PostgreSQL/Redis: это требует согласованного обновления сервисов и backup.
[Контракт повторного запуска](docs/operations/STARTUP.md).

## Пароль администратора при повторном full-deploy

AUD-85 добавляет `--create-only`: existing active super_admin сохраняет пароль/роль/MFA;
candidate `SPHERE_ADMIN_PASSWORD` действует только для новой записи. После confirmed
creation credentials выводятся до enrollment, а Bash сохраняет их в `.admin-credentials`.
Поздний отказ не является общим успехом, но уже созданный пароль доступен. При existing
кандидат не выводится и credential file не перезаписывается. Намеренный reset через
direct CLI без флага остаётся отдельной операцией. [Полный контракт и ограничения](docs/operations/STARTUP.md).

## Если backend раньше падал на DEV_SKIP_AUTH

AUD-86 исправляет default full Compose: отсутствующее/пустое значение теперь
становится `false`, а не строкой, которую Settings не может распознать. Не требуется
включать обход авторизации или добавлять обязательный параметр в существующий dotenv.
[Подробный startup contract](docs/operations/STARTUP.md). Полная приёмка стека/APK
по-прежнему описана в [плане пилота](docs/operations/PILOT-ACCEPTANCE.md).
