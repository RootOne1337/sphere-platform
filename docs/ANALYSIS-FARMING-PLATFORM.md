# 🎯 SPHERE PLATFORM — Полный анализ возможностей для игрового фарминга

> **Дата:** 2025-06  
> **Версия платформы:** v0.x (pre-release, ~120 API endpoints, 23 таблицы БД)  
> **Анализируемые слои:** Android Agent (APK), Backend (FastAPI), Frontend (Next.js), PC Agent (Python), DAG Engine, Pipeline Orchestrator, WebSocket, Redis, PostgreSQL  
> **Цель:** Определить что **фундаментально существует** и что **критически отсутствует** для полноценного автоматизированного фарминга игровых аккаунтов (Black Russia, GTA5RP и др.)

---

## Содержание

1. [Архитектура платформы](#1-архитектура-платформы)
2. [Android Agent — Движок автоматизации](#2-android-agent--движок-автоматизации)
3. [XPath-движок и UI-поиск](#3-xpath-движок-и-ui-поиск)
4. [DAG-скрипты и Lua-движок](#4-dag-скрипты-и-lua-движок)
5. [WebSocket-протокол и обратная связь](#5-websocket-протокол-и-обратная-связь)
6. [Модель данных — Существующие таблицы](#6-модель-данных--существующие-таблицы)
7. [Pipeline Orchestrator (TZ-12)](#7-pipeline-orchestrator-tz-12)
8. [Система расписаний (Schedules)](#8-система-расписаний-schedules)
9. [PC Agent — Управление эмуляторами](#9-pc-agent--управление-эмуляторами)
10. [Что СУЩЕСТВУЕТ — полная карта](#10-что-существует--полная-карта)
11. [Что ОТСУТСТВУЕТ — критические пробелы](#11-что-отсутствует--критические-пробелы)
12. [Детект банов и капчи](#12-детект-банов-и-капчи)
13. [Регистрация аккаунтов](#13-регистрация-аккаунтов)
14. [Привязка аккаунт ↔ эмулятор](#14-привязка-аккаунт--эмулятор)
15. [Спецификации TZ-12 SPLIT-3 — Что запроектировано](#15-спецификации-tz-12-split-3--что-запроектировано)
16. [Frontend — Страницы и компоненты](#16-frontend--страницы-и-компоненты)
17. [Итоговая матрица готовности](#17-итоговая-матрица-готовности)
18. [Рекомендации по приоритезации внедрения](#18-рекомендации-по-приоритезации-внедрения)

---

## 1. Архитектура платформы

### Общая диаграмма

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SPHERE PLATFORM                              │
│                                                                     │
│  ┌─────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────┐ │
│  │ Frontend │──▷│    Nginx     │──▷│   Backend    │──▷│PostgreSQL│ │
│  │ Next.js  │   │  80/443/TLS  │   │   FastAPI    │   │  :5432   │ │
│  │  :3000   │   └──────────────┘   │   :8000      │   └──────────┘ │
│  └─────────┘          │            │              │   ┌──────────┐ │
│                       │            │  ┌──────┐    │──▷│  Redis   │ │
│  ┌─────────┐          │            │  │ WS   │    │   │  :6379   │ │
│  │   n8n   │──────────┘            │  │Hub   │    │   └──────────┘ │
│  │  :5678  │                       │  └──┬───┘    │   ┌──────────┐ │
│  └─────────┘                       │     │        │──▷│  MinIO   │ │
│                                    └─────┼────────┘   │ :9000    │ │
│                                          │            └──────────┘ │
│  ┌──────────────────────┐               │                          │
│  │      PC Agent        │       WebSocket (wss://)                 │
│  │  ┌────────────────┐  │               │                          │
│  │  │ LDPlayer CLI   │  │◁──────────────┤                          │
│  │  │ ADB Bridge     │  │               │                          │
│  │  │ Telemetry      │  │               │                          │
│  │  └────────────────┘  │               │                          │
│  └──────────────────────┘               │                          │
│                                          │                          │
│  ┌────────────────────────────────────┐  │                          │
│  │    Android Agent (APK x N)         │  │                          │
│  │  ┌────────────┐ ┌──────────────┐   │  │                          │
│  │  │ DagRunner  │ │ WS Client    │◁──┼──┘                          │
│  │  │ LuaEngine  │ │ Auth/JWT     │   │                             │
│  │  │ AdbExecutor│ │ Heartbeat    │   │                             │
│  │  │ ScriptCache│ │ PendingQueue │   │                             │
│  │  └────────────┘ └──────────────┘   │                             │
│  └────────────────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
```

### Компоненты и технологии

| Компонент | Технология | Назначение |
|-----------|-----------|------------|
| **Backend** | FastAPI + SQLAlchemy 2.0 + Alembic | REST API (~120 endpoints), WebSocket hub |
| **Frontend** | Next.js 15 + Turbopack + shadcn/ui | Дашборд, управление флотом, редактор скриптов |
| **Android Agent** | Kotlin + OkHttp + LuaJ | Исполнитель DAG на эмуляторе |
| **PC Agent** | Python + asyncio + websockets | Управление LDPlayer, ADB мост, телеметрия |
| **PostgreSQL 15** | Основная БД | 23 таблицы, JSONB, UUID PK |
| **Redis 7.2** | Кеш + PubSub + очередь | Статусы устройств, task queue (ZSet), PubSub для команд |
| **Nginx** | Reverse proxy + TLS | SSL termination, WS proxy |
| **n8n** | No-code workflows | Webhook триггеры, кастомные сценарии |
| **MinIO** | S3-совместимое хранилище | Скриншоты, логи, артефакты |

---

## 2. Android Agent — Движок автоматизации

### Структура APK

```
android/app/src/main/kotlin/com/sphereplatform/agent/
├── commands/
│   ├── AdbActionExecutor.kt    ← Исполнитель: tap, swipe, type, xpath
│   ├── DagRunner.kt            ← Движок DAG: 25+ типов действий
│   ├── CommandDispatcher.kt    ← Маршрутизатор команд WS → Executor
│   ├── ScriptCacheManager.kt   ← LRU-кеш скриптов (SHA-256)
│   └── model/CommandType.kt    ← Enum: TAP, SWIPE, EXECUTE_DAG, VPN_CONNECT...
├── lua/
│   └── LuaEngine.kt           ← Lua 5.2 sandbox (заблокированы: os, io, debug)
├── ws/
│   └── SphereWebSocketClient.kt ← OkHttp WS + exponential backoff + circuit breaker
├── store/
│   └── AuthTokenStore.kt      ← EncryptedSharedPreferences (AES256-GCM)
├── provisioning/
│   ├── DeviceRegistrationClient.kt ← POST /devices/register
│   └── CloneDetector.kt       ← SHA-256 fingerprint для идентификации клонов
├── providers/
│   ├── DeviceInfoProvider.kt   ← Системная информация (модель, ОС, память)
│   └── DeviceStatusProvider.kt ← Статус: батарея, CPU, RAM, VPN
├── streaming/
│   └── ScreenCaptureService.kt ← H.264 видеопоток (TZ-05)
├── vpn/
│   ├── SphereVpnManager.kt    ← AmneziaWG управление
│   └── KillSwitchManager.kt   ← Kill switch при разрыве VPN
├── ota/                        ← OTA-обновления агента
├── service/
│   └── SphereAgentService.kt  ← Foreground service (не убивается ОС)
└── ui/
    └── SetupActivity.kt       ← UI регистрации устройства
```

### Ключевые характеристики

| Параметр | Значение |
|----------|----------|
| Язык | Kotlin |
| WebSocket | OkHttp 4.x, RFC 6455 |
| Авторизация | JWT (first-message auth после `onOpen`) |
| Reconnect | Exponential backoff: 1s→2s→4s→8s→16s→30s |
| Circuit breaker | 10 ошибок подряд → 60 сек пауза |
| Heartbeat | Ping каждые 15 сек + watchdog 90 сек |
| Шифрование локальных данных | AES256-GCM (EncryptedSharedPreferences) |
| DAG лимиты | 500 нод, 500 хопов, глубина 10 |
| Lua таймаут | 30 сек на блокирующие операции |
| Кеш скриптов | LRU, 50 макс, content-addressable (SHA-256) |
| Pending results (offline) | Сохранение в SharedPrefs → flush при reconnect |

---

## 3. XPath-движок и UI-поиск

### ✅ РЕАЛИЗОВАНО — Полная поддержка XPath 1.0

**Файл:** `android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt`

#### Механизм работы

```
1. Агент выполняет: uiautomator dump /sdcard/sphere_ui_dump.xml
2. Считывает XML через: cat /sdcard/sphere_ui_dump.xml
3. Парсит через javax.xml.xpath.XPath (Java стандарт)
4. Находит элемент → возвращает координаты центра (bounds)
5. Если не найден — возвращает null (для DAG: on_failure ветка)
```

#### Стратегии поиска

| Стратегия | Код | Пример |
|-----------|-----|--------|
| `xpath` | javax.xml.xpath (полный XPath 1.0) | `//android.widget.Button[@text='Login']` |
| `text` | Быстрый поиск по `@text` | `Login` |
| `id` | Поиск по `@resource-id` | `com.example:id/btn_login` |
| `desc` | Поиск по `@content-desc` | `Login button` |
| `class` | Поиск по `@class` | `android.widget.EditText` |

#### Возможности XPath

```xpath
# Простой поиск кнопки по тексту
//android.widget.Button[@text='Войти']

# Содержание текста (contains)
//android.widget.TextView[contains(@text, 'Баланс')]

# Поиск по нескольким атрибутам
//android.widget.EditText[@resource-id='com.blackrussia:id/login' and @enabled='true']

# Позиционный поиск (второй элемент)
//android.widget.ListView/android.widget.TextView[2]

# Последний элемент
//android.widget.ListView/android.widget.TextView[last()]

# Иерархический поиск
//android.widget.LinearLayout/android.widget.Button[@clickable='true']
```

#### Защиты

| Защита | Значение | Назначение |
|--------|----------|------------|
| Таймаут uiautomator dump | 4 сек | Не зависает на тяжёлых UI |
| Размер XML | ≤ 512 KB | Защита от OOM |
| Zombie cleanup | `killall uiautomator` | Убивает зомби-процессы |

#### Может ли APK находить элементы и отправлять результат?

**ДА, полностью.** Цепочка:

```
DAG node (find_element) → AdbActionExecutor.findElement() → XPath parse
  → результат (bounds, text, id) → сохраняется в DAG context
  → доступен в следующих нодах через ctx.{node_id}
  → отправляется на сервер через task_progress / command_result
```

---

## 4. DAG-скрипты и Lua-движок

### Формат DAG

```json
{
  "entry_node": "start",
  "timeout_ms": 300000,
  "nodes": [
    {
      "id": "start",
      "action": { "type": "launch_app", "package": "com.blackrussia" },
      "on_success": "wait_loaded",
      "on_failure": null,
      "retry": 2,
      "timeout_ms": 10000
    },
    {
      "id": "wait_loaded",
      "action": {
        "type": "tap_element",
        "selector": "//android.widget.Button[@text='Играть']",
        "strategy": "xpath",
        "timeout_ms": 15000
      },
      "on_success": "check_ban",
      "on_failure": "handle_crash"
    }
  ]
}
```

### Полный список действий DAG (25+)

#### Базовые взаимодействия

| Действие | Параметры | Описание |
|----------|-----------|----------|
| `tap` | `x, y` | Тап по координатам |
| `swipe` | `x1, y1, x2, y2, duration_ms` | Свайп |
| `type_text` | `text` | Ввод текста (clipboard-based, UTF-8 + emoji) |
| `key_event` | `keyCode` | Аппаратная кнопка (BACK, HOME, ENTER) |
| `screenshot` | — | Сохранение скриншота на устройство |
| `sleep` | `delay_ms` | Задержка |
| `long_press` | `x, y, duration_ms` | Долгое нажатие |
| `double_tap` | `x, y` | Двойной тап |
| `scroll` | `direction, percent, duration_ms` | Прокрутка (up/down/left/right) |
| `scroll_to` | `selector, strategy, direction` | Скроллить пока не найдёт элемент |
| `input_clear` | — | Очистить текущее поле ввода |

#### Работа с элементами UI

| Действие | Параметры | Описание |
|----------|-----------|----------|
| `tap_element` | `selector, strategy, timeout_ms` | Найти элемент по XPath/text/id → тап |
| `find_element` | `selector, strategy, timeout_ms` | Найти элемент → вернуть bounds |
| `get_element_text` | `selector, attribute` | Извлечь текст/атрибут элемента |
| `find_first_element` | `candidates[]` | Мультипоиск: вернуть первый найденный |
| `wait_for_element_gone` | `selector, strategy, timeout_ms` | Ждать пока элемент исчезнет |

#### Управление переменными (контекст DAG)

| Действие | Параметры | Описание |
|----------|-----------|----------|
| `set_variable` | `key, value` | Установить переменную в контексте |
| `get_variable` | `key` | Получить переменную |
| `increment_variable` | `key, step` | Инкременировать переменную |

#### Логика и контроль

| Действие | Параметры | Описание |
|----------|-----------|----------|
| `condition` | `test_code, on_true, on_false` | Ветвление (if/else) |
| `loop` | `body, condition, max_iterations` | Цикл с условием |
| `assert` | `check, params` | Проверка (элемент есть/нет, текст содержит) |

#### Системные и сетевые

| Действие | Параметры | Описание |
|----------|-----------|----------|
| `launch_app` | `package` | Запустить приложение |
| `stop_app` | `package` | Остановить приложение |
| `clear_app_data` | `package` | Очистить данные приложения |
| `open_url` | `url` | Открыть URL в браузере |
| `http_request` | `url, method, body, headers, timeout_ms` | HTTP запрос с сохранением ответа |
| `get_device_info` | — | Получить JSON с информацией об устройстве |
| `shell` | `command` | Выполнить shell-команду |

#### Lua-блоки

| Действие | Параметры | Описание |
|----------|-----------|----------|
| `lua` | `code` | Выполнить Lua-скрипт в песочнице |

### Lua Engine — Песочница

**Файл:** `android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaEngine.kt`

#### Заблокированные модули (security sandbox)

```
❌ luajava, os, io, require, dofile, debug, package
❌ load, loadstring, coroutine, getmetatable
```

#### Доступные функции в Lua

```lua
-- Взаимодействие с UI
tap(x, y)
swipe(x1, y1, x2, y2)
type_text(text)
key_event(keyCode)
screenshot()
sleep(ms)

-- Логирование
log(message)

-- Контекст DAG (результаты предыдущих нод)
local result = ctx.previous_node_id
```

#### Пример Lua в DAG

```json
{
  "id": "check_balance",
  "action": {
    "type": "lua",
    "code": "local balance_text = ctx.get_balance_text; if balance_text then local num = tonumber(balance_text:match('(%d+)')); if num and num > 10000 then return 'rich' else return 'poor' end end"
  },
  "on_success": "decide_next",
  "on_failure": "error_handler"
}
```

### Per-node Retry

- Exponential backoff: 50ms → 150ms → 450ms → 5000ms
- Конфигурируется на уровне каждой ноды (`"retry": 3`)

---

## 5. WebSocket-протокол и обратная связь

### Типы сообщений

#### Агент → Сервер

| Тип | Формат | Назначение | Данные |
|-----|--------|-----------|--------|
| `pong` | JSON | Heartbeat ответ | `battery, cpu, ram, vpn_active` |
| `telemetry` | JSON | Полная телеметрия | `battery, cpu, ram, screen_on, vpn_active` |
| `task_progress` | JSON | Прогресс DAG | `task_id, nodes_done, total_nodes, current_node` |
| `command_result` | JSON | Результат задачи | `command_id, status, result, error` |
| `event` | JSON | Событие устройства | `event_name, data` |
| Binary | H.264 NAL | Видеопоток | 14-byte header + H.264 frames |

#### Сервер → Агент

| Тип | Формат | Назначение |
|-----|--------|-----------|
| `ping` | JSON | Heartbeat запрос (`ts`) |
| `EXECUTE_DAG` | JSON | Запустить DAG-скрипт |
| `PAUSE_DAG` | JSON | Приостановить DAG |
| `RESUME_DAG` | JSON | Возобновить DAG |
| `start_stream` | JSON | Начать видеостриминг |
| `stop_stream` | JSON | Остановить видеостриминг |
| `request_keyframe` | JSON | Запросить I-frame |
| `screenshot` | JSON | Сделать скриншот |

### Структура command_result (от агента)

```json
{
  "command_id": "uuid",
  "type": "command_result",
  "status": "completed | failed | timeout",
  "result": {
    "success": true,
    "output": "...",
    "execution_time_ms": 5234,
    "node_results": [
      {
        "node_id": "find_login_btn",
        "status": "success",
        "output": {"bounds": [100, 200, 300, 250], "text": "Войти"},
        "duration_ms": 234
      }
    ]
  },
  "error": null
}
```

### Redis PubSub каналы

| Канал | Тип | Назначение | TTL |
|-------|-----|-----------|-----|
| `sphere:agent:cmd:{device_id}` | PubSub | Команды к агенту | — |
| `sphere:org:events:{org_id}` | PubSub | Broadcast событий организации | — |
| `sphere:stream:video:{device_id}` | PubSub | Видеопоток | — |
| `device:status:{device_id}` | String (msgpack) | Live статус устройства | 120s |
| `task:queue:{org_id}` | ZSet | Очередь задач (по приоритету) | — |
| `task_progress:{task_id}` | Hash | Кеш прогресса | 10 мин |

---

## 6. Модель данных — Существующие таблицы

### Полный перечень (23 таблицы)

| № | Таблица | Тип | Назначение |
|---|---------|-----|-----------|
| 1 | `organizations` | Корневая | Мульти-тенантность |
| 2 | `users` | Auth | Пользователи (email, role, MFA) |
| 3 | `api_keys` | Auth | API-ключи для агентов и интеграций |
| 4 | `refresh_tokens` | Auth | JWT refresh-токены |
| 5 | `audit_logs` | Security | Неизменяемый лог действий |
| 6 | `workstations` | Infra | PC-хосты (hostname, OS, IP) |
| 7 | `ldplayer_instances` | Infra | Эмуляторы на воркстанциях (index, ADB port) |
| 8 | `devices` | Core | Устройства/эмуляторы (serial, tags, status) |
| 9 | `device_groups` | Core | Группы устройств (иерархия, цвет) |
| 10 | `device_group_members` | M2M | Устройство ↔ группа |
| 11 | `locations` | Core | Физические локации (координаты) |
| 12 | `device_location_members` | M2M | Устройство ↔ локация |
| 13 | `vpn_peers` | Network | WireGuard/AmneziaWG пиры |
| 14 | `scripts` | Automation | Контейнер скрипта (name, current_version) |
| 15 | `script_versions` | Automation | Версии DAG (append-only, immutable) |
| 16 | `tasks` | Execution | Задачи (status, result, device_id, script_id) |
| 17 | `task_batches` | Execution | Пакетные запуски (wave_config) |
| 18 | `pipelines` | Orchestration | Шаблоны pipeline (steps, input_schema) |
| 19 | `pipeline_runs` | Orchestration | Запущенные инстансы pipeline |
| 20 | `pipeline_batches` | Orchestration | Массовые запуски pipeline |
| 21 | `schedules` | Orchestration | Cron/Interval/OneShot расписания |
| 22 | `schedule_executions` | Orchestration | Лог срабатываний расписания |
| 23 | `webhooks` | Integration | Webhook подписки (HMAC-SHA256) |

### Ключевая модель — `devices`

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | UUID | PK |
| `org_id` | UUID | FK → organizations |
| `name` | VARCHAR(255) | Имя устройства |
| `serial` | VARCHAR(100) | ADB serial |
| `android_version` | VARCHAR(50) | Версия ОС |
| `model` | VARCHAR(255) | Модель устройства |
| `tags` | ARRAY(String) | Теги для фильтрации |
| `is_active` | BOOL | Активно в использовании |
| `last_status` | ENUM | ONLINE / OFFLINE / BUSY / ERROR / MAINTENANCE |
| `meta` | JSONB | Произвольные метаданные |
| `notes` | TEXT | Заметки оператора |

### Ключевая модель — `tasks`

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | UUID | PK |
| `device_id` | UUID | FK → devices |
| `script_id` | UUID | FK → scripts |
| `batch_id` | UUID | FK → task_batches (nullable) |
| `status` | ENUM | QUEUED / ASSIGNED / RUNNING / COMPLETED / FAILED / TIMEOUT / CANCELLED |
| `priority` | INT | 1=highest, 5=default, 10=lowest |
| `input_params` | JSONB | Параметры скрипта |
| `result` | JSONB | Результат выполнения (вкл. node_results) |
| `error_message` | VARCHAR(2048) | Ошибка |
| `timeout_seconds` | INT | Default 300 |

---

## 7. Pipeline Orchestrator (TZ-12)

### Концепция

Pipeline = шаблон оркестрации (как Docker Image).  
PipelineRun = запущенный инстанс (как Docker Container).

### Типы шагов Pipeline

| Тип | Описание | Реализация |
|-----|----------|-----------|
| `execute_script` | Запустить DAG, дождаться результата | ✅ Реализовано |
| `condition` | Проверка: `ctx.login_result == "success"` | ✅ Реализовано |
| `action` | Серверное действие (HTTP, update контекста) | ✅ Реализовано |
| `delay` | Пауза (ms) | ✅ Реализовано |
| `wait_for_event` | Ждать событие агента с таймаутом | ⚠️ Частично (нет event reactor) |
| `n8n_workflow` | Вызов n8n webhook → результат в контекст | ✅ Реализовано |
| `parallel` | Параллельные подшаги | ✅ Реализовано |
| `loop` | Повтор блока N раз | ✅ Реализовано |
| `sub_pipeline` | Запуск вложенного pipeline | ✅ Реализовано |

### Пример Pipeline для фарминга

```json
{
  "name": "Black Russia — Auto Farm",
  "steps": [
    {
      "id": "assign_account",
      "type": "action",
      "params": { "action": "assign_free_account", "game": "blackrussia" }
    },
    {
      "id": "login",
      "type": "execute_script",
      "params": { "script_name": "BR Login Script" },
      "on_success": "check_login",
      "on_failure": "handle_error"
    },
    {
      "id": "check_login",
      "type": "condition",
      "params": { "expression": "ctx.login.success == true" },
      "on_true": "farm",
      "on_false": "rotate_account"
    },
    {
      "id": "farm",
      "type": "execute_script",
      "params": { "script_name": "BR Farm Loop" }
    },
    {
      "id": "rotate_account",
      "type": "action",
      "params": { "action": "release_account_and_get_next" }
    }
  ]
}
```

### Статусы PipelineRun

```
QUEUED → RUNNING → COMPLETED
              ├──→ PAUSED (ожидание оператора)
              ├──→ WAITING (wait_for_event)
              ├──→ FAILED
              ├──→ CANCELLED
              └──→ TIMED_OUT
```

---

## 8. Система расписаний (Schedules)

### Модель данных

| Поле | Описание |
|------|----------|
| `cron_expression` | Cron: `5,25,45 * * * *` (каждые 20 мин) |
| `interval_seconds` | Интервал: каждые N секунд |  
| `one_shot_at` | Одноразовый запуск |
| `timezone` | IANA: `Europe/Moscow` |
| `target_type` | `script` или `pipeline` |
| `device_ids` | Конкретные UUID устройств |
| `group_id` | Вся группа устройств |
| `device_tags` | По тегам |
| `only_online` | Только online устройства |
| `conflict_policy` | SKIP / QUEUE / CANCEL |
| `active_from/until` | Окно активности |
| `max_runs` | Лимит запусков |

### Диспетчеризация

- DB-backed с `croniter` парсером
- Multi-instance safe через `FOR UPDATE SKIP LOCKED`
- Каждый тик: `schedule_executions` → запись в лог

---

## 9. PC Agent — Управление эмуляторами

### Возможности

| Функция | Команда | Описание |
|---------|---------|----------|
| **LDPlayer Management** | `ld_launch` | Запуск эмулятора по индексу |
| | `ld_quit` | Остановка эмулятора |
| | `ld_reboot` | Перезагрузка |
| | `ld_create` | Создание нового инстанса |
| | `ld_install_apk` | Установка APK |
| | `ld_run_app` | Запуск приложения |
| **ADB Bridge** | `adb_shell` | Выполнить команду на устройстве |
| | `adb_install` | Установить APK через ADB |
| | `adb_push/pull` | Загрузка/выгрузка файлов |
| **Telemetry** | `telemetry` | CPU, RAM, Disk хост-машины |
| **ADB Discovery** | `scan` | Сканирование подсети на ADB порты |
| **Topology** | `register` | Регистрация инстансов при подключении |

### Архитектура подключения

```
                          ┌──────────────┐
                   ┌──────│  Workstation  │──────┐
                   │      │  PC Agent     │      │
                   │      └──────┬───────┘       │
                   │             │               │
           ┌───────┴───────┐    │    ┌───────┴───────┐
           │ LDPlayer #0   │    │    │ LDPlayer #1   │
           │ (emulator:0)  │    │    │ (emulator:1)  │
           │ → APK Agent   │    │    │ → APK Agent   │
           │ → WebSocket   │    │    │ → WebSocket   │
           └───────────────┘    │    └───────────────┘
                                │
                         WebSocket к Backend
```

---

## 10. Что СУЩЕСТВУЕТ — полная карта

### ✅ Инфраструктура

| Функция | Файл / Компонент | Статус |
|---------|-------------------|--------|
| Docker Compose (dev + prod) | `docker-compose*.yml` | ✅ |
| PostgreSQL 15 с 23 таблицами | `alembic/versions/` | ✅ |
| Redis 7.2 PubSub + Task Queue | `backend/websocket/channels.py` | ✅ |
| Nginx reverse proxy + TLS | `infrastructure/nginx.conf` | ✅ |
| MinIO (S3-совместимое) | `docker-compose.yml` | ✅ |
| Prometheus метрики | `backend/metrics.py` | ✅ |

### ✅ Android Agent (APK)

| Функция | Реализация | Статус |
|---------|-----------|--------|
| XPath 1.0 поиск элементов | `AdbActionExecutor.kt` | ✅ |
| 25+ типов действий DAG | `DagRunner.kt` | ✅ |
| Lua 5.2 sandbox | `LuaEngine.kt` | ✅ |
| WebSocket + JWT auth | `SphereWebSocketClient.kt` | ✅ |
| Heartbeat + circuit breaker | `CommandDispatcher.kt` | ✅ |
| Pending results (offline) | `DagRunner.kt` | ✅ |
| Content-addressable script cache | `ScriptCacheManager.kt` | ✅ |
| AmneziaWG VPN | `SphereVpnManager.kt` | ✅ |
| H.264 видеостриминг | `ScreenCaptureService.kt` | ✅ |
| OTA-обновления | `ota/` | ✅ |
| Clone detection (fingerprint) | `CloneDetector.kt` | ✅ |
| Device registration | `DeviceRegistrationClient.kt` | ✅ |

### ✅ Backend API

| Функция | Эндпоинт | Статус |
|---------|----------|--------|
| Одиночная задача | `POST /tasks` | ✅ |
| Пакетный запуск | `POST /batches` | ✅ |
| Broadcast на все online | `POST /batches/broadcast` | ✅ |
| Wave батч (с задержкой) | Конфиг `wave_config` | ✅ |
| Pipeline CRUD | `POST/GET/PATCH /pipelines` | ✅ |
| Pipeline запуск | `POST /pipelines/{id}/runs` | ✅ |
| Schedule CRUD | `POST/GET/PATCH/DELETE /schedules` | ✅ |
| Schedule toggle | `POST /schedules/{id}/toggle` | ✅ |
| Webhook подписки | `POST/GET/PATCH /webhooks` | ✅ |
| Device CRUD | Полный REST | ✅ |
| Script versioning | `POST /scripts/{id}/versions` | ✅ |
| Скриншот устройства | `POST /devices/{id}/screenshot` | ✅ |

### ✅ Frontend

| Страница | Путь | Существует |
|----------|------|-----------|
| Dashboard | `/dashboard` | ✅ |
| Fleet (группы) | `/fleet` | ✅ |
| Stream (видео) | `/stream` | ✅ |
| Tasks | `/tasks` | ✅ |
| Orchestration (Pipelines + Schedules) | `/orchestration` | ✅ |
| Scripts | `/scripts` | ✅ |
| Script Builder (DAG) | `/scripts/builder` | ✅ |
| Monitoring | `/monitoring` | ✅ |
| Locations | `/locations` | ✅ |
| Discovery | `/discovery` | ✅ |
| VPN | `/vpn` | ✅ |
| Users (RBAC) | `/users` | ✅ |
| Audit Log | `/logs` | ✅ |
| Webhooks | `/webhooks` | ✅ |
| Settings | `/settings` | ✅ |

---

## 11. Что ОТСУТСТВУЕТ — критические пробелы

### 🔴 Таблица `game_accounts` — НЕ СУЩЕСТВУЕТ

Это **главный блокирующий фактор** для полноценного фарминга. В БД нет ни одной таблицы, связанной с игровыми аккаунтами.

**Что нужно:**

```
game_accounts
├── org_id (FK → organizations)
├── game_id (str: "blackrussia", "gta5rp")
├── login (str, unique per org+game)
├── password_encrypted (bytes, AES-256-GCM)
├── status (ENUM: IDLE, IN_USE, BANNED, SUSPENDED, CAPTCHA, COOLDOWN, ERROR, RETIRED)
├── status_reason (str | null)
├── status_changed_at (datetime)
├── device_id (FK → devices, nullable — если IN_USE)
├── assigned_at (datetime | null)
├── level (int | null — уровень в игре)
├── balance (float | null — баланс в игре)
├── last_balance_update (datetime | null)
├── total_bans (int, default 0)
├── last_ban_at (datetime | null)
├── ban_reason (str | null)
├── total_sessions (int, default 0)
├── last_session_end (datetime | null)
├── cooldown_until (datetime | null)
├── meta (JSONB — сервер, персонаж, дополнительные данные)
├── created_at, updated_at
```

**Индексы:**
```sql
INDEX ix_game_accounts_org_game_status (org_id, game_id, status)
INDEX ix_game_accounts_device_id (device_id)
INDEX ix_game_accounts_cooldown_until (cooldown_until) WHERE cooldown_until IS NOT NULL
```

### 🔴 Таблица `account_sessions` — НЕ СУЩЕСТВУЕТ

**Что нужно:**

```
account_sessions
├── account_id (FK → game_accounts)
├── device_id (FK → devices)
├── org_id (FK → organizations)
├── started_at (datetime)
├── ended_at (datetime | null)
├── success (bool)
├── nodes_executed (int)
├── errors_count (int)
├── script_id (FK → scripts, nullable)
├── task_id (FK → tasks, nullable)
├── error_reason (str | null)
├── meta (JSONB — дополнительные данные сессии)
```

### 🔴 Таблица `device_events` — НЕ СУЩЕСТВУЕТ

**Что нужно:** Персистентное хранилище событий от агентов.

```
device_events
├── device_id (FK → devices)
├── org_id (FK → organizations)
├── event_type (str: "account.banned", "account.captcha", "game.crashed", "app.error")
├── severity (ENUM: DEBUG, INFO, WARNING, ERROR)
├── data (JSONB — payload события)
├── task_id (FK → tasks, nullable)
├── account_id (FK → game_accounts, nullable)
├── created_at (datetime)
```

### 🔴 Сервис `AccountService` — НЕ СУЩЕСТВУЕТ

Нужен сервис для управления жизненным циклом аккаунтов:

- `assign_account(device_id, game_id)` → возвращает IDLE аккаунт
- `release_account(account_id)` → IDLE + cooldown
- `ban_account(account_id, reason)` → BANNED
- `rotate_account(device_id, game_id)` → release текущий + assign новый
- `import_accounts(csv/json)` → массовый импорт
- `get_stats(game_id)` → статистика по статусам

### 🔴 API `/api/v1/accounts/*` — НЕ СУЩЕСТВУЕТ

Нужны эндпоинты:

```
GET    /accounts                    # Список с фильтрацией
GET    /accounts/{id}               # Детали аккаунта
POST   /accounts                    # Создание
PATCH  /accounts/{id}               # Обновление
DELETE /accounts/{id}               # Удаление (soft)
POST   /accounts/import             # Массовый импорт
POST   /accounts/{id}/assign        # Привязка к устройству
POST   /accounts/{id}/release       # Отвязка
GET    /accounts/stats              # Статистика
GET    /accounts/{id}/sessions      # История сессий
```

### 🔴 Frontend страница Accounts — НЕ СУЩЕСТВУЕТ

Нет UI для управления игровыми аккаунтами.

### 🔴 Event Reactor — НЕ ЗАВЕРШЁН

Pipeline поддерживает `wait_for_event` шаг, но полноценный Event Reactor (реакция на события от агента: бан, капча, вылет) не доработан. Без таблицы `game_accounts` автоматическая ротация аккаунтов невозможна.

---

## 12. Детект банов и капчи

### Текущее состояние: ❌ НЕТ встроенной логики

В Android Agent **нет** встроенного детектирования банов, капч или других игровых событий. Агент — это универсальный исполнитель DAG, он не знает о "банах" или "капчах".

### Как это работает СЕЙЧАС (ручная реализация через DAG)

```json
{
  "id": "check_ban_popup",
  "action": {
    "type": "find_element",
    "selector": "//android.widget.TextView[contains(@text, 'заблокирован')]",
    "strategy": "xpath",
    "timeout_ms": 3000
  },
  "on_success": "handle_ban",
  "on_failure": "continue_game"
}
```

Проблема: это требует написания XPath-проверок вручную для каждой игры. Нет стандартизации.

### Что НУЖНО по спецификации (TZ-12 SPLIT-3)

1. **Агент отправляет событие** через WebSocket:
   ```json
   {"type": "event", "event_name": "account.banned", "data": {"reason": "Текст бана"}}
   ```

2. **Бэкенд сохраняет** в `device_events` таблицу

3. **Event Reactor** реагирует:
   - `account.banned` → стоп скрипт → `GameAccount.status = BANNED` → ротация
   - `account.captcha` → пауза → алерт оператору
   - `game.crashed` → перезапуск приложения → retry

4. **n8n триггер** для кастомных сценариев

---

## 13. Регистрация аккаунтов

### Регистрация УСТРОЙСТВА на сервер — ✅ СУЩЕСТВУЕТ

```kotlin
// DeviceRegistrationClient.kt
suspend fun register(
    serverUrl: String,
    enrollmentApiKey: String,
    workstationId: String? = null,
    instanceIndex: Int? = null,
    location: String? = null
): RegistrationResult  // deviceId, accessToken, refreshToken
```

### Регистрация ИГРОВЫХ аккаунтов — ❌ НЕ СУЩЕСТВУЕТ

Нет встроенной автоматизации создания игровых аккаунтов. Может быть реализована через DAG:

```json
[
  {"id": "open_game", "action": {"type": "launch_app", "package": "com.blackrussia"}},
  {"id": "tap_register", "action": {"type": "tap_element", "selector": "//Button[@text='Регистрация']", "strategy": "xpath"}},
  {"id": "enter_email", "action": {"type": "type_text", "text": "user123@gmail.com"}},
  {"id": "enter_password", "action": {"type": "type_text", "text": "SecurePass123!"}},
  {"id": "confirm", "action": {"type": "tap_element", "selector": "//Button[@text='Создать']", "strategy": "xpath"}},
  {"id": "save_result", "action": {"type": "http_request", "method": "POST", "url": "https://sphere-server/api/v1/accounts", "body": "{...}"}}
]
```

**Проблемы:**
- Нет эндпоинта `/api/v1/accounts` для сохранения
- Нет модели `GameAccount` для хранения
- Нет автогенерации email/пароля на стороне сервера
- Нет интеграции с сервисами временной почты / SMS

---

## 14. Привязка аккаунт ↔ эмулятор

### Текущее состояние: ❌ НА УРОВНЕ БД НЕТ

**Существует на устройстве:**
- `AuthTokenStore` хранит `device_id` + JWT (авторизация устройства на сервере)
- `CloneDetector` создаёт уникальный `fingerprint` (`SHA-256(app_instance_id + android_id + build_fingerprint + ...)`)
- Связь `ldplayer_instances.device_id → devices.id` (один к одному)

**НЕ существует:**
- Связь `game_account.device_id → devices.id` (аккаунт привязан к эмулятору)
- Сервис назначения/освобождения аккаунтов
- Cooldown после использования аккаунта
- Ротация при бане

### Как ДОЛЖНО работать

```
Пул аккаунтов (game_accounts)           Флот устройств (devices)
┌──────────────┐                        ┌──────────────┐
│ acc_001 IDLE │──── assign ──────────▷ │ device_a     │
│ acc_002 IN_USE │───────────────────▷  │ device_b     │
│ acc_003 BANNED │                      │ device_c     │ (свободен)
│ acc_004 COOLDOWN │                    │ device_d     │ (свободен)
│ acc_005 IDLE │                        └──────────────┘
└──────────────┘

Ротация:
1. acc_002 → BANNED (событие от агента)
2. acc_002.device_id = NULL, acc_002.status = BANNED
3. acc_005 (IDLE) → assign → device_b
4. acc_005.device_id = device_b, acc_005.status = IN_USE
```

---

## 15. Спецификации TZ-12 SPLIT-3 — Что запроектировано

### Спецификация описывает, но НЕ реализовано

| Сущность | Описание | Реализация |
|----------|----------|-----------|
| `GameAccount` модель | Полная модель с status, device_id, level, balance, bans | ❌ |
| `AccountStatus` enum | IDLE, IN_USE, BANNED, SUSPENDED, CAPTCHA, COOLDOWN, ERROR, RETIRED | ❌ |
| `DeviceEvent` модель | Персистентное хранилище событий | ❌ |
| `AccountService` | assign, release, rotate, import | ❌ |
| `EventReactor` | Автоматическая реакция на события | ❌ |
| `AccountSession` | История use-сессий | ❌ |
| API `/accounts/*` | CRUD + операции | ❌ |
| Frontend /accounts | UI управления аккаунтами | ❌ |

### Полный Pipeline для фарминга (из спецификации)

```
Pipeline: "Black Russia Full Farm Cycle"
├─ Step[0]: assign_account        → Выбрать IDLE аккаунт из пула
├─ Step[1]: login_script          → DAG: запуск игры, ввод логин/пароль
├─ Step[2]: check_login           → condition: ctx.login.success?
│   ├─ on_true → Step[3]
│   └─ on_false → Step[7]
├─ Step[3]: farm_script           → DAG: автоматический фарминг
├─ Step[4]: wait_for_event        → Ждать: account.banned / account.level_up / timeout
│   ├─ on: account.banned → Step[7]
│   ├─ on: account.level_up → Step[5]
│   └─ on: timeout(3600s) → Step[6]
├─ Step[5]: log_progress          → action: обновить level/balance в БД
├─ Step[6]: graceful_stop         → DAG: остановить фарм, выход из игры
└─ Step[7]: rotate_and_retry      → action: release_account + assign_next + goto Step[1]
```

---

## 16. Frontend — Страницы и компоненты

### Существующие страницы

| Страница | Путь | Ключевые компоненты |
|----------|------|-------------------|
| Dashboard | `/dashboard` | FleetStats, DeviceDistribution, VPN Health |
| Fleet | `/fleet` | FleetMatrix, DeviceGroupCards |
| Stream | `/stream` | DeviceStream (grid 1x-16x, H.264) |
| Tasks | `/tasks` | TaskGanttChart, TaskTable, BroadcastModal |
| Orchestration | `/orchestration` | PipelineList, PipelineRunsAccordion, SchedulesTab |
| Scripts | `/scripts` | ScriptList, RunScriptModal |
| Script Builder | `/scripts/builder` | ReactFlow DAG editor (TapNode, SwipeNode, LuaNode...) |
| VPN | `/vpn` | PeerList, ThroughputChart, NodeManagement |

### Компоненты DAG (Script Builder)

```
frontend/components/sphere/dag/
├── ConditionNode.tsx    # Ветвление if/else
├── TapNode.tsx          # Тап по координатам/элементу
├── SwipeNode.tsx        # Свайп
├── ScreenshotNode.tsx   # Скриншот
├── SleepNode.tsx        # Задержка
├── StartNode.tsx        # Начальная нода
├── EndNode.tsx          # Конечная нода
└── LuaNode.tsx          # Lua-код
```

### Отсутствующие компоненты

- ❌ `AccountTable.tsx` — таблица аккаунтов с фильтрацией
- ❌ `AccountStatusBadge.tsx` — бейдж статуса (IDLE, IN_USE, BANNED...)
- ❌ `AccountImportDialog.tsx` — массовый импорт аккаунтов
- ❌ `AccountStatsChart.tsx` — графики по статусам
- ❌ `/accounts` страница — вся UI для управления

---

## 17. Итоговая матрица готовности

### ✅ ПОЛНОСТЬЮ ГОТОВО

| Модуль | Компонент | Уровень |
|--------|-----------|---------|
| **Agent XPath** | Поиск элементов по XPath/text/id/desc/class | Продакшн |
| **Agent Actions** | 25+ действий: tap, swipe, type, scroll, lua, http, shell | Продакшн |
| **Agent Feedback** | WebSocket JSON + task_progress + command_result | Продакшн |
| **Agent Security** | JWT auth, AES256 storage, circuit breaker, backoff | Продакшн |
| **Agent DAG** | Полный DAG runner с retry, timeout, variables, routing | Продакшн |
| **Agent Lua** | Lua 5.2 sandbox с таймаутом | Продакшн |
| **Agent Cache** | SHA-256 content-addressable, LRU 50 скриптов | Продакшн |
| **Agent VPN** | AmneziaWG с kill switch | Продакшн |
| **Agent Stream** | H.264 стриминг экрана | Продакшн |
| **Backend Tasks** | Создание, диспетчеризация, результаты, таймауты | Продакшн |
| **Backend Batch** | Wave batch, broadcast, агрегация, jitter | Продакшн |
| **Backend Pipeline** | 9 типов шагов, executor loop, статусы | Продакшн |
| **Backend Schedule** | Cron + Interval + OneShot, device targeting | Продакшн |
| **Backend WebSocket** | PubSub router, connection manager, heartbeat | Продакшн |
| **Backend Webhook** | HMAC-SHA256 подпись, retry, event-driven | Продакшн |
| **Backend Device CRUD** | Полный REST, группы, локации, статусы | Продакшн |
| **Backend Script CRUD** | Версионирование, DAG JSONB хранение | Продакшн |
| **Backend Auth** | JWT + MFA + RBAC + API Keys + Audit Log | Продакшн |
| **Backend VPN** | AmneziaWG peers, health check | Продакшн |
| **PC Agent** | LDPlayer management, ADB bridge, telemetry | Продакшн |
| **Frontend** | 15 страниц, DAG builder, stream grid | Продакшн |

### ⚠️ ЧАСТИЧНО ГОТОВО

| Модуль | Что есть | Что не хватает |
|--------|---------|----------------|
| **Pipeline wait_for_event** | Шаг описан, handler существует | Event Reactor не связан с GameAccount |
| **Device Events** | WebSocket `event` тип существует | Нет персистентной таблицы `device_events` |
| **Batch + Pipeline targeting** | `device_ids`, `group_id` в Schedule и Batch | Нет targeting по аккаунтам |

### 🔴 ПОЛНОСТЬЮ ОТСУТСТВУЕТ

| Модуль | Критичность | Описание |
|--------|------------|----------|
| **Таблица `game_accounts`** | 🔴 БЛОКЕР | Нет БД для хранения аккаунтов |
| **Таблица `account_sessions`** | 🟡 HIGH | Нет истории использования |
| **Таблица `device_events`** | 🔴 БЛОКЕР | Нет персистентного лога событий |
| **AccountService** | 🔴 БЛОКЕР | Нет сервиса assign/release/rotate |
| **API /accounts** | 🔴 БЛОКЕР | Нет REST API для аккаунтов |
| **Event Reactor** | 🔴 БЛОКЕР | Нет автоматической реакции на бан/капчу |
| **Frontend /accounts** | 🟡 HIGH | Нет UI управления аккаунтами |
| **Встроенный ban detect** | 🟡 MEDIUM | Можно через DAG, но нет стандарта |
| **Captcha solver integration** | 🟡 MEDIUM | Нет интеграции с rucaptcha/anticaptcha |
| **Account registration automation** | 🟡 MEDIUM | Нет автогенерации email/SMS |
| **Account analytics** | 🟢 LOW | Зависит от game_accounts |
| **Account export (для продажи)** | 🟢 LOW | Зависит от game_accounts |

---

## 18. Рекомендации по приоритезации внедрения

### Фаза 1 — Фундамент (🔴 БЛОКЕРЫ)

**Без этих компонентов фарминг невозможен на промышленном уровне.**

1. **Alembic миграция + модель `GameAccount`**  
   - Создать `backend/models/game_account.py`
   - Создать Alembic миграцию
   - Enum `AccountStatus` (IDLE, IN_USE, BANNED, SUSPENDED, CAPTCHA, COOLDOWN, ERROR, RETIRED)
   - FK → devices (nullable), FK → organizations
   - Шифрование пароля (Fernet или AES-256-GCM)

2. **`AccountService`**  
   - `assign_account(device_id, game_id)` — взять IDLE → IN_USE
   - `release_account(account_id, reason)` — IN_USE → IDLE/COOLDOWN
   - `ban_account(account_id, reason)` — → BANNED
   - `rotate_account(device_id, game_id)` — release + assign
   - `import_accounts(data)` — массовый импорт

3. **API `/api/v1/accounts/*`**  
   - CRUD + assign/release/rotate + import + stats

4. **Alembic миграция + модель `DeviceEvent`**
   - `backend/models/device_event.py`
   - Персистентное хранилище событий от агентов

### Фаза 2 — Автоматизация (🟡 HIGH)

5. **Event Reactor**  
   - Обработка WebSocket `event` → сохранить в `device_events`
   - Связка event → GameAccount status change
   - Автоматическая ротация при бане

6. **Pipeline integration**  
   - Шаг `assign_account` в step_handlers
   - Шаг `release_account`
   - `wait_for_event` связан с реальными событиями

7. **Frontend `/accounts`**  
   - Таблица аккаунтов с фильтрацией (statuses, game, device)
   - Import/Export dialog
   - Статистика (IDLE/IN_USE/BANNED/COOLDOWN)

8. **Таблица `account_sessions`**  
   - История привязок аккаунт ↔ устройство
   - Длительность, результат, ошибки

### Фаза 3 — Оптимизация (🟡 MEDIUM)

9. **Стандартизация ban/captcha detection**
   - Библиотека шаблонных XPath-проверок для популярных игр
   - Готовые DAG-шаблоны проверки банов

10. **Captcha solver integration**
    - Интеграция с rucaptcha/anticaptcha через `http_request` DAG-нод
    - Pipeline шаг `solve_captcha`

11. **Account registration automation**
    - DAG-шаблоны для регистрации
    - Интеграция с сервисами временной почты / виртуальных номеров

### Фаза 4 — Аналитика и масштаб (🟢 LOW)

12. **Account Analytics Dashboard**
    - Графики: IDLE/IN_USE/BANNED по времени
    - Средний lifetime аккаунта до бана
    - Доход (balance) по аккаунтам

13. **Account Export**
    - Экспорт прокачанных аккаунтов (CSV, JSON)
    - Интеграция с торговыми площадками

14. **Multi-game support**
    - Конфигурации per-game (XPath шаблоны, login flow, ban patterns)

---

> **Итог:** Платформа Sphere имеет **мощнейший фундамент** для автоматизации (XPath, DAG engine, Lua, Pipeline, Schedule, WebSocket, VPN). Но для промышленного фарминга не хватает **одного критического слоя** — управления игровыми аккаунтами (модель `GameAccount`, сервис, API, UI). Это 4-5 файлов кода + 1 миграция. После их создания платформа покроет 95% сценариев автоматизированного фарминга.
