# SPHERE PLATFORM — Саммари-выжимка по возможностям фарминга

> Краткая выжимка из [ANALYSIS-FARMING-PLATFORM.md](ANALYSIS-FARMING-PLATFORM.md)

---

## Что МОЖЕТ делать APK-агент прямо сейчас

- **XPath 1.0** — полная поддержка: `//Button[@text='Войти']`, `contains()`, `last()`, позиции, иерархия
- **25+ действий DAG** — tap, swipe, type_text, long_press, scroll_to, find_element, get_element_text, http_request, shell, lua, condition, loop, assert
- **Lua 5.2** — встроенный движок с sandbox (заблокированы: os, io, debug), доступ к контексту DAG через `ctx`
- **Обратная связь** — WebSocket JSON: `task_progress`, `command_result`, `event`. Результаты каждой ноды DAG возвращаются на сервер
- **Offline-режим** — pending results сохраняются в EncryptedSharedPreferences, отправка при reconnect
- **VPN** — AmneziaWG с kill switch, управление через DAG
- **Скриншоты / видеопоток** — H.264 стриминг (TZ-05)
- **Кеш скриптов** — SHA-256 content-addressable, LRU 50 шт. Экономия 99.8% трафика при повторных запусках

## Что МОЖЕТ делать бэкенд

- **Task system** — создание, диспетчеризация, приоритеты, таймауты, результаты
- **Batch** — wave batch (с волнами + jitter), broadcast на все online устройства
- **Pipeline** — 9 типов шагов (execute_script, condition, action, delay, wait_for_event, n8n_workflow, parallel, loop, sub_pipeline)
- **Schedule** — cron / interval / one-shot, таргетирование по device_ids / group / tags / only_online
- **Webhook** — HMAC-SHA256 подпись, retry, event-driven уведомления
- **Prometheus метрики** — HTTP, WS, devices, tasks, VPN

## Что НЕ СУЩЕСТВУЕТ (критические пробелы)

| Пробел | Критичность | Что нужно создать |
|--------|------------|-------------------|
| Таблица `game_accounts` | 🔴 БЛОКЕР | Модель + Alembic миграция (status, device_id, level, balance, bans) |
| Таблица `device_events` | 🔴 БЛОКЕР | Персистентный лог событий от агента |
| `AccountService` | 🔴 БЛОКЕР | assign/release/rotate/ban/import аккаунтов |
| API `/accounts/*` | 🔴 БЛОКЕР | REST CRUD + операции |
| Event Reactor | 🔴 БЛОКЕР | Автоматическая реакция на бан→ротация |
| Таблица `account_sessions` | 🟡 HIGH | История привязок аккаунт ↔ устройство |
| Frontend `/accounts` | 🟡 HIGH | UI таблица + импорт + статистика |
| Ban/captcha detect библиотека | 🟡 MEDIUM | Шаблоны XPath-проверок для игр |
| Captcha solver | 🟡 MEDIUM | Интеграция rucaptcha/anticaptcha |
| Авто-регистрация аккаунтов | 🟡 MEDIUM | DAG-шаблоны + интеграция email/SMS |

## Объём работы до промышленного фарминга

```
Фаза 1 — Фундамент (4-5 файлов + 1 миграция):
  ├── backend/models/game_account.py
  ├── backend/models/device_event.py
  ├── backend/services/account_service.py
  ├── backend/api/v1/accounts/router.py
  └── alembic/versions/YYYYMMDD_game_accounts.py

Фаза 2 — Автоматизация:
  ├── Event Reactor (обработка событий → смена статуса аккаунта)
  ├── Pipeline step handlers: assign_account, release_account
  ├── frontend/app/(dashboard)/accounts/page.tsx
  └── backend/models/account_session.py

Фаза 3 — Оптимизация:
  ├── Библиотека ban/captcha XPath шаблонов
  ├── Captcha solver integration
  └── Account registration DAG-шаблоны
```

## Главный вывод

Платформа имеет **зрелый фундамент**: XPath-движок, DAG engine с 25+ действиями, Lua, Pipeline orchestrator, Schedule, WebSocket, VPN — всё production-ready. Единственный блокирующий слой — **управление игровыми аккаунтами** (`GameAccount` модель + сервис + API). Это ~5 файлов кода. После их создания покрывается 95% сценариев промышленного фарминга.
