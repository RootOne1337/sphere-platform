.DEFAULT_GOAL := help

.PHONY: help setup dev full down test lint security migrate migrate-new build monitoring logs alembic-check alembic-merge-heads rls-lint branches worktree-setup seed-enrollment build-apk deploy-prod ssl-init ssl-renew start tunnel-keygen tunnel-build tunnel-up tunnel-down tunnel-sync tunnel-logs rebuild-backend rebuild-frontend

help:          ## Показать помощь
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

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
	alembic -c alembic/alembic.ini upgrade head

migrate-new:   ## Создать миграцию (name=описание)
	alembic -c alembic/alembic.ini revision --autogenerate -m "$(name)"

build:         ## Собрать production Docker образы
	docker compose -f docker-compose.production.yml build

monitoring:    ## Запустить Prometheus + Grafana
	docker compose -f infrastructure/monitoring/docker-compose.monitoring.yml up -d

logs:          ## Логи backend
	docker compose -f docker-compose.full.yml logs -f backend

alembic-check: ## Проверить наличие множественных Alembic heads (CI)
	@python -c "\
import subprocess, sys; \
r = subprocess.run(['alembic', '-c', 'alembic/alembic.ini', 'heads'], capture_output=True, text=True); \
heads = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]; \
print(f'Alembic heads: {len(heads)}'); \
[print(f'  {h}') for h in heads]; \
sys.exit(1 if len(heads) > 1 else 0)"

alembic-merge-heads: ## Автослияние множественных Alembic heads после merge stage-веток
	@echo "Проверяем количество Alembic heads..."
	@HEADS=$$(alembic -c alembic/alembic.ini heads 2>/dev/null | wc -l); \
	if [ "$$HEADS" -le 1 ]; then \
		echo "✅ Одна head — merge не нужен"; \
	else \
		echo "⚠️  Найдено $$HEADS heads — выполняем merge..."; \
		alembic -c alembic/alembic.ini merge heads -m "merge_parallel_stage_migrations"; \
		echo "✅ Heads объединены. Запусти: alembic -c alembic/alembic.ini upgrade head"; \
	fi

rls-lint:      ## Проверить что все таблицы с org_id имеют RLS policy
	@python scripts/check_rls.py

seed-enrollment: ## Создать enrollment API-ключ в БД (AGENT_CONFIG_ENV=production|staging|development)
	@echo "Запуск seed enrollment key (env=$${AGENT_CONFIG_ENV:-development})..."
	AGENT_CONFIG_ENV=$${AGENT_CONFIG_ENV:-development} python -m scripts.seed_enrollment_key

build-apk:     ## Собрать enterprise APK с зашитым CONFIG_URL (требует SPHERE_CONFIG_URL env)
	@if [ -z "$$SPHERE_CONFIG_URL" ]; then \
		echo "❌ Задай SPHERE_CONFIG_URL. Пример:"; \
		echo "   SPHERE_CONFIG_URL=https://adb.leetpc.com/api/v1/config/agent make build-apk"; \
		exit 1; \
	fi
	@echo "Сборка enterprise APK с CONFIG_URL=$$SPHERE_CONFIG_URL"
	cd android && ./gradlew assembleEnterpriseRelease
	@echo "✅ APK: android/app/build/outputs/apk/enterprise/release/"

deploy-prod:   ## Полный деплой production: build → migrate → seed → up
	@echo "═══ Production Deploy ═══"
	docker compose -f docker-compose.yml -f docker-compose.production.yml build
	docker compose -f docker-compose.yml -f docker-compose.production.yml up -d
	@echo "Ожидание старта backend..."
	@sleep 5
	docker compose exec backend alembic -c alembic/alembic.ini upgrade head
	AGENT_CONFIG_ENV=production docker compose exec backend python -m scripts.seed_enrollment_key
	@echo "✅ Production деплой завершён"
	@echo "   Теперь собери APK: SPHERE_CONFIG_URL=https://$${SERVER_HOSTNAME}/api/v1/config/agent make build-apk"


ssl-init:      ## Получить Let's Encrypt сертификат (первый раз на сервере)
	@bash scripts/init_ssl.sh

ssl-renew:     ## Принудительное обновление Let's Encrypt сертификата
	docker compose exec certbot certbot renew --webroot -w /var/www/certbot --force-renewal
	docker compose exec nginx nginx -s reload
	@echo 'Сертификат обновлён, nginx перезагружен'

# ── Туннель (autossh в Docker) ───────────────────────────────────────────────
tunnel-keygen: ## Сгенерировать SSH ключ для туннеля (один раз)
	@mkdir -p infrastructure/tunnel/keys
	@if [ -f infrastructure/tunnel/keys/id_rsa ]; then \
		echo '✅ Ключ уже существует: infrastructure/tunnel/keys/id_rsa'; \
	else \
		ssh-keygen -t ed25519 -C "sphere-tunnel@$$(hostname)" -f infrastructure/tunnel/keys/id_rsa -N ''; \
		echo '✅ Ключ сгенерирован!'; \
		echo ''; \
		echo 'Публичный ключ (для Serveo):'; \
		cat infrastructure/tunnel/keys/id_rsa.pub; \
	fi

tunnel-build:  ## Собрать Docker образ туннеля
	docker compose -f docker-compose.tunnel.yml build
	@echo '✅ Образ sphere-tunnel собран'

tunnel-up:     ## Поднять Serveo SSH-туннель (фиксированный URL sphere.serveousercontent.com)
	docker build -t sphere-tunnel:latest -f infrastructure/tunnel/Dockerfile infrastructure/tunnel/
	-docker stop sphere-tunnel 2>/dev/null; docker rm sphere-tunnel 2>/dev/null
	docker run -d \
	  --name sphere-tunnel \
	  --restart always \
	  --network sphere-platform_frontend-net \
	  -e TUNNEL_SUBDOMAIN=sphere \
	  -e TUNNEL_LOCAL_HOST=nginx \
	  -e TUNNEL_LOCAL_PORT=80 \
	  sphere-tunnel:latest
	@echo '✅ Serveo туннель запущен: https://sphere.serveousercontent.com'

tunnel-down:   ## Остановить туннель
	-docker stop sphere-tunnel 2>/dev/null; docker rm sphere-tunnel 2>/dev/null

tunnel-sync:   ## Синхронизировать текущий URL туннеля в .env + agent-config + рестарт бэкенда
	@bash scripts/sync-tunnel-url.sh

tunnel-url:    ## Показать текущий URL туннеля
	@echo 'https://sphere.serveousercontent.com'

tunnel-logs:   ## Логи туннеля в реальном времени
	docker compose -f docker-compose.tunnel.yml logs -f tunnel

# ── Пересборка отдельных сервисов ────────────────────────────────────────────
rebuild-backend:  ## Пересобрать только backend (при pip install)
	docker compose -f docker-compose.yml -f docker-compose.full.yml build backend
	docker compose -f docker-compose.yml -f docker-compose.full.yml up -d --no-deps backend
	@echo '✅ Backend пересобран и перезапущен'

rebuild-frontend: ## Пересобрать только frontend (при npm install)
	docker compose -f docker-compose.yml -f docker-compose.full.yml build frontend
	docker compose -f docker-compose.yml -f docker-compose.full.yml up -d --no-deps frontend
	@echo '✅ Frontend пересобран и перезапущен'

# ── Главный стартер ──────────────────────────────────────────────────────────
start:         ## 🚀 Запустить весь стек + туннель (главная команда для разработки)
	@echo '═══ Sphere Platform — Полный старт ═══'
	$(MAKE) full
	@echo 'Ожидание готовности БД...'
	@sleep 8
	$(MAKE) tunnel-up
	@echo ''
	@echo '╔═══════════════════════════════════════════╗'
	@echo '║         СТЕК ЗАПУЩЕН ПОЛНОСТЬЮ ✅          ║'
	@echo '╠═══════════════════════════════════════════╣'
	@echo '║  Frontend:  http://localhost:3000          ║'
	@echo '║  Backend:   http://localhost:8000          ║'
	@echo '║  API Docs:  http://localhost:8000/docs     ║'
	@printf '║  🌐 Public: %s\n' "$$(cat .tunnel-url 2>/dev/null || echo 'make tunnel-url')"
	@echo '╚═══════════════════════════════════════════╝'
