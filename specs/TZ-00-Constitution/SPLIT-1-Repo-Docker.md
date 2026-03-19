# SPLIT-1 — Репозиторий, Git Flow, Docker Compose Infrastructure

**ТЗ-родитель:** TZ-00-Constitution  
**Ветка:** `stage/0-constitution`  
**Задача:** `SPHERE-001`  
**Исполнитель:** DevOps  
**Оценка:** 1 рабочий день  
**Блокирует:** ВСЕ остальные задачи — без этого сплита никто не может начать работу

---

## Цель Сплита

Создать монорепозиторий со структурой директорий, Git Flow, защитой веток, pre-commit хуками, и Docker Compose стеком. После выполнения — **все 10 параллельных потоков могут клонировать репо и начать работу в своих ветках**.

---

## Предусловия

- [ ] GitHub репозиторий `sphere-platform` создан (новый, не существующий)
- [ ] Docker Desktop установлен на сервере разработки
- [ ] Make установлен (WSL/Git Bash на Windows)
- [ ] Python 3.12+ и Node.js 20+ установлены для локального dev

---

## Шаг 1 — Структура директорий

```bash
mkdir -p backend/{api/v1,api/ws,core,database,middleware,models,schemas,services,websocket,monitoring,updates}
mkdir -p backend/api/v1/{auth,devices,vpn,scripts,tasks,schedules,workstations,n8n}
mkdir -p frontend/{app,components,lib,hooks,types,public}
mkdir -p android/app/src/main/kotlin/com/sphereplatform/agent/{service,ws,commands,lua,encoder,vpn,updates}
mkdir -p pc-agent/{core,ldplayer,adb,telemetry,ws}
mkdir -p n8n-nodes/nodes/{ADBDevicePool,ADBExecuteScript,ADBEventTrigger}
mkdir -p infrastructure/{nginx,postgres,redis,monitoring}
mkdir -p .github/{workflows,ISSUE_TEMPLATE}
```

**Финальная структура:**

```
sphere-platform/
├── backend/                   ← FastAPI (Python 3.12)
│   ├── api/v1/                ← REST endpoints, 350+
│   ├── api/ws/                ← WebSocket handlers
│   ├── core/                  ← config, security, logging
│   ├── database/              ← engine, migrations
│   ├── middleware/            ← rate_limit, prometheus, cors
│   ├── models/                ← SQLAlchemy ORM (35+ моделей)
│   ├── schemas/               ← Pydantic request/response
│   ├── services/              ← бизнес-логика (50+ сервисов)
│   ├── websocket/             ← ConnectionManager
│   ├── monitoring/            ← Prometheus collectors
│   ├── main.py
│   └── requirements.txt
├── frontend/                  ← Next.js 15 (App Router)
│   ├── app/                   ← 28 страниц
│   ├── components/
│   ├── lib/
│   └── package.json
├── android/                   ← SphereAgent APK (Kotlin 2.0)
│   └── app/
├── pc-agent/                  ← PC Agent daemon (Python)
│   └── main.py
├── n8n-nodes/                 ← Custom n8n nodes (TypeScript)
│   └── package.json
├── infrastructure/
│   ├── nginx/nginx.conf
│   ├── postgres/init.sql
│   └── monitoring/
├── alembic/                   ← DB миграции
│   └── versions/
├── tests/                     ← Unit + Integration тесты
├── docker-compose.yml
├── docker-compose.full.yml
├── docker-compose.production.yml
├── Makefile
├── .env.example
└── .gitignore
```

---

## Шаг 2 — .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage

# Node
node_modules/
.next/
dist/
build/

# Android
android/.gradle/
android/app/build/
android/*.keystore
android/local.properties

# Secrets — НИКОГДА не коммитить
.env
.env.local
.env.production
*.pem
*.key
*.p12
secrets/

# IDE
.idea/
.vscode/settings.json
*.swp

# Docker
volumes/
postgres_data/
redis_data/
```

---

## Шаг 3 — Git Branch Strategy + Рабочая Среда

### Ветки

```
main                ← production-ready, защищена, только через PR с review
develop             ← staging, интеграция готовых этапов
stage/0-constitution  }
stage/1-auth          }  ← параллельные ветки разработки
stage/2-device-registry }    (feature branches для каждого этапа TZ)
stage/3-websocket     }
...                   }
hotfix/*            ← экстренные фиксы прямо от main
```

### КРИТИЧЕСКИ ВАЖНО — Модель работы: git worktree

> **Проблема одного IDE:** Все параллельные этапы (1-11) разрабатываются в одном IDE, одной машине.
> Если всё работает в одной папке `sphere-platform/`, переключение веток между чатами ИИ = конфликты.
>
> **Решение: `git worktree`** — каждый этап получает ОТДЕЛЬНУЮ папку на диске, все папки разделяют один `.git`.
> Агент открывает СВОЮ папку. `git checkout` не нужен НИКОГДА.

**Структура папок на диске после `make worktree-setup`:**

```
C:\Users\dimas\Documents\
├── sphere-platform\          ← базовая папка (develop/main), DevOps
├── sphere-stage-1\           ← stage/1-auth          → Разработчик TZ-01
├── sphere-stage-2\           ← stage/2-device-registry → Разработчик TZ-02
├── sphere-stage-3\           ← stage/3-websocket      → Разработчик TZ-03
├── sphere-stage-4\           ← stage/4-scripts        → Этап TZ-04
├── sphere-stage-5\           ← stage/5-streaming      → Этап TZ-05
├── sphere-stage-6\           ← stage/6-vpn            → Этап TZ-06
├── sphere-stage-7\           ← stage/7-android        → Этап TZ-07
├── sphere-stage-8\           ← stage/8-pc-agent       → Этап TZ-08
├── sphere-stage-9\           ← stage/9-n8n            → Этап TZ-09
├── sphere-stage-10\          ← stage/10-frontend      → Этап TZ-10
└── sphere-stage-11\          ← stage/11-monitoring    → Этап TZ-11
```

**Правила для КАЖДОГО исполнителя этапа:**

| Разрешено | ЗАПРЕЩЕНО |
|---|---|
| `git add` + `git commit` + `git push origin stage/N-name` | `git checkout <любая-ветка>` ❌ |
| Создавать файлы в своих папках (`backend/api/v1/NAME/`) | `git merge` / `git rebase` ❌ |
| Открывать PR `stage/N` → `develop` | `git push --force` ❌ |
| Читать общие файлы | Редактировать `backend/main.py` 🔴 |
| | Редактировать `backend/core/` 🔴 |

**GitHub Branch Protection (main):**

```
Required status checks before merging:
  ✅ tests / unit-tests
  ✅ tests / integration-tests
  ✅ lint / ruff + mypy
  ✅ security / bandit + pip-audit

Required reviews: 1
Dismiss stale reviews when new commits pushed: true
Require linear history: true (no merge commits in main)
```

---

## Шаг 4 — docker-compose.yml (dev окружение)

```yaml
# docker-compose.yml — только инфраструктура (PG, Redis, Nginx, n8n)
# NOTE: поле version устарело в Docker Compose v2+ и убрано намеренно

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: sphereplatform
      POSTGRES_USER: ${POSTGRES_USER:-sphere}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"          # только в dev! в production нет
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infrastructure/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-sphere}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - backend-net

  redis:
    image: redis:7.2-alpine
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --appendonly yes
      --appendfsync everysec
      --save ""
    ports:
      - "6379:6379"          # только в dev!
    healthcheck:
      # FIX: пароль через REDISCLI_AUTH — не виден в docker inspect
      test: ["CMD-SHELL", "REDISCLI_AUTH=\"$$REDIS_PASSWORD\" redis-cli ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - backend-net

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./infrastructure/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./infrastructure/nginx/ssl:/etc/nginx/ssl:ro
    # FIX: зависимость nginx от postgres была бессмысленной (nginx не работает с PG напрямую).
    # nginx стартует сразу и ждёт бэкенд по сети — backend задаётся в docker-compose.full.yml.
    networks:
      - frontend-net
    restart: unless-stopped

  n8n:
    image: n8nio/n8n:latest
    ports:
      - "5678:5678"
    environment:
      - N8N_HOST=localhost
      - N8N_PORT=5678
      - N8N_PROTOCOL=http
      - DB_TYPE=postgresdb
      - DB_POSTGRESDB_HOST=postgres
      - DB_POSTGRESDB_DATABASE=n8n
      - DB_POSTGRESDB_USER=${POSTGRES_USER:-sphere}
      - DB_POSTGRESDB_PASSWORD=${POSTGRES_PASSWORD}
      - N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - backend-net
      - frontend-net

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "${FRONTEND_PORT:-3000}:3000"   # S3 API
      - "9001:9001"   # Web Console
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}
    volumes:
      - minio_data:/data
    networks:
      - backend-net
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      timeout: 5s
      retries: 5
    # MED-10: TZ-04 SPLIT-5 использует MinIO для хранения скриншотов устройств

volumes:
  postgres_data:
  redis_data:
  minio_data:

networks:
  frontend-net:
    driver: bridge
  backend-net:
    driver: bridge
    # NOTE: internal: true УДАЛЕНО намеренно.
    # Backend должен достигать внешних хостов:
    #   - TZ-06: WireGuard/AmneziaWG router (внешний VPS)
    #   - n8n:   исходящие webhook-запросы к внешним API
    # Изоляция обеспечивается на уровне Nginx (только /api/, /ws/ наружу).
```

---

## Шаг 4.1 — infrastructure/postgres/init.sql

```sql
-- infrastructure/postgres/init.sql
-- Выполняется при первом старте PostgreSQL-контейнера.
-- Алембик создаёт таблицы. Этот файл только создаёт ДОПОЛНИТеЛЬНЫЕ БД и настраивает роли.

-- БД n8n: Docker-образ создаёт только POSTGRES_DB=sphereplatform.
-- FIX: n8n требует базу «n8n» — без CREATE DATABASE n8n n8n упадёт с ошибкой «database "n8n" does not exist».
CREATE DATABASE n8n
    WITH OWNER = sphere
    ENCODING = 'UTF8'
    LC_COLLATE = 'C'
    LC_CTYPE = 'C'
    TEMPLATE = template0;

-- Расширение умолчания search_path для основной БД
\c sphereplatform
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- функции LIKE-поиска
CREATE EXTENSION IF NOT EXISTS "btree_gin"; -- композитные GIN-индексы
```

---

## Шаг 5 — docker-compose.full.yml (весь стек)

```yaml
# docker-compose.full.yml — добавляем backend + frontend
# NOTE: поле version устарело в Docker Compose v2+ и убрано намеренно

# Включает всё из docker-compose.yml + добавляет:
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    environment:
      - POSTGRES_URL=postgresql+asyncpg://sphere:CHANGE_ME@localhost:5432/sphereplatform${POSTGRES_PASSWORD}@postgres:5432/sphereplatform
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - WG_ROUTER_URL=${WG_ROUTER_URL}
      - WG_ROUTER_API_KEY=${WG_ROUTER_API_KEY}
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./backend:/app           # hot reload в dev
      - ./backend/updates:/app/updates  # OTA APK файлы
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
    networks:
      - frontend-net
      - backend-net

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
      - NEXT_PUBLIC_WS_URL=ws://localhost:8000
    ports:
      - "3002:3002"
    volumes:
      - ./frontend:/app
      - /app/node_modules         # анонимный volume для node_modules
    command: npm run dev -- -p 3002
    networks:
      - frontend-net
```

---

## Шаг 6 — backend/Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python зависимости (отдельный слой для кэша)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходный код
COPY . .

# Запуск от non-root пользователя
RUN useradd -r -u 1001 sphere
USER sphere

EXPOSE 8000

# Production: без --reload, с worker limits для graceful restart
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100"]
```

---

## Шаг 7 — Makefile

```makefile
.DEFAULT_GOAL := help

.PHONY: help setup dev full down test lint security migrate build logs

help:          ## Показать помощь
 @grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup:         ## Первоначальная настройка: создать .env, pre-commit
 @cp -n .env.example .env.local || true
 @pip install pre-commit
 @pre-commit install --install-hooks
 # Windows: без longpaths Kotlin-пути android/app/src/main/kotlin/... > 260 символов не создадутся
 git config core.longpaths true
 @echo "✅ Настройка завершена. Заполни .env.local и запусти 'make branches' затем 'make worktree-setup'"

branches:      ## Создать все stage-ветки в удалённом репозитории (выполнить один раз)
 @echo "Создаём все stage-ветки от develop..."
 git checkout develop && git pull origin develop
 git checkout -b stage/1-auth        && git push -u origin stage/1-auth        && git checkout develop
 git checkout -b stage/2-device-registry && git push -u origin stage/2-device-registry && git checkout develop
 git checkout -b stage/3-websocket   && git push -u origin stage/3-websocket   && git checkout develop
 git checkout -b stage/4-scripts     && git push -u origin stage/4-scripts     && git checkout develop
 git checkout -b stage/5-streaming   && git push -u origin stage/5-streaming   && git checkout develop
 git checkout -b stage/6-vpn         && git push -u origin stage/6-vpn         && git checkout develop
 git checkout -b stage/7-android     && git push -u origin stage/7-android     && git checkout develop
 git checkout -b stage/8-pc-agent    && git push -u origin stage/8-pc-agent    && git checkout develop
 git checkout -b stage/9-n8n         && git push -u origin stage/9-n8n         && git checkout develop
 git checkout -b stage/10-frontend   && git push -u origin stage/10-frontend   && git checkout develop
 git checkout -b stage/11-monitoring && git push -u origin stage/11-monitoring  && git checkout develop
 @echo "✅ Все ветки созданы"

worktree-setup: ## Создать изолированные папки для каждого этапа (выполнить один раз после 'make branches')
 @echo "Создаём git worktrees для всех этапов..."
 git worktree add ../sphere-stage-1  stage/1-auth         2>/dev/null || echo "sphere-stage-1 уже существует"
 git worktree add ../sphere-stage-2  stage/2-device-registry 2>/dev/null || echo "sphere-stage-2 уже существует"
 git worktree add ../sphere-stage-3  stage/3-websocket    2>/dev/null || echo "sphere-stage-3 уже существует"
 git worktree add ../sphere-stage-4  stage/4-scripts      2>/dev/null || echo "sphere-stage-4 уже существует"
 git worktree add ../sphere-stage-5  stage/5-streaming    2>/dev/null || echo "sphere-stage-5 уже существует"
 git worktree add ../sphere-stage-6  stage/6-vpn          2>/dev/null || echo "sphere-stage-6 уже существует"
 git worktree add ../sphere-stage-7  stage/7-android      2>/dev/null || echo "sphere-stage-7 уже существует"
 git worktree add ../sphere-stage-8  stage/8-pc-agent     2>/dev/null || echo "sphere-stage-8 уже существует"
 git worktree add ../sphere-stage-9  stage/9-n8n          2>/dev/null || echo "sphere-stage-9 уже существует"
 git worktree add ../sphere-stage-10 stage/10-frontend    2>/dev/null || echo "sphere-stage-10 уже существует"
 git worktree add ../sphere-stage-11 stage/11-monitoring  2>/dev/null || echo "sphere-stage-11 уже существует"
 @echo ""
 @echo "✅ Worktree-среды готовы!"
 @echo "   Передавай разработчику папку C:\\Users\\USERNAME\\Documents\\sphere-stage-N"
 @echo "   Агент работает ТОЛЬКО в своей папке, ветки не переключает."
 @echo "   ОБЯЗАТЕЛЬНО: Синхронизация с ядром каждые 24 часа: git fetch origin develop && git merge origin/develop"
 @echo "   ПРАВИЛО PHASE 0: Бэкенд сперва генерирует openapi.json и Pydantic схемы -> PR Contract Merge."
 @echo "   Frontend (TZ-10) ждет ТОЛЬКО Contract Merge, чтобы начать работу параллельно с бэкендом!"
 @git worktree list

dev:           ## Запустить инфраструктуру (PG, Redis, Nginx, n8n)
 docker compose up -d
 @echo "✅ Инфраструктура запущена"
 @echo "   PG:    localhost:5432"
 @echo "   Redis: localhost:6379"
 @echo "   n8n:   http://localhost:5678"
 @echo ""
 @echo "Запусти backend: cd backend && uvicorn main:app --reload"

full:          ## Запустить весь стек в Docker
 # FIX: оба файла нужны — docker-compose.full.yml ТОЛЬКО добавляет backend+frontend,
 # без docker-compose.yml не будет postgres/redis/nginx/n8n.
 docker compose -f docker-compose.yml -f docker-compose.full.yml up -d

down:          ## Остановить всё
 docker compose down

test:          ## Тесты с покрытием
 pytest tests/ -v --cov=backend --cov-report=term-missing --cov-fail-under=80

lint:          ## Линтинг: ruff + mypy
 ruff check backend/ tests/
 mypy backend/ --ignore-missing-imports

security:      ## Безопасность: bandit + pip-audit
 bandit -r backend/ -c .bandit -ll
 pip-audit -r backend/requirements.txt

migrate:       ## Применить миграции
 alembic upgrade head

migrate-new:   ## Создать миграцию (name=описание)
 alembic revision --autogenerate -m "$(name)"

build:         ## Собрать production Docker образы
 docker compose -f docker-compose.production.yml build

monitoring:    ## Запустить Prometheus + Grafana
 docker compose -f infrastructure/monitoring/docker-compose.monitoring.yml up -d

logs:          ## Логи backend
 docker compose -f docker-compose.full.yml logs -f backend

alembic-check: ## Проверить наличие множественных Alembic heads (CI)
 @python -c "import subprocess, sys; \
  r = subprocess.run(['alembic', 'heads'], capture_output=True, text=True); \
  heads = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]; \
  print(f'Alembic heads: {len(heads)}'); \
  [print(f'  {h}') for h in heads]; \
  sys.exit(1 if len(heads) > 1 else 0)"

alembic-merge-heads: ## Автослияние множественных Alembic heads после merge stage-веток
 @echo "Проверяем количество Alembic heads..."
 @HEADS=$$(alembic heads 2>/dev/null | wc -l); \
 if [ "$$HEADS" -le 1 ]; then \
  echo "✅ Одна head — merge не нужен"; \
 else \
  echo "⚠️  Найдено $$HEADS heads — выполняем merge..."; \
  alembic merge heads -m "merge_parallel_stage_migrations"; \
  echo "✅ Heads объединены. Запусти: alembic upgrade head"; \
 fi

rls-lint:      ## Проверить что все таблицы с org_id имеют RLS policy
 @python scripts/check_rls.py
```

---

## Шаг 8 — pre-commit конфигурация

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=500']
      - id: detect-private-key    # блокирует случайный commit ключей
      - id: check-merge-conflict

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

---

## Шаг 9 — CODEOWNERS

```
# .github/CODEOWNERS
# Каждый PR автоматически назначает ревьюера по файлам.
# Правила ниже УПОРЯДОЧЕНЫ: более конкретные — внизу, переопределяют общие.

# ━━━ Общие (fallback) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/backend/                              @backend-lead
/android/                              @android-lead
/pc-agent/                             @backend-lead
/frontend/                             @frontend-lead
/n8n-nodes/                            @frontend-lead @backend-lead
/infrastructure/                       @devops-lead
/docker-compose*.yml                   @devops-lead
/.github/workflows/                    @devops-lead @backend-lead
/Makefile                              @devops-lead

# ━━━ TZ-00 Foundation (ЗАМОРОЖЕННЫЕ файлы — 2 approvals) ━━━━━━━━━━━━
/backend/main.py                       @backend-lead @devops-lead
/backend/database/engine.py            @backend-lead
/backend/core/config.py                @backend-lead
/backend/core/lifespan_registry.py     @backend-lead
/backend/models/__init__.py            @backend-lead
/alembic/                              @backend-lead

# ━━━ TZ-01 Auth ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/backend/api/v1/auth/                  @tz01-lead
/backend/services/auth_service.py      @tz01-lead
/backend/core/security.py              @tz01-lead @security-lead
/backend/middleware/tenant_middleware.py @tz01-lead

# ━━━ TZ-02 Device Registry ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/backend/api/v1/devices/               @tz02-lead
/backend/services/device_service.py    @tz02-lead
/backend/services/device_discovery.py  @tz02-lead

# ━━━ TZ-03 WebSocket Layer ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/backend/api/ws/                       @tz03-lead
/backend/websocket/                    @tz03-lead

# ━━━ TZ-04 Script Engine ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/backend/api/v1/scripts/               @tz04-lead
/backend/services/task_service.py      @tz04-lead
/backend/services/task_queue.py        @tz04-lead
/backend/services/screenshot_storage.py @tz04-lead

# ━━━ TZ-05 H264 Streaming ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/backend/api/v1/streaming/             @tz05-lead
/android/streaming/                    @tz05-lead @android-lead
/frontend/lib/h264/                    @tz05-lead @frontend-lead

# ━━━ TZ-06 VPN AmneziaWG ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/backend/api/v1/vpn/                   @tz06-lead
/backend/services/vpn/                 @tz06-lead
/android/vpn/                          @tz06-lead @android-lead

# ━━━ TZ-07 Android Agent ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/android/                              @tz07-lead @android-lead

# ━━━ TZ-08 PC Agent ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/pc-agent/                             @tz08-lead

# ━━━ TZ-09 n8n Integration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/n8n-nodes/                            @tz09-lead
/backend/services/webhook_service.py   @tz04-lead @tz09-lead

# ━━━ TZ-10 Web Frontend ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/frontend/                             @tz10-lead @frontend-lead

# ━━━ TZ-11 Monitoring ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/infrastructure/monitoring/            @tz11-lead @devops-lead
/backend/metrics.py                    @tz11-lead
/backend/api/v1/metrics/               @tz11-lead

# ━━━ Security-sensitive (2 approvals обязательны) ━━━━━━━━━━━━━━━━━━━
/.env*                                 @security-lead @backend-lead
/infrastructure/postgres/rls_policies.sql @backend-lead @security-lead
/scripts/check_rls.py                  @backend-lead @security-lead
```

---

## Шаг 10 — PR Template

```markdown
<!-- .github/pull_request_template.md -->
## Описание
<!-- Краткое описание изменений -->

## Тип изменения
- [ ] ✨ feat: новая функция
- [ ] 🐛 fix: исправление бага
- [ ] 🔒 security: исправление безопасности
- [ ] ♻️ refactor: рефакторинг
- [ ] 📝 docs: документация
- [ ] ⚡ perf: оптимизация

## Связано с
<!-- SPHERE-XXX или ссылка на issue -->

## Checklist
- [ ] Тесты написаны и проходят
- [ ] `ruff check` проходит без ошибок
- [ ] `mypy` проходит без ошибок
- [ ] Нет секретов в коде (detect-secrets clean)
- [ ] Миграции обратимы (downgrade работает)
- [ ] API backward-compatible (или отмечено BREAKING CHANGE)

## Security Checklist
- [ ] Нет SQL injection (используем ORM/параметризованные запросы)
- [ ] Нет XSS (шаблоны экранируются)
- [ ] Нет IDOR (проверка org_id/user_id)
- [ ] RBAC проверки на всех endpoints
- [ ] Rate limiting на публичных endpoints
```

---

## Шаг 11 — Issue Templates

```yaml
# .github/ISSUE_TEMPLATE/bug_report.yml
name: 🐛 Bug Report
description: Сообщить об ошибке
labels: [bug]
body:
  - type: textarea
    id: description
    attributes:
      label: Описание бага
      placeholder: Что произошло?
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: Шаги воспроизведения
      value: |
        1. Перейти на '...'
        2. Нажать '...'
        3. Результат: ...
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Ожидаемое поведение
  - type: dropdown
    id: severity
    attributes:
      label: Серьёзность
      options:
        - P0 — Critical (production down)
        - P1 — High (major feature broken)
        - P2 — Medium (workaround exists)
        - P3 — Low (cosmetic)
```

```yaml
# .github/ISSUE_TEMPLATE/feature_request.yml
name: ✨ Feature Request
description: Предложить новую функцию
labels: [enhancement]
body:
  - type: textarea
    id: problem
    attributes:
      label: Проблема
      placeholder: Какую проблему это решает?
    validations:
      required: true
  - type: textarea
    id: solution
    attributes:
      label: Предлагаемое решение
    validations:
      required: true
```

---

## Шаг 12 — Conventional Commits

**Обязательный формат коммитов для всех разработчиков:**

```
<type>(<scope>): <description>

[body]

[footer(s)]
```

**Типы:**

```
feat     — новая функция
fix      — исправление бага
security — исправление безопасности
docs     — документация
style    — форматирование
refactor — рефакторинг
perf     — оптимизация
test     — тесты
ci       — CI/CD
chore    — рутинные задачи
```

**Scopes:** `auth`, `devices`, `ws`, `vpn`, `scripts`, `streaming`, `agent`, `pc-agent`, `n8n`, `frontend`, `monitoring`, `db`, `ci`

**Примеры:**

```
feat(auth): add API key authentication for n8n integration
fix(ws): resolve memory leak in ConnectionManager heartbeat loop
security(agent): block Lua metatable escape in sandbox
perf(db): add composite GIN index on devices.tags
BREAKING CHANGE: remove deprecated /api/v0/ endpoints
```

---

## Шаг 13 — Semantic Versioning

```
# VERSION файл
v4.0.0

# Стратегия:
# MAJOR (5.0.0) — breaking API changes
# MINOR (4.1.0) — новые фичи, backward-compatible
# PATCH (4.0.1) — bug fixes
```

**Changelog автоматизация (release workflow):**

```yaml
# .github/workflows/release.yml (см. SPLIT-5)
# При push tag v*.*.* → генерирует CHANGELOG из Conventional Commits
```

---

## Шаг 14 — Code Review Guidelines

**Правила code review для всех потоков:**

| Правило | Описание |
|---------|----------|
| **Max PR size** | ≤400 строк изменений (исключая тесты) |
| **Review time** | < 24 часов рабочего времени |
| **Approvals** | main: 2 approvals, develop: 1 approval |
| **Блокеры** | Security issue, failing tests, missing migration |
| **Stale dismissal** | При новых коммитах старые approvals сбрасываются |
| **Self-merge** | Запрещено для main, разрешено для develop (после approval) |

**Чеклист ревьюера:**

1. Код делает то, что описано в PR description?
2. Нет секретов / credentials в коде?
3. SQL через ORM, нет raw SQL без параметров?
4. Все endpoints имеют RBAC / auth проверку?
5. Ошибки обработаны, не глотаются молча?
6. Миграция обратима (downgrade)?

---

## Шаг 15 — Merge Strategy

```
# Из stage/* → develop:
git checkout develop
git merge --no-ff stage/1-auth    # merge commit для читаемости
# Каждый этап мержится отдельным PR, конфликты решаются ДО merge

# develop → main:
git checkout main
git merge --no-ff develop         # только через release PR
git tag -a v4.1.0 -m "Release 4.1.0: Auth + Device Registry"
git push origin main --tags
```

**Порядок merge 10 потоков в develop:**

```
Волна 1 (без конфликтов — все параллельные):
  stage/1-auth       → develop  (backend: api/v1/auth/, services/auth_*)
  stage/2-device     → develop  (backend: api/v1/devices/, services/device_*)
  stage/3-websocket  → develop  (backend: api/ws/, websocket/)
  stage/4-scripts    → develop  (backend: api/v1/scripts/, services/script_*)
  stage/5-streaming  → develop  (android: encoder/, frontend: lib/streaming/)
  stage/6-vpn        → develop  (backend: api/v1/vpn/, services/vpn_*)
  stage/7-android    → develop  (android: commands/, lua/, ota/)
  stage/8-pc-agent   → develop  (pc-agent/)
  stage/9-n8n        → develop  (n8n-nodes/)
  stage/11-monitoring → develop (infrastructure/monitoring/)

Волна 2 (зависит от всех backend-стадий):
  stage/10-frontend  → develop  (frontend/ — подключить реальные API)
```

---

## Шаг 16 — Архитектура Изоляции: Worktree + Автодискавери + Rulesets

> **Это главный шаг для работы одним IDE с несколькими разработчиками/агентами без конфликтов.**
> Выполняется DevOps ОДИН РАЗ. После этого каждый агент независим.

---

### 16.1 — Замороженный `backend/main.py` (НИКОГДА не редактировать)

`main.py` создаётся в TZ-00 и **ЗАМОРОЖЕН НАВСЕГДА**. Он **автоматически подключает** все роутеры из `backend/api/v1/*/router.py` — каждый этап просто создаёт свой файл, и он подхватывается без изменения `main.py`.

```python
# backend/main.py — СОЗДАЁТСЯ В TZ-00, РЕДАКТИРОВАТЬ ЗАПРЕЩЕНО ВСЕМ ЭТАПАМ
# Каждый новый этап создаёт ТОЛЬКО backend/api/v1/<NAME>/router.py — он подключится автоматически
import importlib
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from backend.core.cors import setup_cors
from backend.database.redis_client import connect_redis, disconnect_redis


# CRIT-3: lifespan_registry — решает проблему frozen main.py.
# Каждый модуль регистрирует свои startup/shutdown хуки самостоятельно.
# main.py не меняется при добавлении новых сервисов.

# backend/core/lifespan_registry.py
from typing import Callable, Awaitable
import structlog

logger = structlog.get_logger()
_startup_hooks: list[tuple[str, Callable[[], Awaitable[None]]]] = []
_shutdown_hooks: list[tuple[str, Callable[[], Awaitable[None]]]] = []

def register_startup(name: str, coro: Callable[[], Awaitable[None]]) -> None:
    """Зарегистрировать корутину для выполнения при старте FastAPI."""
    _startup_hooks.append((name, coro))

def register_shutdown(name: str, coro: Callable[[], Awaitable[None]]) -> None:
    """Зарегистрировать корутину для выполнения при остановке FastAPI."""
    _shutdown_hooks.append((name, coro))

async def run_all_startup() -> None:
    for name, coro in _startup_hooks:
        logger.info("startup", hook=name)
        await coro()

async def run_all_shutdown() -> None:
    for name, coro in reversed(_shutdown_hooks):  # shutdown в обратном порядке
        logger.info("shutdown", hook=name)
        await coro()


# backend/database/redis_client.py — регистрируем свои хуки в конце файла:
# from backend.core.lifespan_registry import register_startup, register_shutdown
# register_startup("redis", connect_redis)
# register_shutdown("redis", disconnect_redis)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    CRIT-3: main.py не знает о конкретных сервисах — только запускает реестр.
    Новые startup/shutdown хуки регистрируются в самих модулях через register_startup().
    """
    # PROC-4: экспорт OpenAPI schema для TZ-10 (frontend типы через openapi-typescript)
    import json
    from pathlib import Path
    Path("openapi.json").write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False))

    from backend.core.lifespan_registry import run_all_startup, run_all_shutdown
    await run_all_startup()

    yield   # приложение работает

    await run_all_shutdown()


app = FastAPI(
    title="Sphere Platform API",
    version="4.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,             # FastAPI ≥ 0.93: рекомендуемый способ startup/shutdown
)

setup_cors(app)

# ── Авто-дискавери роутеров ──────────────────────────────────────────────────
# Подключает backend/api/v1/<subdir>/router.py для каждой поддиректории.
# ВАЖНО: каждый новый этап создаёт backend/api/v1/<NAME>/router.py — НЕ файл android.py!
# Структура: backend/api/v1/auth/router.py, backend/api/ws/android/router.py и т.д.
# Порядок: алфавитный (auth < devices < scripts < ...).
_v1_path = Path(__file__).parent / "api" / "v1"
if _v1_path.exists():
    for _sub in sorted(_v1_path.iterdir()):
        if _sub.is_dir() and (_sub / "router.py").exists():
            _mod = importlib.import_module(f"backend.api.v1.{_sub.name}.router")
            if hasattr(_mod, "router"):
                app.include_router(_mod.router, prefix="/api/v1")

# ── WebSocket роутеры ────────────────────────────────────────────────────────
# Подключает backend/api/ws/<subdir>/router.py (stage/3-websocket)
# КАЖДЫЙ WS-модуль ОБЯЗАН быть папкой с router.py:
#   backend/api/ws/android/router.py
#   backend/api/ws/agent/router.py
# НЕ backend/api/ws/android.py — авто-дискавери не найдёт файл!
_ws_path = Path(__file__).parent / "api" / "ws"
if _ws_path.exists():
    for _sub in sorted(_ws_path.iterdir()):
        if _sub.is_dir() and (_sub / "router.py").exists():
            _mod = importlib.import_module(f"backend.api.ws.{_sub.name}.router")
            if hasattr(_mod, "router"):
                app.include_router(_mod.router)


@app.get("/api/v1/health", tags=["health"])
async def health_check():
    return {"status": "ok", "version": "4.0.0"}
```

**Правило для всех SPLIT-файлов:** Нигде в ТЗ-1..11 не должно быть инструкций `import` или `app.include_router` в `main.py`. Только создать свой `router.py`.

---

### 16.2 — Файловое владение по этапам (кто что трогает)

> Конфликты при merge = когда два этапа редактируют один файл. Эта таблица это запрещает.

| Этап | Папки/файлы этапа ✅ | Запрещено трогать 🔴 |
|---|---|---|
| **TZ-00** (Constitution) | `backend/main.py`, `backend/core/`, `backend/database/`, `backend/models/` (ВСЕ!), `docker-compose*.yml`, `Makefile`, `.github/` | — (создаёт всё) |
| **TZ-01** (Auth) | `backend/api/v1/auth/`, `backend/services/auth_*`, `backend/schemas/auth*`, `backend/models/refresh_token.py`, `backend/core/security.py`, `backend/core/dependencies.py`, `backend/core/exceptions.py` | `main.py`, `backend/core/config.py` 🔴, `backend/core/cors.py` 🔴, `backend/models/user.py` (TZ-00) |
| **TZ-02** (Devices) | `backend/api/v1/devices/`, `backend/api/v1/groups/`, `backend/api/v1/bulk/`, `backend/api/v1/discovery/`, `backend/services/device_*`, `pc-agent/modules/adb_*` | `main.py`, `core/`, `auth/`, `backend/models/` |
| **TZ-03** (WebSocket) | `backend/api/ws/`, `backend/websocket/`, `backend/api/v1/ws/` | `main.py`, `core/`, `devices/`, `backend/models/` |
| **TZ-04** (Scripts) | `backend/api/v1/scripts/`, `backend/api/v1/tasks/`, `backend/api/v1/batches/`, `backend/services/script_*`, `backend/services/task_*`, `backend/services/batch_*`, `backend/schemas/dag*` | `main.py`, `core/`, `devices/`, `backend/models/` (TZ-00!) |
| **TZ-05** (Streaming) | `android/app/src/main/kotlin/.../encoder/`, `backend/api/v1/streaming/`, `backend/services/streaming_*` | `main.py`, `core/`, `ws/`, `backend/models/` |
| **TZ-06** (VPN) | `backend/api/v1/vpn/`, `backend/services/vpn_*`, `backend/schemas/vpn*`, `android/.../vpn/` | `main.py`, `core/`, `streaming/`, `backend/models/` (TZ-00!) |
| **TZ-07** (Android Agent) | `android/app/src/main/kotlin/.../{commands,lua,ota,updates}/` | `main.py`, `core/`, encoder (TZ-05), `backend/models/` |
| **TZ-08** (PC Agent) | `pc-agent/` (всё кроме `adb_discovery.py` — он в TZ-02) | `main.py`, `core/`, `backend/` |
| **TZ-09** (n8n) | `n8n-nodes/`, `backend/api/v1/n8n/`, `backend/services/n8n_*` | `main.py`, `core/`, `backend/models/` |
| **TZ-10** (Frontend) | `frontend/` (всё) | `main.py`, `backend/` (только читать API docs) |
| **TZ-11** (Monitoring) | `infrastructure/monitoring/`, `backend/monitoring/`, `backend/middleware/prometheus*` | `main.py`, `core/`, `frontend/`, `backend/models/` |

---

### 16.3 — Создание изолированных рабочих сред (выполнить один раз)

```bash
# 1. Создать все stage-ветки (от develop)
make branches

# 2. Создать изолированные папки-worktrees
make worktree-setup

# 3. Убедиться что всё создано:
git worktree list
# Вывод:
# C:/Users/dimas/Documents/sphere-platform     abc1234 [develop]
# C:/Users/dimas/Documents/sphere-stage-1      def5678 [stage/1-auth]
# C:/Users/dimas/Documents/sphere-stage-2      ...
# ...
```

---

### 16.4 — Инструкция для разработчика/агента (передаётся перед началом работы)

Скопируй этот текст и используй в начале каждого этапа:

```
Ты исполнитель этапа TZ-NN.
Рабочая папка: C:\Users\dimas\Documents\sphere-stage-N
Открой ИМЕННО ЭТУ папку в IDE. НЕ sphere-platform.

Правила:
1. Выполни git branch --show-current → должно быть stage/N-name
2. Работай ТОЛЬКО в своих папках (см. таблицу владения в Шаг 0 ТЗ)
3. backend/main.py — НИКОГДА НЕ ТРОГАТЬ. Просто создай свой router.py — он подключится автоматически
4. backend/core/ — НИКОГДА НЕ ТРОГАТЬ
5. git checkout — ЗАПРЕЩЕНО
6. git merge / git rebase — ЗАПРЕЩЕНО
7. git push --force — ЗАПРЕЩЕНО
8. Разрешено: git add, git commit, git push origin stage/N-name, открыть PR

ТЗ для этого этапа лежит в папке TZ-NN-Name/ (рядом с sphere-platform).
```

---

### 16.5 — GitHub Rulesets (сервер-сайд защита, после создания веток)

```bash
# Установить переменную с именем вашей GitHub-организации/пользователя
export GITHUB_OWNER=$(gh repo view --json owner -q .owner.login)

gh auth login

# Защита main (2 ревью, полный CI)
gh api repos/$GITHUB_OWNER/sphere-platform/rulesets --method POST \
  --field name="protect-main" --field target="branch" --field enforcement="active" \
  --field 'conditions={"ref_name":{"include":["~DEFAULT_BRANCH"],"exclude":[]}}' \
  --field 'rules=[{"type":"deletion"},{"type":"non_fast_forward"},{"type":"required_linear_history"},{"type":"pull_request","parameters":{"required_approving_review_count":2,"dismiss_stale_reviews_on_push":true}}]'

# Защита develop (1 ревью)
gh api repos/$GITHUB_OWNER/sphere-platform/rulesets --method POST \
  --field name="protect-develop" --field target="branch" --field enforcement="active" \
  --field 'conditions={"ref_name":{"include":["refs/heads/develop"],"exclude":[]}}' \
  --field 'rules=[{"type":"deletion"},{"type":"non_fast_forward"},{"type":"pull_request","parameters":{"required_approving_review_count":1,"dismiss_stale_reviews_on_push":true}}]'

# Запрет force-push в stage/* (разработчики не могут испортить историю)
gh api repos/$GITHUB_OWNER/sphere-platform/rulesets --method POST \
  --field name="isolate-stage-branches" --field target="branch" --field enforcement="active" \
  --field 'conditions={"ref_name":{"include":["refs/heads/stage/**"],"exclude":[]}}' \
  --field 'rules=[{"type":"deletion"},{"type":"non_fast_forward"}]'
```

---

### 16.6 — Порядок merge при финальной интеграции (без говна)

```
Волна 1 — независимые параллельные (порядок между ними неважен):
  stage/1-auth         → PR → develop  ✅ нет зависимостей
  stage/2-device-registry → PR → develop  ✅ нет зависимостей
  stage/3-websocket    → PR → develop  ✅ нет зависимостей
  stage/4-scripts      → PR → develop  ✅ нет зависимостей
  stage/5-streaming    → PR → develop  ✅ нет зависимостей
  stage/6-vpn          → PR → develop  ✅ нет зависимостей
  stage/7-android      → PR → develop  ✅ нет зависимостей
  stage/8-pc-agent     → PR → develop  ✅ нет зависимостей
  stage/9-n8n          → PR → develop  ✅ нет зависимостей
  stage/11-monitoring  → PR → develop  ✅ нет зависимостей

Волна 2 — зависит от всего backend:
  stage/10-frontend    → PR → develop  ⏳ ТОЛЬКО после merge Волны 1

Благодаря авто-дискавери main.py: НУЛЕВЫХ конфликтов в main.py при всех PR.
Каждый этап трогает ТОЛЬКО свои файлы → конфликты при merge НЕВОЗМОЖНЫ.
---

## Критерии готовности (Definition of Done)

- [ ] `git clone` → `make setup` → работает без ошибок
- [ ] `make dev` → PG, Redis, n8n запущены, healthchecks OK
- [ ] `make branches` → все 11 stage-веток созданы и запушены
- [ ] `make worktree-setup` → все 11 папок `sphere-stage-N` созданы рядом с `sphere-platform`
- [ ] `git worktree list` показывает 12 рабочих деревьев (sphere-platform + 11 stage)
- [ ] `backend/main.py` создан с авто-дискавери роутеров (Шаг 16.1) — больше НЕ ТРОГАТЬ
- [ ] GitHub Rulesets созданы (Шаг 16.5): protect-main, protect-develop, isolate-stage-branches
- [ ] `git push` с .env файлом — отклоняется pre-commit
- [ ] `git push` с приватным ключом в коде — отклоняется detect-secrets
- [ ] CI (GitHub Actions) запускается на PR → tests + lint проходят
- [ ] `.github/CODEOWNERS` покрывает все ключевые директории
- [ ] PR template используется при создании PR (содержит security checklist)
- [ ] Issue templates для bug report и feature request настроены
- [ ] Conventional Commits проверяются в pre-commit (commitlint)
- [ ] Merge strategy задокументирована: `stage/*` → `develop` → `main`
- [ ] Таблица владения файлами (Шаг 16.2) донесена до всех агентов/разработчиков
- [ ] Semantic versioning: VERSION файл = v4.0.0, tag при release
