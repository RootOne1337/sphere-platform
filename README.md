<div align="center">

# Sphere Platform

**Enterprise Android Device Management & Remote Control Platform**

[![CI Backend](https://github.com/RootOne1337/sphere-platform/actions/workflows/ci-backend.yml/badge.svg)](https://github.com/RootOne1337/sphere-platform/actions)
[![CI Android](https://github.com/RootOne1337/sphere-platform/actions/workflows/ci-android.yml/badge.svg)](https://github.com/RootOne1337/sphere-platform/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-4.3.0-brightgreen.svg)](VERSION)

[Документация](docs/) · [API Reference](docs/api-reference.md) · [Deployment Guide](docs/deployment.md) · [Changelog](CHANGELOG.md)

</div>

---

## Обзор

Sphere Platform — production-ready система для управления, мониторинга и автоматизации крупных парков Android-устройств через защищённый VPN. Обеспечивает H.264 стриминг в реальном времени, DAG-движок автоматизации скриптов и глубокую интеграцию с n8n для no-code workflow.

### Ключевые возможности

| Возможность | Описание |
|-------------|----------|
| **Управление флотом** | Регистрация, группировка, тегирование и мониторинг 1000+ Android-устройств |
| **Удалённое управление** | H.264 видеопоток в реальном времени + выполнение ADB-команд |
| **Автоматизация скриптов** | DAG-based скрипты v7 с wave/batch исполнением по группам устройств |
| **Pipeline Orchestrator** | Цепочки скриптов (Pipeline) с параллельными/последовательными шагами, условной логикой и 9 типами step-обработчиков |
| **Cron Scheduler** | Собственный DB-backed планировщик с croniter, конфликт-политиками (skip/queue) и SKIP LOCKED |
| **VPN-туннелирование** | AmneziaWG (обфусцированный WireGuard) per-device туннели с IP-пулом |
| **Agent Discovery** | Zero-touch автообнаружение и авторегистрация 1000+ эмуляторов LDPlayer |
| **Agent Resilience** | ConfigWatchdog (remote config polling из Git) + ServiceWatchdog (AlarmManager 100% uptime) + Circuit Breaker → auto-reconnect |
| **n8n интеграция** | Нативные n8n-ноды для no-code автоматизации |
| **PC Agent** | Host-side ADB-мост для обнаружения USB-устройств |
| **Мониторинг** | Prometheus + Grafana дашборды, структурированное логирование, алертинг |

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Internet / LAN                                  │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ HTTPS / WSS
                    ┌──────▼──────┐
                    │   nginx      │  TLS termination, rate limiting
                    │  (reverse    │  static assets, WS upgrade
                    │   proxy)     │
                    └──────┬───────┘
          ┌────────────────┼──────────────────┐
          │                │                  │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌───────▼──────┐
   │  FastAPI    │  │  Next.js 15 │  │  n8n         │
   │  Backend    │  │  Frontend   │  │  Workflows   │
   │  :8000      │  │  :3000      │  │  :5678       │
   └──────┬───────┘  └─────────────┘  └──────────────┘
          │
   ┌──────┴──────────────────────────┐
   │                                  │
   ▼                                  ▼
PostgreSQL 15              Redis 7 (cache + pub/sub)
(primary data store,       (WS sessions, device status,
 RLS policies)              task queue, config cache)
          │
   ┌──────▼──────────────────────────────┐
   │          WebSocket Layer             │
   │  ConnectionManager + PubSubRouter   │
   └──────┬──────────────────────────────┘
          │  Secure WebSocket (wss://)
   ┌──────┴───────────────────────────────┐
   │                                       │
   ▼                                       ▼
Android Agent                      PC Agent
(on-device APK v1.2.0)            (Windows/Linux host)
  - H.264 streaming                  - ADB bridge
  - AmneziaWG VPN                    - Device discovery
  - Command handler                  - LDPlayer manager
  - Zero-touch auto-registration     - Telemetry
  - Clone detection (LDPlayer)       - DAG v7 execution
  - OTA updates
```

### Agent Discovery Flow (TZ-12)

```
LDPlayer Clone N ──► ZeroTouchProvisioner
                         │
                    GET /api/v1/config/agent     ← конфиг без авторизации
                         │
                    ServerConfig(autoRegister=true)
                         │
                    POST /api/v1/devices/register ← идемпотентная регистрация
                         │
                    Device(fingerprint, JWT tokens) → готов к работе
```

### Pipeline Orchestrator (TZ-12)

```
REST API
  │
  POST /api/v1/pipelines/{id}/execute
  │
  ▼
PipelineService ──► PipelineExecutor ──► StepHandlers (9 типов)
  │                      │                   ├── run_script
  │                      │                   ├── run_pipeline (вложенные)
  │                      │                   ├── http_request
  │                      │                   ├── condition (if/else)
  │                      │                   ├── delay
  │                      │                   ├── parallel
  │                      │                   ├── set_variable
  │                      │                   ├── notify
  │                      │                   └── approval (ручной)
  │                      │
  ▼                      ▼
Pipeline (ORM)     PipelineRun (ORM) ── состояние каждого шага
  │
  ▼
SchedulerEngine ──► croniter ──► периодический запуск по расписанию
  │                               (FOR UPDATE SKIP LOCKED)
  ▼
Schedule (ORM) ──► ScheduleExecution (история)
```

### Agent Resilience Architecture (v4.3.0)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Android Agent Watchdog System                      │
│                                                                      │
│   6-Level Restart Guarantee:                                         │
│                                                                      │
│   1. BootReceiver         → BOOT_COMPLETED / QUICKBOOT_POWERON       │
│   2. START_STICKY          → OS auto-restart after OOM kill          │
│   3. ServiceWatchdog       → AlarmManager every 5 min                │
│   4. Application.onCreate  → watchdog scheduling on app start        │
│   5. ConfigWatchdog        → remote config polling (GitHub Raw)      │
│   6. NetworkChangeHandler  → instant reconnect on network change     │
│                                                                      │
│   Config Auto-Discovery:                                             │
│   GitHub Raw ──► ZeroTouchProvisioner.fetchServerConfig()            │
│         │                                                            │
│         ├─ server_url changed? → authStore.saveServerUrl()           │
│         │                       → wsClient.forceReconnectNow()       │
│         │                                                            │
│         └─ Circuit Breaker (10 failures) → forceCheck() → Git poll  │
└─────────────────────────────────────────────────────────────────────┘
```

> Полная документация по архитектуре: [docs/architecture.md](docs/architecture.md)

---

## Быстрый старт

### Требования

- Docker Desktop 4.x+ с Compose V2
- Минимум 4 ГБ оперативной памяти (рекомендуется 8 ГБ)
- Свободные порты: 80, 443, 5432 (только dev), 6379 (только dev)

### 1 — Клонирование и генерация секретов

```bash
git clone https://github.com/RootOne1337/sphere-platform.git
cd sphere-platform
python scripts/generate_secrets.py          # создаёт .env.local
```

### 2 — Запуск стека

```bash
# Разработка (с hot-reload)
docker compose -f docker-compose.yml -f docker-compose.full.yml -f docker-compose.override.yml up -d

# Проверка статуса всех сервисов
docker compose ps
```

### 3 — Миграции и создание администратора

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/create_admin.py
```

### 4 — Интерфейсы

| Сервис | URL |
|--------|-----|
| Веб-интерфейс | http://localhost |
| API Docs (Swagger) | http://localhost/api/v1/docs |
| API Docs (ReDoc) | http://localhost/api/v1/redoc |
| Grafana | http://localhost:3001 |
| n8n | http://localhost:5678 |

Суперадмин создаётся при первом запуске `create_admin.py` — учётные данные задаёшь самостоятельно.

---

## Структура проекта

```
sphere-platform/
├── backend/                # FastAPI-приложение (Python 3.12)
│   ├── api/v1/             # REST-эндпоинты (21 модуль: auth, devices, pipelines, schedules, …)
│   ├── api/ws/             # WebSocket-маршруты (подключение устройств, стриминг)
│   ├── core/               # Конфигурация, RBAC, JWT, зависимости
│   ├── models/             # SQLAlchemy ORM модели (17 таблиц + Alembic миграции)
│   ├── schemas/            # Pydantic request/response схемы
│   ├── services/           # Бизнес-логика (orchestrator/, scheduler/, vpn/, …)
│   ├── tasks/              # Фоновые asyncio-задачи (sync_device_status, scheduler_engine)
│   ├── websocket/          # ConnectionManager + PubSubRouter
│   └── monitoring/         # Prometheus-метрики, healthcheck
│
├── frontend/               # Next.js 15 App Router (React 19)
│   ├── app/(auth)/         # Страница авторизации
│   ├── app/(dashboard)/    # Dashboard, Devices, Scripts, Stream, VPN, Tasks, Fleet, Monitoring
│   ├── components/         # UI-компоненты (shadcn/ui)
│   ├── hooks/              # TanStack Query data hooks
│   └── lib/                # Axios-клиент, Zustand auth store
│
├── android/                # Android Agent (Kotlin + Hilt, APK v1.3.0)
│   └── app/src/main/       # Services, VPN, Streaming, Commands, DI, ConfigWatchdog, ServiceWatchdog
│
├── pc-agent/               # PC Agent (Python asyncio)
│   └── modules/            # ADB bridge, device discovery, telemetry, WS client
│
├── agent-config/           # Конфигурации для zero-touch provisioning агентов
│   ├── schema/             # JSON Schema v1 для валидации конфигов
│   ├── environments/       # Конфиги по окружениям (dev, staging, production)
│   ├── tools/              # Генератор batch-конфигов для массовых развёртываний
│   └── README.md           # Документация конфигурационного репозитория
│
├── n8n-nodes/              # Кастомные n8n-ноды для интеграции
│
├── infrastructure/
│   ├── nginx/              # nginx.conf + SSL
│   ├── postgres/           # init.sql, RLS-политики, аудит
│   ├── redis/              # Конфиг Redis
│   ├── monitoring/         # Prometheus, Grafana дашборды, Alertmanager
│   └── traefik/            # Альтернатива: Traefik reverse proxy
│
├── alembic/                # Миграции базы данных
│   └── versions/           # Скрипты миграций
│
├── tests/                  # Pytest-тесты (779 тестов, 100% pass rate)
├── scripts/                # Утилиты (генерация секретов, создание admin)
├── .github/                # CI/CD workflows, PR шаблон, CODEOWNERS
└── docs/                   # Документация проекта
```

---

## Технологический стек

### Backend
| Компонент | Технология |
|-----------|------------|
| Фреймворк | FastAPI 0.115+ + Uvicorn |
| ORM | SQLAlchemy 2.0 (async) |
| БД | PostgreSQL 15 (RLS-политики) |
| Кэш / Брокер | Redis 7.2 (pub/sub, кэш конфигов, очередь задач) |
| Аутентификация | JWT HS256 (access + refresh) + TOTP MFA |
| Задачи | asyncio Tasks + Redis PubSub |
| Метрики | Prometheus + structlog |
| Миграции | Alembic |

### Frontend
| Компонент | Технология |
|-----------|------------|
| Фреймворк | Next.js 15.1.0 (App Router) |
| Стейт | Zustand + TanStack Query v5 |
| UI | shadcn/ui + Radix UI + Tailwind CSS |
| Графы / DAG | Recharts + @xyflow/react |
| Аутентификация | JWT refresh rotation |

### Android Agent
| Компонент | Технология |
|-----------|------------|
| Язык | Kotlin (compileSdk 35, minSdk 26) |
| DI | Hilt (Dagger) + WorkManager |
| Стриминг | MediaProjection + MediaCodec (H.264) |
| VPN | AmneziaWG (wg-quick) |
| Транспорт | OkHttp3 WebSocket |
| Discovery | CloneDetector (SHA-256 fingerprint) + ZeroTouchProvisioner |
| Resilience | ConfigWatchdog (Git config polling) + ServiceWatchdog (AlarmManager) + Circuit Breaker hook |

### Инфраструктура
| Компонент | Технология |
|-----------|------------|
| Reverse Proxy | nginx (TLS termination, rate limiting) |
| Контейнеры | Docker Compose V2 |
| CI/CD | GitHub Actions |
| Мониторинг | Prometheus + Grafana + Alertmanager |

---

## Документация

| Документ | Описание |
|----------|----------|
| [Архитектура](docs/architecture.md) | Дизайн системы, потоки данных, компонентные диаграммы |
| [API Reference](docs/api-reference.md) | REST-эндпоинты, схемы запросов/ответов |
| [Deployment Guide](docs/deployment.md) | Docker, продакшн, staging, масштабирование |
| [Конфигурация](docs/configuration.md) | Справочник всех переменных окружения |
| [Безопасность](docs/security.md) | Auth, RBAC, шифрование, модель угроз |
| [Developer Guide](docs/development.md) | Локальная настройка, тестирование, стандарты кода |
| [Android Agent](docs/android-agent.md) | Сборка APK, развёртывание, обновления |
| [PC Agent](docs/pc-agent.md) | Установка, ADB-мост, интеграция с LDPlayer |
| [Agent Config](agent-config/README.md) | Конфигурационный репозиторий zero-touch provisioning |
| [TZ-12 Orchestrator](TZ-12-Orchestrator/) | Pipeline Engine, Scheduler, Event Model (5 SPLITs) |
| [ADR](docs/adr/) | Architecture Decision Records |
| [Runbooks](docs/runbooks/) | Процедуры реагирования на инциденты |
| [Contributing](CONTRIBUTING.md) | Руководство по контрибуции, стратегия ветвления |
| [Security Policy](SECURITY.md) | Процесс отчёта об уязвимостях |
| [Changelog](CHANGELOG.md) | История релизов |

---

## Разработка

Подробности — в [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
# Форк, клонирование, создание ветки
git checkout -b feat/SPHERE-XXX-short-description

# Установка pre-commit хуков
pre-commit install

# Запуск тестов перед пушем
cd backend && pytest -x
```

---

## Лицензия

Проект лицензирован под MIT License — см. [LICENSE](LICENSE).
