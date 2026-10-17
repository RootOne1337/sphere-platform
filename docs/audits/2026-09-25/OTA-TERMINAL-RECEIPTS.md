# AUD-171 · Терминальные receipts адресного Android OTA

**Дата:** 25 сентября 2026 · **Severity:** P1 operational reliability ·
**Статус:** source fix and regression suites pass; pilot deploy/canary still pending.

[Документация](../../README.md) ·
[OTA architecture](../../architecture/ANDROID-OTA-RELIABILITY.md) ·
[Local pilot](../../operations/LOCAL-PILOT.md) ·
[Open stream state](ANDROID-STREAM-OBSERVABILITY.md)

## Finding

Адресный recovery OTA доставлял одноразовый `OTA_UPDATE`, но terminal receipt
терялся на обеих сторонах контракта. Сервер только записывал ответ в log, не
сохранял его и не отправлял `result_ack`. Android удалял локальную durable-запись
сразу после того, как `WebSocket.send()` принимал её в локальную очередь OkHttp.
Это подтверждало постановку в очередь, но не передачу по сети и не сохранение
результата сервером. После обрыва между этими этапами нельзя было достоверно
узнать, завершилась ли установка.

Оставался и повторный сбойной путь: даже после добавления серверного сохранения,
потеря первого ACK оставляла recovery grant уже удалённым. Повтор при reconnect
попадал в обычный `command_result` handler и не распознавался как ранее сохранённый
OTA receipt. Обе стороны должны удерживать запись до подтверждённого commit/ACK и
повторно обрабатывать один и тот же результат идемпотентно.

## Root cause и доказательство

До исправления `serve_ota_recovery()` в
`backend/api/ws/android/router.py` выводил `status`/классифицированную ошибку в
лог, но не вызывал commit и не посылал `result_ack`. На Android
`CommandDispatcher.queueDurableResult()` удалял запись OTA, когда `sendJson()`
возвращал `true`; это значение говорит только о принятии сообщения клиентской
очередью. Обычный task-result handler сохраняет DAG результат; recovery-команда
не является task и не имеет строки `Task`, поэтому этот путь не был источником
истины для OTA.

Регрессионный сценарий отправляет терминальный `completed` receipt с установленной
версией, проверяет сохранение его на Device и ACK только после commit. Отдельный
сценарий заставляет commit завершиться ошибкой и доказывает, что ACK не уходит.
Тест потерянного ACK повторно отправляет тот же receipt через обычный
авторизованный WebSocket и подтверждает idempotent ACK только для совпадающего
результата. Версия ниже целевой не подтверждает установку и не получает ACK.
Интеграционный тест проверяет, что receipt replay читается только в tenant
устройства.

## Изменение

- Сервер сохраняет только allowlisted поля terminal receipt в существующем
  `Device.meta`, удаляет активный recovery grant одной транзакцией и отвечает
  `result_ack` только после успешного commit.
- Android сохраняет OTA receipt в зашифрованном журнале, пока не получит явный
  `result_ack`. Поле `ota_recovery_receipt` отличает его от DAG результата; старые
  ожидающие OTA-записи получают этот маркер при миграции журнала.
- Произвольный текст ошибки агента не сохраняется; наружу попадает только
  ограниченный классификатор `failure_code`.
- Последние 32 уникальных command receipts остаются в bounded history. При
  повторной доставке после потерянного ACK обычный authenticated handler
  подтверждает только совпадающие `command_id`, status и итог установки/код ошибки.
- `GET /api/v1/updates/recovery/{device_id}` показывает активное разрешение и
  receipts только для устройства текущего tenant; поле `authorization_tag` в
  ответ не включается.

Изменение использует уже существующее JSON поле и не требует миграции схемы.
Обычная публикация OTA catalog и адресная recovery команда остаются разными
операциями.

## Проверки

- `tests/test_agent_discovery/test_ota_clone_recovery.py` и
  `tests/test_updates/test_updates_api.py`: **61 passed**, 6 warnings.
- Полная `tests/production` suite с отдельными локальными PostgreSQL/Redis:
  **812 passed**, 2 warnings. Эти сервисы были изолированы от pilot.
- Android `:app:testDevDebugUnitTest`: **650 tests, 0 failures, 0 errors, 1 skipped**;
  включая replay, migration и удержание outbox до server ACK.
- Ruff и `git diff --check`: passed.
- GitHub run для исходного кода `182d40b` выявил только устаревшие
  `docs/openapi.json` и `docs/api-endpoints.md`. Причину воспроизвели в Python 3.12
  с теми же закреплёнными зависимостями, что в CI; после генерации обеих страниц
  `python -m scripts.export_api_docs --check` прошёл. GitHub CI повторно запускается
  после отправки этого документационного commit.
- Source tests не доказывают runtime rollout.

## Текущий canary и residual risk

Candidate APK **1.2.21-dev / 10221** собран из `182d40b` и прошёл подпись/metadata
проверку: пакет `com.sphereplatform.agent.pilot.debug`, 8 504 385 bytes,
SHA-256 `69a275b052477f8b0ce445149369ecba3b566c42f3d2a0fae0b6f5641deb98f8`,
signer SHA-256 `3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f`.
Файл для локального canary:
`.local-pilot/apk/SphereAgent-pilot-candidate-1.2.21-dev-182d40b.apk`.
Он не установлен и не опубликован. Изолированный pilot
остаётся на image `b491a66`; последний ADB snapshot показывал `emulator-5554` на 10220 после ручной
установки, `emulator-5556` — 10219, а серверная запись 5556 `offline` без heartbeat
и agent version. Новая сборка использует действующий в локальном bootstrap mirror
вместо ранее сохранённого устаревшего mirror; GitHub Raw primary и gateway mirror
— два источника manifest, оба отдали signed manifest v24. Это разные config
origins. При этом service API/WSS endpoint внутри signed manifest указывает на
тот же Quick Tunnel, поэтому ingress control/video plane остаётся одним fault
domain. Адресный canary ещё не
принят; общая OTA-публикация не выполнялась. Удалённые устройства и поток кадров
этим исправлением не проверены.

После обновления backend обязательны canary gates: видимый `active` grant, APK
download hash, `completed` receipt с версией не ниже target, отсутствие grant,
подтверждённый `recent_results` после reconnect и фактический новый heartbeat.
Только после этого можно рассматривать канал `android/dev`. Если устройство
полностью offline, оно не может получить удалённую команду до восстановления
связи; receipt persistence не создаёт сеть и не гарантирует установку без
устройства в сети.
