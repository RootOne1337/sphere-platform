# Разработка Sphere

**Сверено 21 сентября 2026.** [Каталог](README.md) · [Contributing](../CONTRIBUTING.md) · [Архитектура](architecture.md)

## Среда

| Компонент | Локальные инструменты | Источник фактических проверок |
| --- | --- | --- |
| Backend / PC-agent | Python 3.12, отдельный virtualenv | [Backend CI](../.github/workflows/ci-backend.yml) |
| Frontend | Node.js 24, npm с lockfile | [Frontend CI](../.github/workflows/ci-frontend.yml) |
| Android | JDK 17, Android SDK, Gradle wrapper | [Android CI](../.github/workflows/ci-android.yml) |
| Runtime regressions | Отдельные PostgreSQL 15 и Redis 7.2 | [Инструкция и защитные ограничения](../tests/production/README.md) |
| Windows deployment | PowerShell 7, Docker Compose v2 | [Startup](operations/STARTUP.md) |

Для production overlay требуется Compose 2.24.4+ из-за `!reset`.
Версии SDK и плагины Android задаются в Gradle, а не устанавливаются произвольно.

## Checkout и первый запуск

```bash
git clone https://github.com/RootOne1337/sphere-platform.git
cd sphere-platform
git switch codex/enterprise-audit-20260905
```

Последняя команда переключает новый checkout на ветку текущего аудита из draft
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19), ветка
`codex/enterprise-audit-20260905`. Выбирайте revision явно; `main` и установленный
pilot могут отличаться.

**Новая установка:** следуйте [порядку bootstrap](operations/STARTUP.md#first-install).
**Готовый pilot:** используйте его [отдельную инструкцию](operations/LOCAL-PILOT.md).
Не объединяйте `full` и `override` Compose recipes и не запускайте миграции без
явного project/env. `start-dev.ps1` предназначен для уже подготовленного стека.

## Backend и PC-agent

```bash
python -m venv .venv
```

Активация: `.venv\Scripts\Activate.ps1` в PowerShell или
`source .venv/bin/activate` в Bash. Из корня репозитория:

```bash
python -m pip install -r backend/requirements.txt -r pc-agent/requirements.txt
python -m pip check
```

Зависимости устанавливаются совместно: последовательная установка скрывала
конфликтующие pins. Для запуска приложения нужны параметры из
[configuration](configuration.md); не берите рабочие secrets для тестов.

| Каталог | Назначение |
| --- | --- |
| `backend/api`, `schemas` | HTTP/WebSocket границы, валидация входа/выхода |
| `backend/services`, `tasks` | Бизнес-правила, оркестрация и фоновые workers |
| `backend/models`, `database`, `alembic/` | Состояние, транзакции, миграции |
| `backend/websocket` | Соединения и доставка событий/команд |
| `backend/core`, `middleware`, `monitoring` | Настройки, identity, контекст и наблюдаемость |

### База и конкурентность

Tenant context привязывается до первого доступа к данным. Одна Session обслуживает
одного tenant; после commit/rollback контекст должен сохраняться корректно.
Для другой организации нужна новая Session. Обычный `get_db()` сам по себе не
доказывает изоляцию. Смотрите [RLS contract](security/postgresql-rls.md),
[user bootstrap](security/user-auth-bootstrap.md) и
[worker RLS](audits/2026-09-20/PIPELINE-RLS.md).

SQLite adapter в тестах не реализует PostgreSQL RLS/locks. Для race, commit-ACK loss,
таймаутов SQL и фоновых workers используйте [runtime regressions](../tests/production/README.md).
Receipt об исполнении, принятие команды транспортом и сохранение результата —
разные события; [task control contract](security/task-control-protocol.md).

### Проверки backend

В отдельном virtualenv для lint установите `ruff` и `mypy`. Основные команды:

```bash
python -m ruff check backend/ tests/ scripts/export_api_docs.py scripts/discovery_manifest.py scripts/discovery_publisher.py scripts/ldplayer_network.py scripts/ldplayer_watchdog.py
python -m mypy backend/ --ignore-missing-imports
python scripts/check_rls.py
```

Для тестов сначала подготовьте **изолированные** PG/Redis, test env и migrations
по [инструкции](../tests/production/README.md), затем используйте команду CI из неё.
Без `SPHERE_RUN_INTEGRATION=1` реальные DB cases пропускаются. Фактический coverage
gate — 65% backend; это не гарантия достаточного покрытия каждого компонента.
`tests/load` не входит в обычную regression suite.

После изменения HTTP routes, в настроенной тестовой среде:

```bash
python -m scripts.export_api_docs
python -m scripts.export_api_docs --check
```

Проверяйте сгенерированный diff [каталога](api-endpoints.md) и [OpenAPI](openapi.json).

## Frontend

В каталоге `frontend`:

```bash
npm ci --ignore-scripts --no-audit --no-fund
npx --no-install jest --ci --runInBand
npm run type-check
npm run build
```

Это команды [текущего CI](../.github/workflows/ci-frontend.yml). Настройка dev proxy
и окружения — в [configuration](configuration.md). UI-изменения проверяйте в браузере:
loading/error/empty, права пользователя, reconnect, отсутствие устаревших данных.
Для стримов нужны новые decoded frames и освобождение capture после последнего viewer.

## Android

В каталоге `android` с установленными JDK/SDK:

```powershell
./gradlew.bat assembleDebug test
```

В Bash используется `./gradlew assembleDebug test`. Debug artifact не равен
подписанной pilot OTA-сборке. Настройки discovery/signing, установка и limitations —
в [Android guide](android-agent.md) и [Local pilot](operations/LOCAL-PILOT.md).
Не меняйте signing key при обновлении уже установленного APK.

Unit tests не доказывают boot, root grants, screen capture или OTA конкретного Android.
Для native приёмки фиксируйте версию APK, PID/crash buffers, device ID, receipts,
recovery и ресурсы. [Безопасный soak](operations/ANDROID-OVERNIGHT-SOAK.md).

## Перед PR

Сохраните воспроизведение и regression, обновите документ соответствующего контракта,
отдельно назовите не выполненные проверки. Для migrations проверьте единственный
Alembic head, grants runtime-role, upgrade существующего volume и rollback-план.
Не запускайте downgrade или очистку на ценных данных ради теста.

[Contributing](../CONTRIBUTING.md) задаёт коммиты/review;
[актуальность документов](DOCUMENTATION.md) — статусы source/installed/accepted;
[Support](../SUPPORT.md) — минимальные данные для разбора инцидента.
