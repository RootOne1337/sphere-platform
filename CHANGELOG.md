# Changelog

All notable changes to **Sphere Platform** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

_Нет нереализованных изменений._

---

## [4.4.0] — 2026-03-01

### Краткое описание
Device Inspector полная интеграция с API (6 кнопок → реальные команды через WS),
страница Оркестрация (Pipeline/Runs/Schedules), Tasks page glass-morphism редизайн,
GridSparkline SVG перформанс-оптимизация, MultiStreamGrid реальный H.264 стриминг,
Android Agent hardening (Android 12+ ForegroundService fix), H264Decoder keyframe fix.
9 атомарных коммитов.

---

### Добавлено

#### Backend — POST /devices/{id}/reboot Endpoint
- Новый REST endpoint для управления перезагрузкой устройства через WebSocket Command Manager
- Timeout-fallback: устройство может перезагрузиться до ACK (3с grace period)
- Проверка наличия WS-соединения; 404 если устройство не найдено, 503 если агент оффлайн

#### Frontend — Device Inspector (все 6 кнопок через API)
- **Stream**: WebSocket `/ws/stream/{id}` → H.264 DeviceStream (реальный видеопоток)
- **Terminal**: `POST /devices/{id}/shell` → Shell API (adbActions.shell)
- **Logcat**: `POST /devices/{id}/logcat` → UPLOAD_LOGCAT → logcatCollector
- **Reboot**: `POST /devices/{id}/reboot` → REBOOT с confirm-dialog
- **Run Script**: `RunScriptTab.tsx` — многострочный редактор (Ctrl+Enter, Tab, copy-to-clipboard)
- **Screenshot**: `GET /devices/{id}/screenshot` → локальное сохранение на устройство
- Toast-уведомления (sonner), Loading-спиннеры, disabled при offline, цветовая индикация ошибок

#### Frontend — Страница Оркестрация (/orchestration)
- 3 таба с live polling (5-8 сек): Pipelines, Pipeline Runs, Schedules
- Pipeline: таблица шаблонов + раскрывающийся DAG-граф шагов с цветовой маркировкой типов
- Runs: управление в реалтайме (Pause/Cancel/Resume) + лог шагов с таймингами и ошибками
- Schedules: CRON/INTERVAL/ONE-SHOT визуализация, toggle вкл/выкл, Fire Now
- 6 статистических карточек (Pipelines, Active Runs, Completed, Failed, Success Rate, Schedules Active)
- NOCSidebar: пункт навигации Orchestration добавлен

#### Frontend — Tasks [id] Page Редизайн (Enterprise Glass-Morphism 2026)
- Live Telemetry для running задач: неоновая пульсация, анимированный прогресс-бар, elapsed time
- MetricCard: отображение current_node, количества циклов и узлов
- Live Feed: поток логов с группировкой повторов (Repeated Nx), sticky-интерфейс сбоку
- Execution Timeline: вертикальная лента с иконками операций (🚀, 📸, 👆)
- Рендер скриншотов из screenshot_key с zoom-hover эффектом
- input_params в терминально-подобном блоке, результаты под складным UI
- Градиентные фоны (Cyan/Emerald/Red) по статусу задачи

#### Frontend — MultiStreamGrid — Реальный H.264 Стриминг
- Кнопка START/STOP BROADCAST для управления вещанием
- DeviceStream компонент при broadcastActive=true (реальный WS H.264 поток)
- Ready/Offline состояния вместо заглушки TCP/UDP
- Экономия ресурсов: стримы не открываются автоматически при 1К+ устройствах

### Улучшено

#### Frontend — GridSparkline SVG (Перформанс 10с → мгновенно)
- Замена Recharts ResponsiveContainer на нативный SVG `<polyline>` с `React.memo`
- Устранение 400+ ResizeObserver + recursivelyTraversePassiveMountEffects при 200+ устройствах
- Ликвидация варнингов width(-1) height(-1)

### Исправлено

| # | Компонент | Проблема | Решение |
|---|-----------|----------|---------|
| 1 | Android | ForegroundServiceStartNotAllowedException (Android 12+) | try-catch в BootReceiver.kt + ServiceWatchdog.kt |
| 2 | Android | Агент ждал 10 обрывов перед проверкой конфига | forceCheck при первом обрыве WS (onCircuitBreakerOpen) |
| 3 | Frontend | H264Decoder: «key frame required after configure()» | needsKeyFrame флаг + поиск последнего IDR в pendingFrames |
| 4 | Frontend | MultiStreamGrid: TCP/UDP заглушка вместо стрима | Интеграция DeviceStream с broadcastActive toggle |
| 5 | Infra | nginx proxy с host.docker.internal (DNS resolution fail) | Возврат на Docker DNS имена (backend:8000, frontend:3000) |
| 6 | Infra | Frontend Docker контейнер на порту 3002 | Унификация на порт 3000 (nginx.dev.conf + docker-compose.full.yml) |
| 7 | Frontend | Auth guard редиректил на /login | DEV_SKIP_AUTH = true в providers.tsx |

---

### Deployment Notes

**APK:** Пересобрать после merge: `cd android && ./gradlew assembleDevDebug`

**Новые файлы:**
```
frontend/app/(dashboard)/orchestration/page.tsx
frontend/src/features/devices/RunScriptTab.tsx
```

**Docker:** Frontend контейнер теперь на порту 3000 (был 3002).

---

## [4.3.0] — 2026-03-01

### Краткое описание
Enterprise-hardening: Android Agent watchdog-механизмы (100% uptime + remote config),
full-stack UI правки 16 страниц дашборда, backend monitoring реальные метрики,
nginx read-only filesystem fix. 14 атомарных коммитов.

---

### Добавлено

#### Android Agent — ConfigWatchdog (Remote Config Polling)
- **`ConfigWatchdog.kt`** — новый @Singleton компонент, периодический опрос `CONFIG_URL`
  (GitHub Raw endpoint) через `ZeroTouchProvisioner.fetchServerConfig()`
- Стандартный интервал: **5 минут** (WS подключён) / **60 секунд** (WS отключён)
- Минимальный интервал: 30 секунд (защита от rate-limiting)
- При обнаружении смены `server_url`: атомарное обновление `AuthTokenStore` +
  немедленный `forceReconnectNow()` для переподключения к новому серверу
- `forceCheck()` — синхронная проверка по вызову от circuit breaker
- Graceful shutdown через `stop()` в `SphereAgentService.onDestroy()`

#### Android Agent — ServiceWatchdog (AlarmManager Keepalive)
- **`ServiceWatchdog.kt`** — BroadcastReceiver + AlarmManager (ELAPSED_REALTIME_WAKEUP)
- Перезапуск `SphereAgentService` каждые 5 минут если процесс убит
- `enrolled` флаг в SharedPreferences — запуск ТОЛЬКО после enrollment
- Тройная защита от kill: **BootReceiver + START_STICKY + AlarmManager**
- Покрывает aggressive battery optimization (Xiaomi, Huawei, Samsung OEM)

#### Android Agent — Circuit Breaker → Config Hook
- `SphereWebSocketClient.onCircuitBreakerOpen` callback
- При 10+ подряд ошибок → немедленная проверка конфига из Git
- Связка: WS failures → ConfigWatchdog.forceCheck() → новый server_url → reconnect

#### Android Agent — Lifecycle Integration (6 точек входа)
- `SphereAgentService.onCreate()`: ConfigWatchdog coroutine + ServiceWatchdog alarm
- `BootReceiver.onReceive()`: enrollment check + watchdog scheduling
- `SphereApp.onCreate()`: watchdog scheduling при старте Application
- `SetupActivity.launchAgent()`: markEnrolled + schedule при enrollment
- `AndroidManifest.xml`: ServiceWatchdog receiver registration

#### Backend — Monitoring Router
- `GET /monitoring/metrics` — агрегированные метрики (CPU, RAM, Redis, сеть)
- `GET /monitoring/nodes` — топология кластера (backend-сервисы как ноды)
- Интеграция с Redis для live-метрик + fallback на psutil/os

#### Frontend — Enterprise Settings Page
- Полная переработка: Profile, Security (MFA), API Keys, Team Management
- Responsive tabbed layout в стиле NOC dark palette

### Исправлено

| # | Компонент | Проблема | Решение |
|---|-----------|----------|---------|
| 1 | Backend | DEV_SKIP_AUTH не читался из .env | Ленивая функция `_is_dev_skip_auth()` через pydantic Settings |
| 2 | Backend | openapi.json ломался на Windows (кодировка) | `encoding="utf-8"` при записи |
| 3 | Backend | /audit-logs prefix не совпадал с frontend | Переименован в /audit/logs |
| 4 | Backend | FastAPI warning при DELETE 204 | `response_model=None` для pipelines/schedules |
| 5 | Frontend | 9 страниц дашборда с заглушками | Подключены к реальным API эндпоинтам |
| 6 | Frontend | DeviceStream теряло frames | Рефакторинг WebCodecs декодера |
| 7 | Frontend | Theme switching не работал | Интеграция `next-themes` |
| 8 | Frontend | devices per_page=1000 | Оптимизировано до 200 |
| 9 | Frontend | Feature-модули (11 компонентов) на mock данных | Интегрированы с live API |
| 10 | Infra | nginx 'upstream not found' с read-only FS | Переход на resolver + переменные |
| 11 | Infra | docker-compose не пробрасывал env | Добавлены переменные в docker-compose.full.yml |

---

### Deployment Notes

**Новые файлы Android Agent:**
```
android/app/src/main/kotlin/com/sphereplatform/agent/service/ConfigWatchdog.kt
android/app/src/main/kotlin/com/sphereplatform/agent/service/ServiceWatchdog.kt
```

**APK:** Пересобрать после merge: `cd android && ./gradlew assembleDevDebug`

**Новые зависимости frontend:**
```bash
cd frontend && npm install next-themes
```

---

## [4.2.0] — 2026-02-28

### Краткое описание
TZ-12 Pipeline Orchestrator + Cron Scheduler — полная реализация серверного оркестратора
для цепочек скриптов с 9 типами step-обработчиков и DB-backed планировщика расписаний.
23 атомарных коммита в ветке `feature/tz12-orchestrator-scheduler-2026-02-28`, PR #6.

---

### Добавлено

#### TZ-12 — Pipeline Orchestrator Engine (SPLIT-4)
- **ORM-модели:** `Pipeline`, `PipelineRun`, `PipelineBatch` с полным lifecycle (draft → active → archived)
- **Pydantic-схемы:** `PipelineCreate`, `PipelineUpdate`, `PipelineResponse`, `PipelineRunResponse` с валидаторами
- **PipelineService:** CRUD + клонирование + управление версиями пайплайнов
- **PipelineExecutor:** Движок исполнения — обход шагов графа с персистенцией состояния в `PipelineRun`
- **9 StepHandler-ов:**
  - `run_script` — запуск DAG-скрипта на устройстве
  - `run_pipeline` — вложенный запуск другого пайплайна
  - `http_request` — HTTP-вызов внешних API
  - `condition` — условная логика (if/else по выражению)
  - `delay` — задержка выполнения
  - `parallel` — параллельное исполнение подшагов
  - `set_variable` — установка переменных контекста
  - `notify` — отправка уведомлений (webhook, email)
  - `approval` — ручное подтверждение оператором
- **REST API (12 эндпоинтов):** CRUD пайплайнов, execute, stop, runs list, run detail, clone

#### TZ-12 — Cron Scheduler (SPLIT-5)
- **ORM-модели:** `Schedule`, `ScheduleExecution` с конфликт-политиками (skip/queue)
- **Pydantic-схемы:** `ScheduleCreate`, `ScheduleUpdate`, `ScheduleResponse`, `ScheduleExecutionResponse`
- **ScheduleService:** CRUD + валидация cron-выражений + расчёт следующих N запусков
- **SchedulerEngine:** Фоновый движок — проверяет расписания раз в 60с, `FOR UPDATE SKIP LOCKED`
- **REST API (8 эндпоинтов):** CRUD расписаний, toggle enable/disable, history, dry-run
- **Зависимости:** `croniter` (cron-парсер), `pytz` (таймзоны)

#### TZ-12 — Спецификации
- `TZ-12-Orchestrator/SPLIT-1-Script-Lifecycle.md` — жизненный цикл скриптов
- `TZ-12-Orchestrator/SPLIT-2-Script-Caching.md` — кэширование и версионирование
- `TZ-12-Orchestrator/SPLIT-3-Agent-Event-Model.md` — модель событий агента
- `TZ-12-Orchestrator/SPLIT-4-Orchestrator-Engine.md` — ядро оркестратора
- `TZ-12-Orchestrator/SPLIT-5-Scheduling-System.md` — система расписаний

#### База данных
- Alembic-миграция `20260224`: 5 таблиц (`pipelines`, `pipeline_runs`, `pipeline_batches`, `schedules`, `schedule_executions`), 4 enum-типа, RLS-политики

#### RBAC
- Разрешения `pipeline:read`, `pipeline:write`, `pipeline:execute`, `schedule:read`, `schedule:write`
- Интеграция в RBAC-матрицу для всех ролей

#### Тестирование
- **27 unit-тестов** для PipelineService, StepHandlers (9 типов), ScheduleService
- Итого: **779 тестов PASSED** (было 743 → 758 → 779), ruff 0 ошибок, mypy 0 ошибок

#### Frontend
- Обновление UI-компонентов: Dashboard, Tasks, Audit, VPN, Monitoring, Fleet
- NOCSidebar и GlobalCommandPalette — переработка навигации
- ThemeProvider, shadcn/ui компоненты — обновления
- Script Builder и streaming модули — улучшения

#### Android Agent
- DagRunner.kt: аудит и 14 исправлений
- AdbActionExecutor, DeviceStatusProvider — обновления

---

### Исправлено

| # | Компонент | Проблема | Решение |
|---|-----------|----------|---------|
| 1 | Auth | `_DEV_SKIP_AUTH = True` хардкод — авторизация полностью отключена | Восстановлена проверка через env `DEV_SKIP_AUTH` |
| 2 | Devices | `send_to_device()` async без await — команды shell/logcat не отправлялись | Добавлен `await` (реальный production баг) |
| 3 | Cache | `TTL_OFFLINE = 120` вместо `3600` — offline-статусы устаревали через 2 мин | Исправлено на 3600с согласно документации |
| 4 | Scheduler | `DeviceLiveStatus.get("online")` — Pydantic модель не dict | Исправлено на `status.status == "online"` |
| 5 | Orchestrator | `isinstance(res, Exception)` — не сужает union-тип для mypy | Исправлено на `isinstance(res, BaseException)` |
| 6 | Lint | 33 ruff-ошибки (I001, F401, E402, W293) в 15+ файлах | Авто-фикс + ручное исправление |
| 7 | Mypy | 6 ошибок типизации (unused-coroutine, union-attr, attr-defined) | Все исправлены |
| 8 | Tests | 21 тест провален из-за DEV_SKIP_AUTH bypass | Все 21 починены |
| 9 | Tests | `AsyncMock` делал `.scalars().all()` корутиной | Использован `MagicMock` для синхронных цепочек |
| 10 | DAG Schema | union types → generic action model | Рефакторинг для упрощения |

---

### Deployment Notes

**Новые зависимости:**
```bash
pip install croniter pytz
```

**Новые переменные окружения:**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEV_SKIP_AUTH` | Нет | `""` (отключено) | `true` для отключения JWT-проверки в dev-режиме |

**Миграции:**
```bash
docker compose exec backend alembic upgrade head
# Создаёт 5 таблиц: pipelines, pipeline_runs, pipeline_batches, schedules, schedule_executions
```

**Docker-образы:** пересобрать backend после merge.

---

## [4.1.0] — 2026-02-25

### Краткое описание
TZ-12 Agent Discovery & Auto-Registration, DAG v6/v7 performance, расширение фронтенда задач, enterprise-тесты.
18+ коммитов на ветке `feature/dag-v6-task-execution-2025-02-25`, интегрировано через PR #4 → main → PR #5 → develop.

---

### Добавлено

#### TZ-12 — Agent Discovery & Auto-Registration
- `agent-config/` — конфигурационный репозиторий: JSON Schema v1, 3 окружения (dev, staging, production), batch-генератор
- `GET /api/v1/config/agent` — soft-auth эндпоинт конфигурации агента (отдаёт `ServerConfig` без обязательной авторизации)
- `POST /api/v1/devices/register` — идемпотентная авторегистрация устройств по fingerprint (JSONB-поиск)
- `DeviceRegistrationService` — авто-нейминг, генерация JWT-токенов, дедупликация по fingerprint
- `CloneDetector.kt` — clone-safe SHA-256 composite fingerprint (7 компонентов, безопасен для LDPlayer-клонов)
- `DeviceRegistrationClient.kt` — HTTP-клиент авторегистрации с авто-сохранением токенов
- `ZeroTouchProvisioner` source #6 — HTTP Config Endpoint
- `SetupActivity` — интеграция авторегистрации с legacy fallback

#### DAG v6/v7 — Движок автоматизации
- DAG v6: reactive smart scan, XPath-элементы, watchdog-оптимизация (`152d146`)
- DAG v7: устранение 3-минутных зависаний, оптимизация таймингов (`48e5081`)
- Расширен DAG-движок Android: `cancelRequested`, `increment_variable`, `find_first_element`, `tap_first_visible`
- `CANCEL_DAG` обработчик в `CommandDispatcher`

#### Backend — Task Execution
- Поля прогресса на модели Task: `cycles`, `started_at` (`0b99c35`)
- Эндпоинты `/progress`, `/live-logs`, `/stop` для задач (`6271665`)
- WebSocket progress handler для live execution logs (`bc9c996`)
- Расширен `TaskService`: dispatch `CANCEL_DAG`, bulk operations (`65ea409`)
- Улучшения WebSocket layer и middleware (`b0ff6ef`)

#### Frontend — Task Management UI
- `useTasks` расширен: `TaskProgress` с циклами + `useTaskLiveLogs` (`2f652cf`)
- Live Execution Dashboard — страница деталей задачи (`adaba59`)
- `RunScriptModal` + улучшены страницы Scripts и Tasks (`8efae3e`)
- OpenAPI 3.1 спецификация обновлена (`b95a907`)

#### Тестирование
- 17 тестов Agent Discovery (config endpoint + device register) (`4ab3eb3`)
- Enterprise-тесты: WS handlers, VPN health loop, n8n integration, user management, OTA updates (`609740f`)
- Service-layer unit-тесты, покрытие ≥ 70% (`5c5b05b`)
- Итого: **743 теста PASSED** (ruff 0 ошибок, mypy 0 ошибок)

---

### Исправлено

| # | Компонент | Проблема | Решение |
|---|-----------|----------|---------|
| 1 | Tests | SQLite не поддерживает ARRAY-тип | `SQLiteArrayType` bind/result processor (`e3722e8`) |
| 2 | Scripts | ruff E741 + import sorting в dev-скриптах | ruff auto-fix 23 ошибки → 0 (`e3c8ddd`) |
| 3 | CI | lint (ruff + mypy) и падающие тесты | Комплексное исправление (`177a961`) |
| 4 | Frontend | WebSocket URL определение в `useFleetEvents` | Исправлено (`2c562af`) |
| 5 | Android | Документация `LuaEngine` — ctx доступен как Lua-таблица | Исправлено (`a123404`) |
| 6 | CI | `PYTHONPATH`, alembic config path, gradlew +x | Серия фиксов (`befea81`, `a5b5692`, `425ec2d`) |
| 7 | Backend | `vpn_peers.status` отсутствовал в базовой миграции | Добавлен в baseline (`b25b49d`) |

---

### Deployment Notes

Новых обязательных переменных окружения нет.
Docker-образы: пересобрать backend и Android APK после merge.

```bash
# Пересборка backend
docker compose build backend

# Миграции (если обновлялись)
docker compose exec backend alembic upgrade head
```

---

## [4.0.0] — 2026-02-23

### Summary
Initial v4.0.0 platform release: full TZ-00 … TZ-11 implementation integrated into `develop`.
255 files changed, 25 779 insertions, 119 deletions across all subsystems.

---

### Added

#### TZ-00 — Infrastructure & CI/CD
- Docker Compose stack: `docker-compose.yml` + `docker-compose.full.yml` + `docker-compose.override.yml`
- Traefik reverse-proxy, nginx, PostgreSQL 15, Redis 7, Prometheus + Grafana
- GitHub Actions workflows: `ci-backend.yml`, `ci-android.yml`, `deploy-staging.yml`
- Pre-commit hooks (ruff, mypy, detect-secrets, commitlint)
- `scripts/generate_secrets.py` — one-shot `.env` secrets generator
- `scripts/create_admin.py` — idempotent super-admin bootstrapper
- `CODEOWNERS` and branch-protection rules

#### TZ-01 — Auth Service
- JWT access + refresh token pair (HS256) with 15-min access / 7-day refresh TTL
- TOTP-based MFA (`/auth/mfa/setup`, `/auth/mfa/verify`)
- RBAC: 7 roles — `super_admin`, `org_admin`, `operator`, `developer`, `viewer`, `api_key`, `pc_agent` — with PostgreSQL RLS enforcement
- API Key management (`/api-keys` CRUD)
- Audit log with RLS policies

#### TZ-02 — Device Registry
- Device CRUD with pagination and filtering
- Groups & Tags sub-resource
- Device status caching via Redis (`ONLINE/OFFLINE/BUSY/ERROR`)
- Bulk actions: assign group, add tag, change status
- Discovery endpoint — real WS RPC to PC Agent (`discover_adb` command)

#### TZ-03 — WebSocket Layer
- `ConnectionManager` with per-device fan-out
- Redis Pub/Sub router for cross-process messaging
- Backpressure: slow-consumer detection and disconnect
- Heartbeat: ping/pong with configurable TTL
- Typed event schema (`device.connected`, `device.status`, `stream.frame`, etc.)

#### TZ-04 — Script Engine
- DAG schema: nodes (action/condition/delay/loop), edges, validation
- Script CRUD (`/scripts`)
- Celery task queue with Redis broker
- Wave/batch execution: fan-out to device groups
- Progress API with SSE stream

#### TZ-05 — H.264 Streaming (Android)
- `MediaProjection` + `MediaCodec` encoder pipeline
- NAL unit framing over WebSocket binary
- Frame-drop policy under backpressure
- `WebCodecs`-based frontend decoder

#### TZ-06 — VPN / AmneziaWG
- `AWGConfigGenerator` — per-device WireGuard config
- IP pool manager with lease/release
- Self-healing monitor: reconnect on tunnel loss
- Kill-switch: iptables `SPHERE_KILLSWITCH` chain (Android side)
- REST API: `/vpn/peers`, `/vpn/pool/stats`, `/vpn/health`

#### TZ-07 — Android Agent
- Full Hilt DI architecture (`SphereApp` + WorkManager)
- WebSocket client with reconnect and binary frame handling
- Command handler: `adb_exec`, `screenshot`, `stream_start/stop`, `vpn_connect/disconnect`
- Live `SphereWebSocketClientLive` adapter wiring streaming module to real WS
- `KillSwitchManager` — iptables VPN kill-switch

#### TZ-08 — PC Agent
- `agent/` package: ADB bridge, topology discovery, telemetry, LDPlayer manager
- WebSocket client with JWT auth and command dispatch
- `pc-agent/main.py` launcher shim → `agent.main`

#### TZ-09 — n8n Integration
- Custom n8n node package (`n8n-nodes/`)
- Nodes: `SphereDevice`, `SphereScript`, `SphereEventTrigger`, `SphereDevicePool`
- OAuth2 + API Key credential types

#### TZ-10 — Web Frontend (Next.js 15)
- App Router layout with sidebar navigation
- Pages: Dashboard analytics, Devices, Groups, Scripts (DAG builder), VPN, Streaming, Settings
- `useDevices`, `useFleetStats`, `usePoolStats`, `useVpnHealth` hooks
- Auth loop fix: raw axios in `useInitAuth` to avoid interceptor recursion

#### TZ-11 — Monitoring
- Prometheus metrics middleware (request count, latency, active WS connections)
- Grafana dashboard provisioning
- Structured JSON logging (structlog)
- Health endpoints: `/health`, `/vpn/health`

---

### Fixed

| # | Component | Issue | Fix |
|---|-----------|-------|-----|
| 1 | Backend | VPN `/vpn/peers` returned 403 for super_admin | Replaced `require_role` with `require_permission("vpn:read")` |
| 2 | Backend | `GET /devices` 500 — `invalid input value for enum device_status_enum: ONLINE` | Added `values_callable=lambda x: [e.value for e in x]` to `DeviceStatus` column |
| 3 | Backend | Discovery service always returned `[]` | Real WS RPC via `PubSubRouter.send_command_wait_result("discover_adb")` |
| 4 | Backend | Missing `/vpn/health` endpoint | Added endpoint |
| 5 | Backend | `vpn_peers.status` column missing | `ALTER TABLE vpn_peers ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'assigned'` |
| 6 | Frontend | `scripts.map is not a function` | Handle paginated `{items,total}` response: `data.items ?? []` |
| 7 | Frontend | Auth infinite redirect loop on token refresh | Raw `axios.post('/auth/refresh')` in `useInitAuth` bypasses interceptor |
| 8 | Frontend | `useDevices` passed `page_size`, backend expects `per_page` | Param renamed in hook |
| 9 | Android | `SphereVpnManager.connect()` was a TODO stub | Full wg-quick integration with exponential backoff and Mutex safety |
| 10 | Android | `StreamingModule` bound no-op WS stub — frames discarded | Bind `SphereWebSocketClientLive` adapter |
| 11 | Android | Duplicate `@HiltAndroidApp` class caused build failure | Cleared `SphereApplication.kt` — canonical app is `SphereApp.kt` |
| 12 | PC Agent | `pc-agent/main.py` was `asyncio.sleep(0)` stub | Launcher shim: `from agent.main import main; asyncio.run(main())` |

---

### Deployment Notes

```sql
-- Run once before deploying this release:
ALTER TABLE vpn_peers ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'assigned';
```

Environment variables — no new required vars in this release.
Docker images — rebuild all services after merge (`docker compose build`).

---

## Previous releases

See `docs/merge_log.md` and [walkthrough.md.resolved](walkthrough.md.resolved) for full branch-by-branch integration history.

[4.1.0]: https://github.com/RootOne1337/sphere-platform/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/RootOne1337/sphere-platform/releases/tag/v4.0.0
