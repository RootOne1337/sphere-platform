# Локальный стенд для совместного тестирования

**12 сентября 2026 · Windows / Docker Desktop · development, авторизация включена.**

[Главная](../../README.md) · [Приёмка](PILOT-ACCEPTANCE.md) ·
[Готовность](READINESS.md) · [Android](../android-agent.md)

## Какая установка запущена

Новый Compose project — **`sphere-pilot-20260911`**, из checkout
`C:\Users\dimas\Documents\ChatGPT\sphere-platform`.
Дата в имени — постоянный идентификатор установки, его не меняют при перезапуске.
Старый project `sphere-platform` из `C:\Users\dimas\Documents\sphere-platform`,
его tunnel, контейнеры и volumes не используются новым стендом.

| Компонент | Адрес на рабочей станции | Проверено |
| --- | --- | --- |
| Web + API + WebSocket gateway | <http://127.0.0.1:18080> | Вход, dashboard, список устройств, reload с refresh сессии |
| API readiness | <http://127.0.0.1:18080/api/v1/health/readyz> | HTTP 200 через Nginx, PostgreSQL и Redis готовы |
| n8n | <http://127.0.0.1:15678> | HTTP `/healthz` 200; выполнение workflows ещё не проверено |
| MinIO S3 / console | `127.0.0.1:19000` / <http://127.0.0.1:19001> | Container health; прикладной screenshot flow ещё не проверен |
| PostgreSQL / Redis | Только собственная Docker network | Миграции и bootstrap, отдельные persistent volumes |

В Docker Desktop семь сервисов объединены под новым именем. Backend и frontend
работают из собранных образов, без source bind mounts и установки npm при старте.
Backend выполняет четыре Gunicorn workers. Все семь сервисов имеют healthcheck и
`restart: unless-stopped`; после запуска Docker они возобновляют работу, если
оператор не остановил их вручную. Docker Desktop должен быть запущен.

## Вход и управление

Логин **`admin@example.com`**. Уникальный пароль создан только для этой установки
и хранится в `.local-pilot/operator-credentials.json` в указанном checkout.
Секреты БД/Redis/n8n/MinIO — в `.local-pilot/pilot.env`; эти файлы игнорируются Git.
Admin и enrollment key принадлежат одной организации `local-pilot-20260911`.

На этой рабочей станции повторный запуск и статус выполняются из корня checkout:

```powershell
python .local-pilot/manage.py up -d --wait --wait-timeout 180
python .local-pilot/manage.py ps --all
python .local-pilot/manage.py logs --since 10m --tail 100 backend
python .local-pilot/manage.py verify-old
```

Сгенерированный local helper фиксирует `--project-name`, `--project-directory`,
`--env-file` и три overlay, удаляет конфликтующие Compose/config значения из
унаследованного environment. Он и installation manifest находятся в `.local-pilot/`
и относятся к этому компьютеру. Нельзя заменять эту команду обычным `docker compose
up` без выбранного project/env. Никакой `down -v` для первого тестирования не нужен.

Версионируемый профиль — [docker-compose.local-pilot.yml](../../docker-compose.local-pilot.yml).
Он применяется **после** base и full; требует Compose с `!reset`/`!override`.
На другом компьютере сначала нужны собственные env, agent config, schema migration,
admin и enrollment bootstrap; копирование одного overlay не подготавливает БД.

## APK именно для нового стенда

Готовый файл и `manifest.json` находятся в **`.local-pilot/apk/`**. Это подписанный
**dev debug APK**, а не production release. Пакет
`com.sphereplatform.agent.pilot.debug` позволяет установить его рядом с обычными
dev/enterprise сборками, сохраняя отдельные credentials и identity.

Сборка задаёт четыре параметра только текущему процессу Gradle:

| Переменная | Назначение этого стенда |
| --- | --- |
| `SPHERE_SERVER_URL` | `http://10.0.2.2:18080` |
| `SPHERE_CONFIG_URL` | `http://10.0.2.2:18080/api/v1/config/agent` |
| `SPHERE_ENROLLMENT_KEY` | Ключ из локального agent config, предварительно seeded в новую БД |
| `SPHERE_DEV_APPLICATION_ID_SUFFIX` | `.pilot` |

Обычные dev defaults и enterprise flavor без этих overrides сохранены.
`GIT_SHA` передаётся при сборке; manifest фиксирует revision, SHA-256, размер и
application ID. Dev discovery направлен на этот же локальный сервер и не зависит
от общей GitHub-конфигурации старой установки. Второй URL той же машины не является
отдельным отказоустойчивым сервером.

`10.0.2.2` — выбранный адрес host loopback для Android Emulator. Если другой
эмулятор использует иной host gateway, надо согласовать его маршрут. Порты этого
стенда опубликованы только на `127.0.0.1`: физический телефон и другая рабочая
станция по LAN пока не подключены. Этот APK автоматически туда не устанавливался.

## Доказательства и следующий тест

- На свежих volumes применена schema до `20260910_device_refresh_retry`, затем
  выполнены реальные CLI создания admin и enrollment key.
- Playwright проверил login HTTP 200 → dashboard → devices HTTP 200. После reload
  `/auth/refresh` вернул 200, пользователь остался на `/devices`. Первый 401 refresh
  в чистом браузере до login ожидаем и не принят за дефект.
- UI показывает **0 устройств** из новой базы: фиктивные online devices не добавлялись.
- AUD-88 выявлен при настоящем запуске: CRLF ломал Nginx. Три Git checkout cases
  падали до LF attributes и проходят после; gateway после исправления отвечает.
- Полный локальный deployment suite: **98 passed / 85.25 s**. Он включает три
  checkout regression и две проверки реального Compose merge локального профиля:
  изоляция ресурсов/портов, image defaults, включённая auth и healthchecks.
- Проверяется неизменность всех 29 прежних контейнеров; в local manifest сохранены
  их ID/image/status/start time. Evidence и APK содержатся в игнорируемом
  `.local-pilot/`; значения секретов не включаются в публичный отчёт.

**Следующий шаг:** установить pilot APK на один эмулятор, выдать нужные Android
разрешения, подтвердить регистрацию и `auth_ok`, найти тот же device ID в UI,
выполнить простое задание и проверить reconnect без переустановки.

**Пока не подтверждено:** исполнение APK на устройстве, end-to-end задание,
стриминг, physical-device/LAN режим, VPN, external PC-agent, длительная нагрузка
и массовое восстановление. Управляемый WG/AWG router для нового стенда не настроен;
VPN-блок dashboard с нулём туннелей не доказывает доступность router. Отдельный
Prometheus/Grafana/Loki stack не включён этим профилем. n8n требует первого входа
и настройки workflows; контейнер health не равен работающей интеграции.
