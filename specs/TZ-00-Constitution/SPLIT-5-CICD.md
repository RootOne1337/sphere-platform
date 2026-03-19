# SPLIT-5 — CI/CD Pipeline (GitHub Actions)

**ТЗ-родитель:** TZ-00-Constitution  
**Ветка:** `stage/0-constitution`  
**Задача:** `SPHERE-005`  
**Исполнитель:** DevOps  
**Оценка:** 0.5 рабочего дня  
**Блокирует:** — (последний SPLIT в TZ-00)
**Обеспечивает:** CI/CD pipeline для качества кода во всех ветках

---

## Цель Сплита

Настроить GitHub Actions CI для автоматических проверок на каждый PR. После выполнения — ни один PR нельзя смержить без прохождения тестов, линтинга и security проверок.

---

## Шаг 1 — CI workflow (backend)

```yaml
# .github/workflows/ci-backend.yml
name: CI — Backend

on:
  push:
    branches: [main, develop, "stage/*"]
  pull_request:
    branches: [main, develop]

jobs:
  lint:
    name: Lint (ruff + mypy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install ruff mypy
      - run: ruff check backend/ tests/
      - run: mypy backend/ --ignore-missing-imports

  security:
    name: Security (bandit + pip-audit)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install bandit pip-audit
      - run: bandit -r backend/ -c .bandit -ll
      - run: pip-audit -r backend/requirements.txt

  test:
    name: Tests
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_DB: sphereplatform_test
          POSTGRES_USER: sphere
          POSTGRES_PASSWORD: test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
      redis:
        image: redis:7.2-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
        ports:
          - 6379:6379
    env:
      POSTGRES_URL: postgresql+asyncpg://sphere:test_password@localhost:5432/sphereplatform_test
      REDIS_URL: redis://localhost:6379/0
      REDIS_PASSWORD: ""
      JWT_SECRET_KEY: test_jwt_secret_key_at_least_32_chars
      WG_ROUTER_URL: http://mock-wg-router
      WG_ROUTER_API_KEY: test_key
      AWG_H1: 1111111111
      AWG_H2: 2222222222
      AWG_H3: 3333333333
      AWG_H4: 4444444444
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r backend/requirements.txt
      - run: alembic upgrade head
        working-directory: backend
      - run: pytest tests/ -v --cov=backend --cov-report=xml --cov-fail-under=80
      - uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
```

---

## Шаг 2 — Android APK CI

```yaml
# .github/workflows/ci-android.yml
name: CI — Android

on:
  push:
    paths: ["android/**"]
  pull_request:
    branches: [main]
    paths: ["android/**"]

jobs:
  build:
    name: Build APK
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          java-version: "17"
          distribution: temurin
      - uses: gradle/actions/setup-gradle@v3
      
      - name: Build debug APK
        working-directory: android
        run: ./gradlew assembleDebug
      
      - name: Run unit tests
        working-directory: android
        run: ./gradlew test
      
      - name: Upload APK artifact
        uses: actions/upload-artifact@v4
        with:
          name: debug-apk
          path: android/app/build/outputs/apk/debug/*.apk
```

---

## Шаг 3 — Deploy workflow (staging)

```yaml
# .github/workflows/deploy-staging.yml
name: Deploy — Staging

on:
  push:
    branches: [develop]

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      
      - name: Build Docker images
        run: docker compose -f docker-compose.production.yml build
      
      - name: Push to registry
        run: |
          echo ${{ secrets.REGISTRY_PASSWORD }} | docker login ghcr.io -u ${{ github.actor }} --password-stdin
          docker push ghcr.io/${{ github.repository_owner }}/sphere-platform-backend:staging
      
      - name: Deploy to staging server
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.STAGING_HOST }}
          username: deploy
          key: ${{ secrets.STAGING_SSH_KEY }}
          script: |
            cd /srv/sphere-platform
            docker compose pull
            docker compose up -d --no-deps backend
            docker compose exec backend alembic upgrade head
```

---

## Шаг 4 — .bandit конфигурация

```yaml
# .bandit
skips:
  - B101  # assert_used (OK в тестах)
  - B601  # paramiko_calls (не используем)
exclude_dirs:
  - tests/
  - alembic/
```

---

## Шаг 4.1 — CI: RLS Policy Lint

> Любая модель с полем `org_id` **обязана** иметь RLS policy в `infrastructure/postgres/rls_policies.sql`.
> Скрипт запускается в CI и блокирует PR без RLS.

```python
# scripts/check_rls.py — автоматическая проверка RLS покрытия
"""
Парсит все SQLAlchemy модели в backend/models/.
Находит таблицы с полем org_id.
Проверяет, что каждая такая таблица упомянута в rls_policies.sql.
Выход: 0 (все покрыты) или 1 (есть пробелы).
"""
import re
import sys
from pathlib import Path

MODELS_DIR = Path("backend/models")
RLS_FILE = Path("infrastructure/postgres/rls_policies.sql")

def find_tables_with_org_id() -> set[str]:
    """Найти все __tablename__ в моделях с org_id."""
    tables = set()
    for py_file in MODELS_DIR.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        # Пропустить __init__.py и base_model.py
        if py_file.name in ("__init__.py", "base_model.py"):
            continue
        # Есть ли org_id?
        if "org_id" not in content:
            continue
        # Извлечь __tablename__
        match = re.search(r'__tablename__\s*=\s*"(\w+)"', content)
        if match:
            tables.add(match.group(1))
    return tables

def find_tables_with_rls() -> set[str]:
    """Извлечь таблицы с ENABLE ROW LEVEL SECURITY из rls_policies.sql."""
    if not RLS_FILE.exists():
        print(f"⚠️  {RLS_FILE} не найден — RLS не настроен!")
        return set()
    content = RLS_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY", content))

def main():
    org_tables = find_tables_with_org_id()
    rls_tables = find_tables_with_rls()
    missing = org_tables - rls_tables

    print(f"Таблицы с org_id:   {len(org_tables)} — {sorted(org_tables)}")
    print(f"Таблицы с RLS:      {len(rls_tables)} — {sorted(rls_tables)}")

    if missing:
        print(f"\n🔴 ОШИБКА: {len(missing)} таблиц(ы) с org_id без RLS policy:")
        for t in sorted(missing):
            print(f"   ✗ {t}")
        print("\nДобавь RLS policy в infrastructure/postgres/rls_policies.sql:")
        for t in sorted(missing):
            print(f"   ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
            print(f"   CREATE POLICY {t}_tenant ON {t} USING (org_id = current_setting('app.current_org_id')::uuid);")
        sys.exit(1)
    else:
        print(f"\n✅ Все {len(org_tables)} таблиц с org_id имеют RLS policy")
        sys.exit(0)

if __name__ == "__main__":
    main()
```

**Интеграция в CI (ci-backend.yml) — добавить job:**

```yaml
  rls-check:
    name: RLS Policy Coverage
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python scripts/check_rls.py

  alembic-check:
    name: Alembic Single Head
    runs-on: ubuntu-latest
    needs: [test]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r backend/requirements.txt
      - run: make alembic-check
```

---

## Шаг 4.2 — Merge Guard Workflow

> Блокирует merge stage-ветки в develop если зависимые ТЗ ещё не смержены.
> **Матрица зависимостей:**
>
> - TZ-00 (Wave 0): нет зависимостей
> - TZ-01..09, TZ-11 (Wave 1): зависят от TZ-00
> - TZ-10 (Wave 2): зависит от ВСЕХ backend ТЗ (TZ-01..06, TZ-09)

```yaml
# .github/workflows/merge-guard.yml
name: Merge Guard — Stage Branch Dependencies

on:
  pull_request:
    branches: [develop]

jobs:
  check-dependencies:
    name: Проверка зависимостей ТЗ
    runs-on: ubuntu-latest
    if: startsWith(github.head_ref, 'stage/')

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Проверить merge order
        run: |
          set -euo pipefail
          BRANCH="${{ github.head_ref }}"
          echo "Проверяем merge-order для: ${BRANCH}"

          # Функция: проверка что ветка уже смержена в develop
          check_merged() {
            local branch="$1"
            # Если ветки нет в remote — значит уже смержена и удалена
            if ! git ls-remote --heads origin "${branch}" | grep -q "${branch}"; then
              echo "  ✅ ${branch} — смержена (ветка удалена)"
              return 0
            fi
            # Если ветка есть и полностью содержится в develop
            if git merge-base --is-ancestor "origin/${branch}" origin/develop 2>/dev/null; then
              echo "  ✅ ${branch} — смержена"
              return 0
            fi
            echo "  ❌ ${branch} — НЕ смержена в develop"
            return 1
          }

          ERRORS=0

          # Все ветки Wave 1+ зависят от TZ-00
          if [[ "${BRANCH}" != "stage/0-constitution" ]]; then
            echo "Проверяем TZ-00 (Wave 0 зависимость)..."
            check_merged "stage/0-constitution" || ERRORS=$((ERRORS + 1))
          fi

          # TZ-10 (frontend) зависит от всех backend ТЗ
          if [[ "${BRANCH}" == "stage/10-frontend" ]]; then
            echo "Проверяем backend ТЗ (Wave 1 зависимости для TZ-10)..."
            for dep in stage/1-auth stage/2-device-registry stage/3-websocket \
                       stage/4-scripts stage/5-streaming stage/6-vpn stage/9-n8n; do
              check_merged "${dep}" || ERRORS=$((ERRORS + 1))
            done
          fi

          if [ "${ERRORS}" -gt 0 ]; then
            echo ""
            echo "🔴 Merge заблокирован: ${ERRORS} зависимость(ей) не выполнена."
            echo "   Сначала смержи зависимые ТЗ в develop."
            exit 1
          fi

          echo ""
          echo "✅ Все зависимости выполнены. Merge разрешён."
```

---

## Шаг 5 — Preview Environments (эфемерные окружения)

> **Opt-in функция.** Все три workflow завершаются немедленно (`if: needs.guard.outputs.enabled == 'true'`), пока переменная явно не активирована.
> **Включить:** GitHub → Settings → Variables → `PREVIEW_ENVIRONMENTS_ENABLED = true`
> **Не использовать:** просто не создавать переменную — нулевое влияние на всё остальное.

### Архитектура

```
PR открыт / обновлён
       │
       ▼
preview-deploy.yml
  ├── guard: PREVIEW_ENVIRONMENTS_ENABLED == 'true'? (иначе exit 0)
  ├── server: проверка слотов (≤ 5 одновременных окружений)
  ├── build backend:pr-N  → ghcr.io
  ├── build frontend:pr-N → ghcr.io
  ├── ssh → /srv/sphere-previews/pr-N/
  │        ├── docker compose up (postgres + redis + backend + frontend)
  │        └── alembic upgrade head
  ├── poll /api/v1/health/ready (до 5 мин)
  ├── GitHub Deployment API → "success"
  └── PR comment: https://pr-N.preview.sphere.example.com

PR закрыт / смержен
       │
       ▼
preview-teardown.yml
  ├── docker compose down -v --remove-orphans
  ├── rm -rf /srv/sphere-previews/pr-N
  └── GitHub Deployment API → "inactive"

Каждые 6 ч (cron)
       │
       ▼
preview-cleanup.yml
  └── удалить все pr-N старше 24 ч
```

**Ключевые свойства:**

- Изолировано в `/srv/sphere-previews/pr-N/` — не касается `/srv/sphere-platform/`
- [Traefik](https://traefik.io) динамически маршрутизирует по Docker-labels — без перезагрузок конфига
- Wildcard TLS `*.preview.sphere.example.com` через Let's Encrypt DNS-challenge (один сертификат на все PR)
- Лимит: не более 5 одновременных окружений (server-side guard перед деплоем)
- Каждое окружение: свой PostgreSQL-volume (чистая БД + миграции), свой Redis, ограниченные CPU/RAM

---

### 5.1 One-time: Traefik на сервере

> Запускается **один раз** на VPS. После этого не трогается — новые preview-контейнеры обнаруживаются автоматически через Docker socket.

```yaml
# infrastructure/traefik/docker-compose.traefik.yml
name: traefik-proxy

services:
  traefik:
    image: traefik:v3.2
    container_name: traefik
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "127.0.0.1:8080:8080"   # dashboard (только localhost)
    environment:
      CF_DNS_API_TOKEN: ${CF_DNS_API_TOKEN}   # wildcard TLS via Cloudflare DNS
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik-data:/traefik
      - ./traefik.yml:/traefik/traefik.yml:ro
    networks:
      - traefik-net
    healthcheck:
      test: ["CMD", "traefik", "healthcheck", "--ping"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  traefik-net:
    name: traefik-net

volumes:
  traefik-data:
    name: traefik-data
```

```yaml
# infrastructure/traefik/traefik.yml  (статичная конфигурация)
api:
  dashboard: true
  insecure: false

ping: {}

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
  websecure:
    address: ":443"

certificatesResolvers:
  letsencrypt:
    acme:
      email: ${ACME_EMAIL}
      storage: /traefik/acme.json
      dnsChallenge:
        provider: cloudflare       # заменить на: digitalocean / route53 / etc.
        delayBeforeCheck: 10
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"

providers:
  docker:
    exposedByDefault: false
    network: traefik-net
    watch: true

log:
  level: INFO

metrics:
  prometheus:
    addEntryPointsLabels: true
    addServicesLabels: true
```

```
# DNS-запись у провайдера (Cloudflare / etc.)
Тип:    A
Имя:    *.preview.sphere.example.com
Значение: <IP VPS>
TTL:    300
```

---

### 5.2 `docker-compose.preview.yml`

```yaml
# docker-compose.preview.yml   (корень репозитория)
# ИЗОЛИРОВАНО: не касается docker-compose.yml / docker-compose.production.yml
# Обязательные env: PR_NUMBER, PREVIEW_DB_PASSWORD, PREVIEW_JWT_SECRET, PREVIEW_DOMAIN

name: preview-${PR_NUMBER}

services:

  postgres:
    image: postgres:15-alpine
    container_name: preview-${PR_NUMBER}-postgres
    environment:
      POSTGRES_DB:       sphere_preview
      POSTGRES_USER:     sphere
      POSTGRES_PASSWORD: ${PREVIEW_DB_PASSWORD}
    volumes:
      - preview-${PR_NUMBER}-pgdata:/var/lib/postgresql/data
    networks:
      - preview-${PR_NUMBER}-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sphere -d sphere_preview"]
      interval: 5s
      timeout: 5s
      retries: 12
    restart: "no"
    deploy:
      resources:
        limits:
          cpus: "0.50"
          memory: 768M  # Alembic + миграции 35+ таблиц — 512M может не хватить

  redis:
    image: redis:7.2-alpine
    container_name: preview-${PR_NUMBER}-redis
    networks:
      - preview-${PR_NUMBER}-net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 6
    restart: "no"
    deploy:
      resources:
        limits:
          cpus: "0.25"
          memory: 128M

  backend:
    image: ghcr.io/${GITHUB_OWNER}/sphere-platform-backend:pr-${PR_NUMBER}
    container_name: preview-${PR_NUMBER}-backend
    environment:
      DATABASE_URL:    postgresql+asyncpg://sphere:${PREVIEW_DB_PASSWORD}@postgres:5432/sphere_preview
      REDIS_URL:       redis://redis:6379/0
      REDIS_PASSWORD:  ""
      JWT_SECRET_KEY:  ${PREVIEW_JWT_SECRET}
      ENV:             preview
      ALLOWED_ORIGINS: "https://pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - preview-${PR_NUMBER}-net
      - traefik-net
    labels:
      traefik.enable: "true"
      traefik.docker.network: "traefik-net"
      traefik.http.routers.prev-${PR_NUMBER}-api.rule: >
        Host(`pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}`) && PathPrefix(`/api`)
      traefik.http.routers.prev-${PR_NUMBER}-api.entrypoints: "websecure"
      traefik.http.routers.prev-${PR_NUMBER}-api.tls.certresolver: "letsencrypt"
      traefik.http.services.prev-${PR_NUMBER}-api.loadbalancer.server.port: "8000"
    restart: "no"
    deploy:
      resources:
        limits:
          cpus: "1.00"
          memory: 1G    # FastAPI достаточно 1 GB

  frontend:
    image: ghcr.io/${GITHUB_OWNER}/sphere-platform-frontend:pr-${PR_NUMBER}
    container_name: preview-${PR_NUMBER}-frontend
    environment:
      NEXT_PUBLIC_API_URL: "https://pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}/api"
      NEXT_PUBLIC_WS_URL:  "wss://pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}/api/v1/ws"
      # Node.js heap limit явно ниже лимита контейнера — предотвращает OOM Kill
      NODE_OPTIONS: "--max-old-space-size=1280"
    networks:
      - preview-${PR_NUMBER}-net
      - traefik-net
    labels:
      traefik.enable: "true"
      traefik.docker.network: "traefik-net"
      traefik.http.routers.prev-${PR_NUMBER}-fe.rule: >
        Host(`pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}`)
      traefik.http.routers.prev-${PR_NUMBER}-fe.entrypoints: "websecure"
      traefik.http.routers.prev-${PR_NUMBER}-fe.tls.certresolver: "letsencrypt"
      traefik.http.services.prev-${PR_NUMBER}-fe.loadbalancer.server.port: "3000"
    restart: "no"
    deploy:
      resources:
        limits:
          cpus: "1.00"
          memory: 1.5G  # Next.js App Router + 28 стр. легко занимает 600MB–1.2GB при startup

  # ── n8n (FIX: без n8n preview-окружения не тестируют webhook-логику TZ-09) ─────
  n8n:
    image: n8nio/n8n:1.70.2
    container_name: preview-${PR_NUMBER}-n8n
    environment:
      DB_TYPE:                 postgresdb
      DB_POSTGRESDB_HOST:      postgres
      DB_POSTGRESDB_PORT:      5432
      DB_POSTGRESDB_DATABASE:  n8n_preview
      DB_POSTGRESDB_USER:      sphere
      DB_POSTGRESDB_PASSWORD:  ${PREVIEW_DB_PASSWORD}
      N8N_HOST:                pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}
      N8N_PROTOCOL:            https
      WEBHOOK_URL:             https://pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}/n8n/
      N8N_EDITOR_BASE_URL:     https://pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}/n8n/
      N8N_PATH:                /n8n/
      N8N_DIAGNOSTICS_ENABLED: "false"
      N8N_PERSONALIZATION_ENABLED: "false"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - preview-${PR_NUMBER}-net
      - traefik-net
    labels:
      traefik.enable: "true"
      traefik.docker.network: "traefik-net"
      traefik.http.routers.prev-${PR_NUMBER}-n8n.rule: >
        Host(`pr-${PR_NUMBER}.preview.${PREVIEW_DOMAIN}`) && PathPrefix(`/n8n`)
      traefik.http.routers.prev-${PR_NUMBER}-n8n.entrypoints: "websecure"
      traefik.http.routers.prev-${PR_NUMBER}-n8n.tls.certresolver: "letsencrypt"
      traefik.http.services.prev-${PR_NUMBER}-n8n.loadbalancer.server.port: "5678"
    restart: "no"
    deploy:
      resources:
        limits:
          cpus: "0.50"
          memory: 512M

networks:
  preview-${PR_NUMBER}-net:
    name: preview-${PR_NUMBER}-net
  traefik-net:
    name: traefik-net
    external: true

volumes:
  preview-${PR_NUMBER}-pgdata:
    name: preview-${PR_NUMBER}-pgdata
```

---

### 5.3 `.github/workflows/preview-deploy.yml`

```yaml
name: Preview — Deploy

on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches: [main, develop]

# Новый пуш в PR отменяет предыдущий незавершённый деплой того же PR
concurrency:
  group: preview-pr-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  # ─────────────────────────────────────────────────────────────────────────────
  # Guard: мгновенный пропуск если переменная не активирована
  # ─────────────────────────────────────────────────────────────────────────────
  guard:
    runs-on: ubuntu-latest
    outputs:
      enabled: ${{ steps.chk.outputs.enabled }}
    steps:
      - id: chk
        run: echo "enabled=${{ vars.PREVIEW_ENVIRONMENTS_ENABLED }}" >> $GITHUB_OUTPUT

  deploy:
    needs: guard
    if: needs.guard.outputs.enabled == 'true'
    runs-on: ubuntu-latest
    permissions:
      contents:     read
      deployments:  write
      pull-requests: write
      packages:     write
    environment:
      name: preview-pr-${{ github.event.pull_request.number }}
      url: https://pr-${{ github.event.pull_request.number }}.preview.${{ vars.PREVIEW_DOMAIN }}

    steps:
      # ── 1. Checkout ──────────────────────────────────────────────────────────
      - uses: actions/checkout@v4

      # ── 2. Лимит: не более 5 одновременных preview envs ─────────────────────
      - name: Check preview slot availability
        uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.PREVIEW_HOST }}
          username: deploy
          key:      ${{ secrets.PREVIEW_SSH_KEY }}
          script: |
            set -euo pipefail
            PR_NUMBER=${{ github.event.pull_request.number }}
            PR_DIR="/srv/sphere-previews/pr-${PR_NUMBER}"
            TOTAL=$(find /srv/sphere-previews -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)
            # Текущий PR не считается — обновление существующего окружения
            [ -d "${PR_DIR}" ] && TOTAL=$((TOTAL - 1))
            if [ "${TOTAL}" -ge 5 ]; then
              echo "::error::Достигнут лимит 5 одновременных preview-окружений. Закройте или смержите другие PRs."
              exit 1
            fi
            echo "Slots: ${TOTAL}/5 used. OK."

      # ── 3. GitHub Deployments API ─────────────────────────────────────────
      - name: Create GitHub Deployment
        id: create_deployment
        uses: actions/github-script@v7
        with:
          script: |
            const { data } = await github.rest.repos.createDeployment({
              owner:                  context.repo.owner,
              repo:                   context.repo.repo,
              ref:                    context.sha,
              environment:            `preview-pr-${context.payload.pull_request.number}`,
              auto_merge:             false,
              required_contexts:      [],
              description:            `PR #${context.payload.pull_request.number}: ${context.payload.pull_request.title}`,
              transient_environment:  true,
              production_environment: false,
            });
            core.setOutput('id', data.id);

      - name: Deployment status → in_progress
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.repos.createDeploymentStatus({
              owner:         context.repo.owner,
              repo:          context.repo.repo,
              deployment_id: ${{ steps.create_deployment.outputs.id }},
              state:         'in_progress',
              description:   'Building Docker images…',
            });

      # ── 4. Docker Buildx: build & push образов ───────────────────────────
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/setup-buildx-action@v3

      - name: Build & push backend
        uses: docker/build-push-action@v6
        with:
          context:    backend
          push:       true
          tags:       ghcr.io/${{ github.repository_owner }}/sphere-platform-backend:pr-${{ github.event.pull_request.number }}
          cache-from: type=registry,ref=ghcr.io/${{ github.repository_owner }}/sphere-platform-backend:buildcache
          cache-to:   type=registry,ref=ghcr.io/${{ github.repository_owner }}/sphere-platform-backend:buildcache,mode=max
          build-args: BUILD_SHA=${{ github.sha }}

      - name: Build & push frontend
        uses: docker/build-push-action@v6
        with:
          context:    frontend
          push:       true
          tags:       ghcr.io/${{ github.repository_owner }}/sphere-platform-frontend:pr-${{ github.event.pull_request.number }}
          cache-from: type=registry,ref=ghcr.io/${{ github.repository_owner }}/sphere-platform-frontend:buildcache
          cache-to:   type=registry,ref=ghcr.io/${{ github.repository_owner }}/sphere-platform-frontend:buildcache,mode=max

      # ── 5. Деплой на сервер ──────────────────────────────────────────────
      - name: Deploy preview environment
        uses: appleboy/ssh-action@v1
        env:
          PR_NUMBER:           ${{ github.event.pull_request.number }}
          PREVIEW_DB_PASSWORD: ${{ secrets.PREVIEW_DB_PASSWORD }}
          PREVIEW_JWT_SECRET:  ${{ secrets.PREVIEW_JWT_SECRET }}
          PREVIEW_DOMAIN:      ${{ vars.PREVIEW_DOMAIN }}
        with:
          host:     ${{ secrets.PREVIEW_HOST }}
          username: deploy
          key:      ${{ secrets.PREVIEW_SSH_KEY }}
          envs:     PR_NUMBER,PREVIEW_DB_PASSWORD,PREVIEW_JWT_SECRET,PREVIEW_DOMAIN
          script: |
            set -euo pipefail
            DEPLOY_DIR="/srv/sphere-previews/pr-${PR_NUMBER}"
            mkdir -p "${DEPLOY_DIR}"

            # Актуальный compose файл из репозитория
            cp /srv/sphere-platform/docker-compose.preview.yml "${DEPLOY_DIR}/"

            # .env с данными этого конкретного PR
            cat > "${DEPLOY_DIR}/.env" <<EOF
            PR_NUMBER=${PR_NUMBER}
            PREVIEW_DB_PASSWORD=${PREVIEW_DB_PASSWORD}
            PREVIEW_JWT_SECRET=${PREVIEW_JWT_SECRET}
            PREVIEW_DOMAIN=${PREVIEW_DOMAIN}
            EOF
            chmod 600 "${DEPLOY_DIR}/.env"

            # Pull-авторизация в GHCR
            echo "$GHCR_PULL_TOKEN" | docker login ghcr.io -u pullbot --password-stdin 2>/dev/null || true

            cd "${DEPLOY_DIR}"
            docker compose -f docker-compose.preview.yml pull --quiet
            docker compose -f docker-compose.preview.yml up -d --remove-orphans

            # Ждём готовности postgres, затем прогоняем миграции
            docker compose -f docker-compose.preview.yml exec -T backend \
              bash -c "until pg_isready -h postgres -U sphere 2>/dev/null; do sleep 2; done; alembic upgrade head"

            echo "✅ Preview pr-${PR_NUMBER} deployed"
        env:
          GHCR_PULL_TOKEN: ${{ secrets.GHCR_PULL_TOKEN }}

      # ── 6. Health check polling (до 5 мин) ───────────────────────────────
      - name: Wait for /api/v1/health/ready
        run: |
          URL="https://pr-${{ github.event.pull_request.number }}.preview.${{ vars.PREVIEW_DOMAIN }}/api/v1/health/ready"
          echo "Polling: ${URL}"
          for i in $(seq 1 30); do
            HTTP=$(curl -sk -o /dev/null -w "%{http_code}" "${URL}" || echo "000")
            echo "[${i}/30] HTTP ${HTTP}"
            [ "${HTTP}" = "200" ] && { echo "✅ Preview healthy!"; exit 0; }
            sleep 10
          done
          echo "❌ Preview не прошёл health check за 5 минут"
          exit 1

      # ── 7. GitHub Deployment: финальный статус ────────────────────────────
      - name: Deployment status → success
        if: success()
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.repos.createDeploymentStatus({
              owner:           context.repo.owner,
              repo:            context.repo.repo,
              deployment_id:   ${{ steps.create_deployment.outputs.id }},
              state:           'success',
              environment_url: `https://pr-${{ github.event.pull_request.number }}.preview.${{ vars.PREVIEW_DOMAIN }}`,
              description:     'Preview environment is live!',
            });

      - name: Deployment status → failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.repos.createDeploymentStatus({
              owner:         context.repo.owner,
              repo:          context.repo.repo,
              deployment_id: ${{ steps.create_deployment.outputs.id }},
              state:         'failure',
              description:   'Deployment failed — check workflow logs.',
            });

      # ── 8. PR comment с URL (создать или обновить) ────────────────────────
      - name: Post / update PR comment
        if: success()
        uses: actions/github-script@v7
        with:
          script: |
            const MARKER  = '<!-- sphere-preview-env -->';
            const prNum   = context.payload.pull_request.number;
            const baseUrl = `https://pr-${prNum}.preview.${{ vars.PREVIEW_DOMAIN }}`;
            const sha7    = context.sha.substring(0, 7);

            const body = [
              MARKER,
              '## 🚀 Preview Environment',
              '',
              '| | |',
              '|:---|:---|',
              `| **Frontend** | [${baseUrl}](${baseUrl}) |`,
              `| **API Docs** | [${baseUrl}/api/v1/docs](${baseUrl}/api/v1/docs) |`,
              `| **Commit**   | \`${sha7}\` |`,
              `| **Updated**  | ${new Date().toISOString()} |`,
              '',
              '> ⚠️ Окружение **автоматически удаляется** при закрытии или мердже PR.',
            ].join('\n');

            const { data: comments } = await github.rest.issues.listComments({
              owner:        context.repo.owner,
              repo:         context.repo.repo,
              issue_number: prNum,
            });

            const existing = comments.find(c => c.body && c.body.includes(MARKER));
            if (existing) {
              await github.rest.issues.updateComment({
                owner:      context.repo.owner,
                repo:       context.repo.repo,
                comment_id: existing.id,
                body,
              });
            } else {
              await github.rest.issues.createComment({
                owner:        context.repo.owner,
                repo:         context.repo.repo,
                issue_number: prNum,
                body,
              });
            }
```

---

### 5.4 `.github/workflows/preview-teardown.yml`

```yaml
name: Preview — Teardown

on:
  pull_request:
    types: [closed]
    branches: [main, develop]

# Teardown не отменяется конкуренцией — он должен завершиться
concurrency:
  group: preview-pr-${{ github.event.pull_request.number }}-teardown
  cancel-in-progress: false

jobs:
  guard:
    runs-on: ubuntu-latest
    outputs:
      enabled: ${{ steps.chk.outputs.enabled }}
    steps:
      - id: chk
        run: echo "enabled=${{ vars.PREVIEW_ENVIRONMENTS_ENABLED }}" >> $GITHUB_OUTPUT

  teardown:
    needs: guard
    if: needs.guard.outputs.enabled == 'true'
    runs-on: ubuntu-latest
    permissions:
      deployments:   write
      pull-requests: write

    steps:
      - name: Destroy preview environment on server
        uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.PREVIEW_HOST }}
          username: deploy
          key:      ${{ secrets.PREVIEW_SSH_KEY }}
          script: |
            set -euo pipefail
            PR_NUMBER=${{ github.event.pull_request.number }}
            DEPLOY_DIR="/srv/sphere-previews/pr-${PR_NUMBER}"

            if [ ! -d "${DEPLOY_DIR}" ]; then
              echo "No preview for pr-${PR_NUMBER}, nothing to destroy"
              exit 0
            fi

            cd "${DEPLOY_DIR}"
            docker compose -f docker-compose.preview.yml down -v --remove-orphans --timeout 30 || true
            cd /
            rm -rf "${DEPLOY_DIR}"
            echo "✅ Preview pr-${PR_NUMBER} destroyed"

      - name: Mark GitHub Deployments as inactive
        uses: actions/github-script@v7
        with:
          script: |
            const env = `preview-pr-${context.payload.pull_request.number}`;
            const { data: deployments } = await github.rest.repos.listDeployments({
              owner:       context.repo.owner,
              repo:        context.repo.repo,
              environment: env,
            });
            for (const d of deployments) {
              await github.rest.repos.createDeploymentStatus({
                owner:         context.repo.owner,
                repo:          context.repo.repo,
                deployment_id: d.id,
                state:         'inactive',
                description:   'Preview destroyed (PR closed).',
              });
            }

      - name: Update PR comment → destroyed
        uses: actions/github-script@v7
        with:
          script: |
            const MARKER  = '<!-- sphere-preview-env -->';
            const prNum   = context.payload.pull_request.number;
            const reason  = context.payload.pull_request.merged ? 'смержен' : 'закрыт';

            const { data: comments } = await github.rest.issues.listComments({
              owner:        context.repo.owner,
              repo:         context.repo.repo,
              issue_number: prNum,
            });

            const existing = comments.find(c => c.body && c.body.includes(MARKER));
            if (existing) {
              await github.rest.issues.updateComment({
                owner:      context.repo.owner,
                repo:       context.repo.repo,
                comment_id: existing.id,
                body: [
                  MARKER,
                  '## Preview Environment',
                  '',
                  '| | |',
                  '|:---|:---|',
                  `| **Status** | 🗑️ Уничтожено |`,
                  `| **Причина** | PR ${reason} |`,
                ].join('\n'),
              });
            }
```

---

### 5.5 `.github/workflows/preview-cleanup.yml`

```yaml
# Удаляет "заброшенные" preview-окружения старше 24 ч
# Срабатывает: каждые 6 ч + вручную

name: Preview — Stale Cleanup

on:
  schedule:
    - cron: "0 */6 * * *"
  workflow_dispatch:

jobs:
  guard:
    runs-on: ubuntu-latest
    outputs:
      enabled: ${{ steps.chk.outputs.enabled }}
    steps:
      - id: chk
        run: echo "enabled=${{ vars.PREVIEW_ENVIRONMENTS_ENABLED }}" >> $GITHUB_OUTPUT

  cleanup:
    needs: guard
    if: needs.guard.outputs.enabled == 'true'
    runs-on: ubuntu-latest

    steps:
      - name: Remove stale preview environments (> 24 h)
        uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.PREVIEW_HOST }}
          username: deploy
          key:      ${{ secrets.PREVIEW_SSH_KEY }}
          script: |
            set -euo pipefail
            PREVIEW_ROOT="/srv/sphere-previews"
            MAX_AGE_HOURS=24
            CLEANED=0

            [ -d "${PREVIEW_ROOT}" ] || { echo "Nothing to clean"; exit 0; }

            NOW=$(date +%s)
            for DIR in "${PREVIEW_ROOT}"/pr-*; do
              [ -d "${DIR}" ] || continue
              MTIME=$(stat -c %Y "${DIR}")
              AGE=$(( (NOW - MTIME) / 3600 ))
              if [ "${AGE}" -ge "${MAX_AGE_HOURS}" ]; then
                PR_NUM=$(basename "${DIR}" | sed 's/pr-//')
                echo "Removing stale pr-${PR_NUM} (${AGE}h old)…"
                cd "${DIR}"
                docker compose -f docker-compose.preview.yml down -v --remove-orphans --timeout 30 || true
                cd /
                rm -rf "${DIR}"
                CLEANED=$((CLEANED + 1))
              fi
            done

            echo "✅ Stale cleanup done. Removed: ${CLEANED}"
```

---

### 5.6 Secrets и Variables

```
# GitHub → Settings → Secrets and Variables → Actions

# ── Repository VARIABLES (видны в логах — не секретные) ──────────────────────
PREVIEW_ENVIRONMENTS_ENABLED  = true               # ← ОПТ-ИН. По умолчанию НЕ создавать.
PREVIEW_DOMAIN                = sphere.example.com
ACME_EMAIL                    = your@email.com

# ── Repository SECRETS (скрыты в логах) ──────────────────────────────────────
PREVIEW_HOST        = <IP сервера>                 # тот же VPS, что и staging
PREVIEW_SSH_KEY     = <PEM deploy key private>     # отдельный ключ для deploy-пользователя
PREVIEW_DB_PASSWORD = <случайный 32+ символа>      # один пароль на все PRs (volumes изолированы)
PREVIEW_JWT_SECRET  = <случайный 32+ символа>      # JWT-secret только для preview (≠ staging/prod)
GHCR_PULL_TOKEN     = <GitHub PAT: read:packages>  # pull-only токен для Docker pull на сервере
CF_DNS_API_TOKEN    = <Cloudflare API token>        # DNS-challenge для wildcard TLS Traefik
```

> **Opt-out полностью:** удали или не создавай `PREVIEW_ENVIRONMENTS_ENABLED`.
> Все три workflow файла будут существовать в репозитории, но условие
> `if: needs.guard.outputs.enabled == 'true'` немедленно завершит все jobs за < 1 сек.
> **Нулевое влияние** на CI-backend, CI-android, deploy-staging и всё остальное.

---

## Критерии готовности

- [ ] PR открыт → CI запускается автоматически
- [ ] PR с упавшими тестами нельзя смержить
- [ ] PR с bandit HIGH severity нельзя смержить
- [ ] Coverage отчёт отправляется в Codecov
- [ ] Push в develop → автодеплой на staging
- [ ] Android APK собирается без ошибок на CI

**Preview Environments (только если `PREVIEW_ENVIRONMENTS_ENABLED = true`):**

- [ ] PR открыт → `https://pr-N.preview.sphere.example.com` доступен по HTTPS за ≤ 5 мин
- [ ] PR обновлён (sync) → preview пересобирается, старый деплой отменяется
- [ ] PR закрыт / смержен → окружение уничтожается автоматически (docker compose down -v)
- [ ] > 5 одновременных PRs → deploy завершается с читаемой ошибкой
- [ ] Окружение > 24 ч без активности → удаляется cron-cleanup
- [ ] В PR отображается актуальный comment с URL и статусом
- [ ] GitHub Deployments API отражает `success` / `failure` / `inactive`
